#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Telegram : https://t.me/routekernel1
# YouTube  : https://youtube.com/@routekernel
# Project  : https://github.com/dreamboxone/piip
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
# Unauthorised reverse engineering or removal of this notice is prohibited.
#
"""Live translation pipeline. Runs as its own process, not inside Enigma2.

    ffmpeg #1 ── video (copy)  ─────────────► PacketDelay ──┐
              ├─ audio 48k st  ─────────────► ByteDelay  ──┤
              └─ audio 16k mono ──► Gemini ──► TranslationBuffer
                                                            │
                                        Mixer(gainA, gainB) ┘
                                                            ▼
                                       ffmpeg #2 (video copy + AAC)
                                                            ▼
                                       http://127.0.0.1:PORT/live.ts

Video is stream-copied end to end, so cost is independent of resolution and
4K behaves exactly like SD. Only audio is decoded, translated and re-encoded.

Deliberately a separate process: it moves several MB/s and talks to the
network, and none of that belongs inside the Enigma2 main loop.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translate import mixer as mx
from translate import redact
from translate.gemini import GeminiTranslator, IN_RATE
from utils.compat import popen_keep_fds
from utils import diaglog

try:
    import Queue as queue                 # Python 2
except ImportError:
    import queue
try:
    from urllib2 import Request, urlopen  # Python 2
    from urlparse import urljoin
except ImportError:
    from urllib.request import Request, urlopen
    from urllib.parse import urljoin


def pick_variant(text, base, max_bandwidth=0):
    """The rendition URL an HLS master playlist should be read from.

    ffmpeg given a master opens every rendition at once: twice the download,
    a much slower start and segment bursts from both. Returns None when the
    playlist is not a master, or when renditions carry their audio in a
    separate group (reading only the video playlist would lose the sound).
    """
    if '#EXT-X-STREAM-INF' not in text:
        return None
    lines = [l.strip() for l in text.splitlines()]
    audio_groups = set()
    for l in lines:
        if l.startswith('#EXT-X-MEDIA') and 'TYPE=AUDIO' in l and 'URI=' in l:
            m = re.search(r'GROUP-ID="([^"]+)"', l)
            if m:
                audio_groups.add(m.group(1))
    found = []
    for i, l in enumerate(lines):
        if not l.startswith('#EXT-X-STREAM-INF'):
            continue
        uri = next((x for x in lines[i + 1:] if x and not x.startswith('#')), None)
        if not uri:
            continue
        m = re.search(r'AUDIO="([^"]+)"', l)
        if m and m.group(1) in audio_groups:
            continue
        bw = re.search(r'(?<![-A-Z])BANDWIDTH=(\d+)', l)
        found.append((int(bw.group(1)) if bw else 0, urljoin(base, uri)))
    if not found:
        return None
    if max_bandwidth:
        fitting = [v for v in found if v[0] <= max_bandwidth]
        # Nothing small enough: the lightest there is.
        return max(fitting) if fitting else min(found)
    best = max(found)
    return best


def steady():
    """A clock NTP cannot move.

    A receiver sets its wall clock some minutes after boot; measured with
    time.time() that jump looked like "no input for 175 s", restarted a
    healthy source and blanked the picture.
    """
    tick = getattr(time, 'monotonic', None)
    return tick() if tick is not None else os.times()[4]


class _Pipeline(object):
    """One ingest + mux generation; replaced whole when the source fails."""

    def __init__(self):
        self.stop = threading.Event()
        self.procs = []
        self.threads = []
        self.fds = []
        self.last_input = steady()
        self.got_input = False
        self.errors = []

CHUNK_MS = 20
MAX_GAIN = 1.0        # a mixer gain, not an amplifier
# A source that stalls longer than the delay buffer would freeze the picture
# every time. After a starvation the buffer grows by this much, so the next
# stall of the same length is absorbed instead of seen.
REBUFFER_STEP_S = 3.0
MAX_EXTRA_DELAY_S = 12.0
STARVE_TICKS = 10         # 200 ms without programme audio is a starvation
INGEST_STALL_S = 45.0     # no input at all for this long: restart the source
MAX_RESTARTS = 30
AUDIO_CHUNK = int(mx.OUT_BPS * CHUNK_MS / 1000.0)          # bytes per tick
GEMINI_CHUNK = int(IN_RATE * 2 * 0.10)                      # 100 ms mono @16k

DEFAULTS = {
    'url': '',
    'api_key': '',
    'model': None,
    'language': 'Persian',
    'delay': 6.0,
    'gain_original': 0.25,
    'gain_translated': 1.0,
    'max_backlog': 6.0,
    'http_port': 8901,
    'control_port': 8902,
    'ffmpeg': 'ffmpeg',
    'user_agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3',
    'http_headers': {},
    'log': '/tmp/piip_engine.log',
    'translate': True,
    # Recorded content must be read at native rate, otherwise ffmpeg races
    # ahead and floods both the delay buffer and the Gemini session.
    'realtime': False,
    'start_at': 0.0,
    'duration': 0,
    # Copy the stream through untouched. Used whenever there is nothing to
    # translate, which is most of the time.
    'passthrough': False,
    # Diagnostics: a session folder (utils/diaglog.py) receives a line of
    # metrics per second, and optionally the first tap_mb of the output TS.
    'diag_dir': '',
    'tap_mb': 0,
    # Keep the audio sent to Gemini and the speech it returned, each with a
    # time index, so translation latency and quality can be judged later.
    'dump_audio': False,
    # Translated speech is scheduled this many seconds before the programme
    # position that had been sent when it came back (the model's latency).
    'translation_lead': 1.0,
    # 0 = the highest rendition of an HLS master playlist.
    'max_bandwidth': 0,
    # Read live sources no faster than they play. Off: ffmpeg's HLS reader
    # then fetches each segment in one burst, which rides out a network
    # hiccup; the read-ahead only lengthens the delay line, and the
    # translation is scheduled on that same timeline.
    'ingest_realtime': False,
    # Optional ffmpeg filter for the copy Gemini hears only. Off: measured
    # on the same recording, a speech band + compressor cut the translated
    # share from 73% to 25% - Live Translate recognises the untouched mix best.
    'gemini_filter': '',
}


class Log(object):
    def __init__(self, path, extra=None):
        self.path = path
        self._lock = threading.Lock()
        self.handles = []
        for target in (path, extra):
            if not target:
                continue
            try:
                self.handles.append(open(target, 'a', 1))
            except Exception:
                pass
        if not self.handles:
            self.handles.append(sys.stderr)

    def __call__(self, *parts):
        # ffmpeg commands and stream URLs carry the account's secrets.
        line = '%s %s\n' % (time.strftime('%H:%M:%S'),
                            redact.text(' '.join(str(p) for p in parts)))
        with self._lock:
            for fh in self.handles:
                try:
                    fh.write(line)
                except Exception:
                    pass


class Meter(object):
    """Per-second counters and peaks, read and reset by the metrics thread.

    Plain dict updates under the GIL; a lost increment at a second boundary
    does not matter for a diagnosis, a lock on every pipe read would.
    """

    def __init__(self):
        self.counts = {}
        self.peaks = {}

    def add(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def peak(self, name, value):
        if value > self.peaks.get(name, 0):
            self.peaks[name] = value

    def take(self):
        counts, peaks = self.counts, self.peaks
        self.counts, self.peaks = {}, {}
        return counts, peaks


def _cpu_ticks(pid):
    try:
        with open('/proc/%d/stat' % pid) as fh:
            fields = fh.read().rsplit(')', 1)[1].split()
        return int(fields[11]) + int(fields[12])
    except Exception:
        return None


def _write_all(fd, data):
    """Write every byte: an unbuffered pipe write can be partial."""
    view = memoryview(data)
    while len(view):
        sent = os.write(fd, view)
        if not sent:
            raise OSError('pipe closed')
        view = view[sent:]


def _child_fds(mapping):
    """preexec_fn that renumbers inherited fds to fixed numbers in the child."""
    def _pre():
        for target in sorted(mapping):
            os.dup2(mapping[target], target)
    return _pre


class Engine(object):
    def __init__(self, cfg):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(cfg or {})
        self.diag_dir = self.cfg.get('diag_dir') or ''
        self.log = Log(self.cfg['log'],
                       os.path.join(self.diag_dir, 'engine.log')
                       if self.diag_dir else None)
        self.meter = Meter()
        self.metrics = diaglog.JsonLines(
            os.path.join(self.diag_dir, 'engine.jsonl')
            if self.diag_dir else None)
        self.tap_queue = None
        self.dumps = {}
        self.stopping = threading.Event()
        self.started_at = time.time()

        # The translated queue must include the intentional A/V delay plus a
        # small recovery reserve.  Otherwise a perfectly healthy translation
        # is discarded merely because the viewer is intentionally delayed.
        queue_cap = max(float(self.cfg['max_backlog']),
                        float(self.cfg['delay']) + 4.0)
        # Passthrough copies the stream and mixes nothing, so it must not
        # ask for an audio backend: on Python 3.13 and later there is no
        # stdlib audioop, and demanding one here stopped the source engine
        # of the dub pipeline from starting at all.
        self.mixer = None
        if not self.cfg.get('passthrough'):
            self.mixer = mx.Mixer(self.cfg['delay'], queue_cap)
            self.mixer.gain_original = float(self.cfg['gain_original'])
            self.mixer.gain_translated = float(self.cfg['gain_translated'])
        self.video = mx.PacketDelay(self.cfg['delay'], steady)

        self.ff_in = None
        self.ff_out = None
        self.gemini = None
        self.client_lock = threading.Lock()
        self.client = None
        self.stats = {'video_bytes': 0, 'audio_bytes': 0, 'out_bytes': 0,
                      'gemini_state': 'off'}
        self.start_at = float(self.cfg.get('start_at') or 0)
        self.emitted_bytes = 0
        self.clock_late_max_ms = 0
        self.audio_burst_max = 0
        # The player shows a black screen until both of these are true, so
        # it needs to be able to say "starting" rather than "playing".
        self.audio_started = False
        self.video_started = False
        self._threads = []
        self.base_delay = float(self.cfg['delay'])
        self.extra_delay = 0.0
        self.restarts = 0
        self.source_url = str(self.cfg['url'])
        self.source_is_hls = '.m3u' in self.source_url.lower().split('?')[0]
        # Programme clock shared by the 16 kHz input and the mix.
        self.input_origin = 0.0
        self.a16_bytes = 0

    # ------------------------------------------------------------- plumbing

    def _input_headers(self):
        lines = []
        for key, value in sorted((self.cfg.get('http_headers') or {}).items()):
            if value:
                lines.append('%s: %s' % (key, value))
        return ['-headers', '\r\n'.join(lines) + '\r\n'] if lines else []

    def _resolve_source(self):
        """Read a single HLS rendition instead of a whole master playlist."""
        url = str(self.cfg['url'])
        self.source_url = url
        self.source_is_hls = '.m3u' in url.lower().split('?')[0]
        if not url.lower().startswith(('http://', 'https://')):
            return
        if self.cfg.get('realtime'):
            return
        if not self.source_is_hls:
            # Xtream and Stalker links often hide an HLS playlist behind a
            # bare path; the first bytes tell.
            self.source_is_hls = self._looks_like_playlist(url)
            if not self.source_is_hls:
                return
        try:
            headers = dict((k, v) for k, v in
                           (self.cfg.get('http_headers') or {}).items() if v)
            headers['User-Agent'] = self.cfg['user_agent']
            handle = urlopen(Request(url, headers=headers), timeout=6)
            try:
                text = handle.read(262144).decode('utf-8', 'replace')
                base = handle.geturl()
            finally:
                handle.close()
            chosen = pick_variant(text, base, int(self.cfg.get('max_bandwidth') or 0))
            if chosen:
                self.source_url = chosen[1]
                self.log('[source] master playlist: reading one rendition, %d bit/s'
                         % chosen[0])
                handle = urlopen(Request(chosen[1], headers=headers), timeout=6)
                try:
                    text = handle.read(262144).decode('utf-8', 'replace')
                finally:
                    handle.close()
            m = re.search(r'#EXT-X-TARGETDURATION:\s*(\d+(?:\.\d+)?)', text)
            if m:
                # Segments arrive a whole segment at a time: a buffer shorter
                # than one segment (plus its download) runs dry at every one.
                need = float(m.group(1)) + 2.0
                if need > self.base_delay + self.extra_delay:
                    self.extra_delay = min(MAX_EXTRA_DELAY_S, need - self.base_delay)
                    self._apply_delay()
                self.log('[source] HLS segments of %ss: delay %.1fs'
                         % (m.group(1), self.base_delay + self.extra_delay))
        except Exception as exc:
            self.log('[source] playlist not inspected (%s); ffmpeg reads it' % exc)

    def _looks_like_playlist(self, url):
        try:
            headers = dict((k, v) for k, v in
                           (self.cfg.get('http_headers') or {}).items() if v)
            headers['User-Agent'] = self.cfg['user_agent']
            handle = urlopen(Request(url, headers=headers), timeout=6)
            try:
                head = handle.read(16)
                final = handle.geturl()
            finally:
                handle.close()
            if not isinstance(head, str):
                head = head.decode('latin-1')
            return '#EXTM3U' in head or '.m3u' in final.lower().split('?')[0]
        except Exception:
            return False

    def _input_args(self):
        cmd = [
            self.cfg['ffmpeg'], '-hide_banner', '-loglevel', 'warning', '-nostdin',
            '-fflags', '+nobuffer', '-flags', 'low_delay',
            '-analyzeduration', '2000000', '-probesize', '2000000',
        ]
        if self.source_is_hls:
            # Start at the live edge: an HLS channel otherwise takes about
            # twenty seconds to its first frame. Only the HLS demuxer knows
            # this option - given to any other input ffmpeg refuses to start,
            # which is what silently broke translation of .ts channels,
            # films and files.
            cmd += ['-live_start_index', '-1']
        if self.source_url.lower().startswith(('http://', 'https://')):
            cmd += ['-user_agent', self.cfg['user_agent']]
        cmd += self._input_headers()
        if self.source_url.lower().startswith(('http://', 'https://')):
            cmd += ['-reconnect', '1', '-reconnect_streamed', '1',
                    '-reconnect_delay_max', '2']
            # Do not use reconnect_at_eof here. On receiver FFmpeg 4.1 it
            # treats the normal end of an HLS manifest download as an outage
            # and loops forever before reading the first media segment.
        if self.cfg['realtime'] or self.cfg.get('ingest_realtime'):
            cmd.append('-re')
        start_at = float(self.cfg.get('start_at') or 0)
        if start_at > 0:
            # Input seeking: fast, and keeps the whole pipeline unchanged.
            cmd += ['-ss', '%.3f' % start_at]
        return cmd + ['-i', self.source_url]

    def _spawn_ingest(self, pipe):
        r48, w48 = os.pipe()
        r16, w16 = os.pipe()
        cmd = self._input_args() + [
            '-map', '0:v:0', '-c:v', 'copy',
            '-f', 'mpegts', '-muxdelay', '0', '-muxpreload', '0', 'pipe:1',
            '-map', '0:a:0', '-c:a', 'pcm_s16le',
            '-ar', str(mx.OUT_RATE), '-ac', str(mx.OUT_CH), '-f', 's16le', 'pipe:3',
        ]
        if self.cfg['translate']:
            cmd += ['-map', '0:a:0']
            if self.cfg.get('gemini_filter'):
                cmd += ['-af', self.cfg['gemini_filter']]
            cmd += ['-c:a', 'pcm_s16le',
                    '-ar', str(IN_RATE), '-ac', '1', '-f', 's16le', 'pipe:4']
        self.log('[ingest]', ' '.join(cmd))
        kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                      preexec_fn=_child_fds({3: w48, 4: w16}), bufsize=0)
        popen_keep_fds(kwargs, (w48, w16))
        p = subprocess.Popen(cmd, **kwargs)
        os.close(w48)
        os.close(w16)
        if not self.cfg['translate']:
            os.close(r16)
            r16 = None
        self.ff_in = p
        pipe.procs.append(p)
        return p, r48, r16

    def _spawn_passthrough(self, pipe):
        """One ffmpeg, copying both streams into a plain TS.

        This exists because the receiver's GStreamer cannot open the HLS
        streams directly; it can play a local MPEG-TS perfectly well.
        """
        cmd = self._input_args() + [
            '-map', '0:v:0?', '-map', '0:a:0?', '-c', 'copy',
            '-mpegts_flags', '+resend_headers',
            '-max_interleave_delta', '0',
            '-f', 'mpegts', '-muxdelay', '0', '-muxpreload', '0', 'pipe:1',
        ]
        self.log('[passthrough]', ' '.join(cmd))
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, close_fds=True,
                             bufsize=0)
        self.ff_in = p
        pipe.procs.append(p)
        return p

    def _spawn_mux(self, pipe):
        rpcm, wpcm = os.pipe()
        cmd = [
            self.cfg['ffmpeg'], '-hide_banner', '-loglevel', 'warning', '-nostdin',
            # A bigger queue: ffmpeg warns and stalls on the default of 8
            # when two live pipes feed it.
            '-thread_queue_size', '4096',
            # Pace the delayed TS from its own PCR/DTS.  This prevents HLS
            # segment bursts making DreamOS alternately race and stall.
            '-re', '-fflags', '+genpts+discardcorrupt',
            # The TS is generated by our own ingest process and already has
            # PAT/PMT. A short probe prevents FFmpeg holding the PCM writer
            # for its default multi-second analysis window at startup.
            '-analyzeduration', '300000', '-probesize', '500000',
            '-f', 'mpegts', '-i', 'pipe:0',
            '-thread_queue_size', '4096',
            '-f', 's16le', '-ar', str(mx.OUT_RATE), '-ac', str(mx.OUT_CH),
            '-i', 'pipe:3',
            '-map', '0:v:0', '-c:v', 'copy',
            # Raw PCM has no timestamps. Generate a strictly monotonic sample
            # clock and absorb scheduler jitter without changing video speed.
            '-filter_complex',
            '[1:a]aresample=48000:async=1:first_pts=0,'
            'asetpts=N/SR/TB[audio]',
            '-map', '[audio]', '-c:a', 'aac', '-b:a', '128k',
            # resend_headers repeats PAT/PMT before every keyframe, so a
            # player that joins mid-stream locks on at the next one instead
            # of staying black until it happens to find them.
            '-mpegts_flags', '+resend_headers',
            # Never hold one stream back waiting for the other.
            '-max_muxing_queue_size', '256',
            '-max_interleave_delta', '200000', '-flush_packets', '1',
            '-avoid_negative_ts', 'make_zero',
            '-f', 'mpegts', '-muxdelay', '0', '-muxpreload', '0', 'pipe:1',
        ]
        self.log('[mux]', ' '.join(cmd))
        kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE,
                      preexec_fn=_child_fds({3: rpcm}), bufsize=0)
        popen_keep_fds(kwargs, (rpcm,))
        p = subprocess.Popen(cmd, **kwargs)
        os.close(rpcm)
        self.ff_out = p
        pipe.procs.append(p)
        pipe.fds.append(wpcm)
        return p, wpcm

    # -------------------------------------------------------------- readers

    def _t(self, fn, name, pipe=None):
        t = threading.Thread(target=self._guard, args=(fn, name, pipe), name=name)
        t.daemon = True
        t.start()
        (pipe.threads if pipe is not None else self._threads).append(t)
        return t

    def _guard(self, fn, name, pipe=None):
        try:
            fn()
        except Exception as e:
            if not self.stopping.is_set() and not (pipe and pipe.stop.is_set()):
                self.log('[%s] died: %s' % (name, e))
                self.log(traceback.format_exc())

    def _read_video(self, pipe, fh):
        while not pipe.stop.is_set():
            data = fh.read(32768)
            if not data:
                break
            pipe.last_input = steady()
            pipe.got_input = True
            self.stats['video_bytes'] += len(data)
            self.meter.add('v_in', len(data))
            self.video.write(data)
        self.log('[video] ingest ended')

    def _read_audio48(self, pipe, fd):
        with os.fdopen(fd, 'rb', 0) as fh:
            while not pipe.stop.is_set():
                data = fh.read(AUDIO_CHUNK * 4)
                if not data:
                    break
                pipe.last_input = steady()
                self.stats['audio_bytes'] += len(data)
                self.meter.add('a48_in', len(data))
                self.mixer.feed_original(data)
        self.log('[audio48] ended')

    def _read_audio16(self, pipe, fd):
        with os.fdopen(fd, 'rb', 0) as fh:
            buf = b''
            while not pipe.stop.is_set():
                data = fh.read(GEMINI_CHUNK)
                if not data:
                    break
                buf += data
                self.meter.add('a16_in', len(data))
                while len(buf) >= GEMINI_CHUNK:
                    chunk, buf = buf[:GEMINI_CHUNK], buf[GEMINI_CHUNK:]
                    self.a16_bytes += len(chunk)
                    if self.gemini:
                        # Never the network here: this thread is what keeps
                        # ffmpeg's pipes moving, picture included. The chunk
                        # carries its programme position so the reply can be
                        # played against the picture it belongs to.
                        self.gemini.enqueue(chunk, self.input_position())
                        self.meter.add('gem_queued', len(chunk))
        self.log('[audio16] ended')

    def input_position(self):
        """Programme seconds of 16 kHz input read so far (same clock as the mix)."""
        return self.input_origin + self.a16_bytes / float(IN_RATE * 2)

    def _drain_stderr(self, pipe, proc, tag):
        for line in iter(proc.stderr.readline, b''):
            if pipe.stop.is_set() or self.stopping.is_set():
                break
            line = line.decode('utf-8', 'replace').strip()
            if line:
                pipe.errors = (pipe.errors + [line])[-20:]
                self.log('[%s]' % tag, line)

    # ----------------------------------------------------------------- pump

    def _pump_audio(self, pipe, wpcm):
        """Feed mixed audio at real time.

        This runs on its own thread: sharing one with the video writer let a
        full audio pipe block the video ffmpeg was waiting for.
        """
        next_tick = steady()
        started = False
        starved = 0
        while not pipe.stop.is_set():
            now = steady()
            sleep = next_tick - now
            if sleep > 0:
                pipe.stop.wait(min(sleep, CHUNK_MS / 1000.0))
                continue
            self.clock_late_max_ms = max(
                self.clock_late_max_ms, int(max(0.0, now - next_tick) * 1000))
            if now - next_tick > 1.0:
                # A long scheduling gap: resume from now rather than burst.
                next_tick = now
            sent = 0
            # Preserve the PCM sample clock after a short scheduling pause,
            # but bound catch-up so a late Python thread cannot flood FFmpeg.
            while next_tick <= now + 0.001 and sent < 5:
                chunk = self.mixer.pull(AUDIO_CHUNK)
                next_tick += CHUNK_MS / 1000.0
                sent += 1
                if chunk is None:
                    if started:
                        self.meter.add('pcm_starved')
                        starved += 1
                        if starved == STARVE_TICKS:
                            self._rebuffer()
                    continue               # still filling the delay buffer
                starved = 0
                if not started:
                    started = True
                    self.audio_started = True
                    self.log('[pump] audio flowing')
                self._note_mix()
                t0 = time.time()
                try:
                    _write_all(wpcm, chunk)
                except OSError:
                    self.log('[pump] audio pipe closed')
                    return
                self.meter.peak('pcm_write_ms', int((time.time() - t0) * 1000))
                self.meter.add('pcm_out', len(chunk))
                self.emitted_bytes += len(chunk)
            self.audio_burst_max = max(self.audio_burst_max, sent)
        self.log('[pump] audio ended')

    def _rebuffer(self):
        """Grow the delay after the source ran dry, for picture and sound alike."""
        if self.extra_delay >= MAX_EXTRA_DELAY_S:
            return
        self.extra_delay = min(MAX_EXTRA_DELAY_S, self.extra_delay + REBUFFER_STEP_S)
        self._apply_delay()
        self.meter.add('rebuffer')
        self.log('[pump] source ran dry: buffering %.0fs more (delay now %.1fs)'
                 % (REBUFFER_STEP_S, self.base_delay + self.extra_delay))

    def _apply_delay(self):
        d = self.base_delay + self.extra_delay
        self.video.set_delay(d)
        if self.mixer is None:
            return
        self.mixer.set_delay(d)
        # Scheduled speech legitimately waits up to the whole delay before
        # it is due; a cap below that would throw good translation away.
        self.mixer.translated.max_backlog = max(
            float(self.cfg['max_backlog']), d + 6.0)

    def _pump_video(self, pipe, fd):
        """Release delayed video packets as their hold time expires."""
        started = False
        while not pipe.stop.is_set():
            packets = self.video.drain()
            if not packets:
                pipe.stop.wait(0.01)
                continue
            if not started:
                started = True
                self.video_started = True
                self.log('[pump] video flowing')
            for packet in packets:
                t0 = time.time()
                try:
                    _write_all(fd, packet)
                except OSError:
                    self.log('[pump] video pipe closed')
                    return
                self.meter.peak('v_write_ms', int((time.time() - t0) * 1000))
                self.meter.add('v_out', len(packet))
        self.log('[pump] video ended')

    def _serve_output(self, pipe, fh):
        while not pipe.stop.is_set():
            data = fh.read(16384)
            if not data:
                break
            self.stats['out_bytes'] += len(data)
            self.meter.add('mux_out', len(data))
            with self.client_lock:
                c = self.client
            if c is None:
                self.meter.add('discard', len(data))
                continue                       # nobody watching: discard
            t0 = time.time()
            try:
                c.sendall(data)
                self.meter.peak('client_send_ms',
                                int((time.time() - t0) * 1000))
                self.meter.add('client_out', len(data))
                self._tap(data)
            except Exception as exc:
                self.meter.add('client_drop')
                self.log('[out] client dropped after %dms: %s'
                         % (int((time.time() - t0) * 1000), exc))
                with self.client_lock:
                    if self.client is c:
                        self.client = None
                try:
                    c.close()
                except Exception:
                    pass
        self.log('[out] mux ended')

    # -------------------------------------------------------------- sockets

    def _http_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', int(self.cfg['http_port'])))
        srv.listen(4)
        srv.settimeout(1.0)
        self.log('[http] listening on 127.0.0.1:%s' % self.cfg['http_port'])
        while not self.stopping.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(5.0)
                conn.recv(4096)
                conn.sendall(b'HTTP/1.0 200 OK\r\n'
                             b'Content-Type: video/mp2t\r\n'
                             b'Cache-Control: no-cache\r\n'
                             b'Connection: close\r\n\r\n')
                # A wedged decoder must not fill every pipe and freeze source
                # ingestion. Enigma2 can reconnect to the still-live engine.
                conn.settimeout(3.0)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                continue
            with self.client_lock:
                old, self.client = self.client, conn
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self.meter.add('client_attach')
            self.log('[http] client attached')
        srv.close()

    def _control_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', int(self.cfg['control_port'])))
        srv.listen(4)
        srv.settimeout(1.0)
        self.log('[ctl] listening on 127.0.0.1:%s' % self.cfg['control_port'])
        while not self.stopping.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(5.0)
                data = conn.recv(8192).decode('utf-8', 'replace').strip()
                reply = self._command(json.loads(data)) if data else {}
                conn.sendall((json.dumps(reply) + '\n').encode())
            except Exception as e:
                try:
                    conn.sendall((json.dumps({'ok': False,
                                              'error': str(e)}) + '\n').encode())
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        srv.close()

    def _command(self, req):
        cmd = req.get('cmd')
        if self.mixer is None and cmd in ('set_gain', 'status'):
            # Passthrough has no mixer: answer with what this mode does have.
            if cmd == 'set_gain':
                return {'ok': False, 'error': 'passthrough has no mixer'}
            return {'ok': True,
                    'uptime': round(time.time() - self.started_at, 1),
                    'position': round(self.position(), 1),
                    'flowing': bool(self.video_started),
                    'duration': int(self.cfg.get('duration') or 0),
                    'seekable': bool(self.cfg.get('realtime')),
                    'passthrough': True,
                    'delay': self.video.seconds,
                    'clock_late_max_ms': self.clock_late_max_ms,
                    'video_held': self.video.bytes_held,
                    'gemini': self.stats['gemini_state'],
                    'stats': dict(self.stats)}
        if cmd == 'set_gain':
            # 1.0 is the ceiling: above unity the sum just clips.
            if 'original' in req:
                self.mixer.gain_original = max(
                    0.0, min(MAX_GAIN, float(req['original'])))
            if 'translated' in req:
                self.mixer.gain_translated = max(
                    0.0, min(MAX_GAIN, float(req['translated'])))
            return {'ok': True,
                    'original': self.mixer.gain_original,
                    'translated': self.mixer.gain_translated}
        if cmd == 'set_delay':
            d = max(0.0, min(15.0, float(req.get('seconds', 4.0))))
            self.base_delay = d
            self._apply_delay()
            return {'ok': True, 'delay': d}
        if cmd == 'status':
            return {'ok': True, 'uptime': round(time.time() - self.started_at, 1),
                    'position': round(self.position(), 1),
                    'flowing': bool(self.audio_started and self.video_started),
                    'duration': int(self.cfg.get('duration') or 0),
                    'seekable': bool(self.cfg.get('realtime')),
                    'gain_original': self.mixer.gain_original,
                    'gain_translated': self.mixer.gain_translated,
                    'delay': self.mixer.original.seconds,
                    'backlog': round(self.mixer.translated.backlog_seconds(), 2),
                    'translation_tempo': round(self.mixer.translated.speed, 4),
                    'translation_dropped_ms': int(
                        self.mixer.translated.dropped_bytes * 1000 / mx.OUT_BPS),
                    'translation_compressed_ms': int(
                        self.mixer.translated.compressed_bytes * 1000 / mx.OUT_BPS),
                    'translation_underruns': self.mixer.translated.underruns,
                    'original_fallback': bool(self.mixer.fallback),
                    'active_original_gain': round(
                        self.mixer.active_original_gain, 3),
                    'clock_late_max_ms': self.clock_late_max_ms,
                    'audio_burst_max': self.audio_burst_max,
                    'video_held': self.video.bytes_held,
                    'gemini': self.stats['gemini_state'],
                    'stats': dict(self.stats)}
        if cmd == 'stop':
            self.stop()
            return {'ok': True}
        return {'ok': False, 'error': 'unknown command %r' % cmd}

    # ---------------------------------------------------------- diagnostics

    def _note_mix(self):
        m = self.mixer
        if m is None:
            return
        self.meter.add('mix_ticks')
        if m.last_present:
            self.meter.add('present_ticks')
        self.meter.add('orig_rms_sum', m.last_orig_rms)
        self.meter.peak('orig_rms_max', m.last_orig_rms)
        self.meter.add('trans_rms_sum', m.last_trans_rms)
        self.meter.peak('trans_rms_max', m.last_trans_rms)

    def _dump(self, name, pcm, t):
        if not (self.diag_dir and self.cfg.get('dump_audio')):
            return
        entry = self.dumps.get(name)
        if entry is None:
            try:
                entry = [open(os.path.join(self.diag_dir, name + '.pcm'), 'ab'),
                         open(os.path.join(self.diag_dir, name + '.idx'), 'a', 1),
                         0]
            except Exception:
                entry = [None, None, 0]
            self.dumps[name] = entry
        if entry[0] is None:
            return
        try:
            entry[0].write(pcm)
            # time, byte offset, length: enough to line speech up in time.
            entry[1].write('%.3f %d %d\n' % (t, entry[2], len(pcm)))
            entry[2] += len(pcm)
        except Exception:
            pass

    def _start_tap(self):
        limit = int(float(self.cfg.get('tap_mb') or 0) * 1048576)
        if not (self.diag_dir and limit > 0):
            return
        self.tap_queue = queue.Queue(maxsize=512)

        def writer():
            written = 0
            try:
                fh = open(os.path.join(self.diag_dir, 'output.ts'), 'ab')
            except Exception as exc:
                self.log('[tap] cannot open: %s' % exc)
                self.tap_queue = None
                return
            while not self.stopping.is_set() and written < limit:
                try:
                    data = self.tap_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                fh.write(data)
                written += len(data)
            fh.close()
            self.tap_queue = None
            self.log('[tap] closed after %d bytes' % written)
        self._t(writer, 'tap')

    def _tap(self, data):
        q = self.tap_queue
        if q is None:
            return
        try:
            q.put_nowait(data)
        except queue.Full:
            # The disk is slower than the stream: lose tap bytes, never
            # delay the decoder for the sake of a diagnosis.
            self.meter.add('tap_lost', len(data))

    def _metrics_loop(self):
        if self.metrics.fh is None:
            return
        try:
            tick = os.sysconf('SC_CLK_TCK')
        except Exception:
            tick = 100
        last = time.time()
        cpu_last = {}
        while not self.stopping.wait(1.0):
            now = time.time()
            span = max(0.001, now - last)
            last = now
            counts, peaks = self.meter.take()
            m = self.mixer
            ticks = counts.pop('mix_ticks', 0)
            rec = {
                't': round(now, 2),
                'up': round(now - self.started_at, 1),
                'mode': 'passthrough' if self.cfg.get('passthrough') else
                        ('translate' if self.gemini else 'engine'),
                'span': round(span, 3),
                'flowing': bool(self.audio_started and self.video_started),
                'client': self.client is not None,
                'gemini': self.stats.get('gemini_state'),
                'video_held_kb': self.video.bytes_held // 1024,
                'clock_late_max_ms': self.clock_late_max_ms,
                'mix_ticks': ticks,
            }
            if m is not None:
                # Passthrough mixes nothing and has no mixer to measure.
                rec.update({
                    'backlog': round(m.translated.backlog_seconds(), 2),
                    'tempo': round(m.translated.speed, 4),
                    'dropped_ms': int(
                        m.translated.dropped_bytes * 1000 / mx.OUT_BPS),
                    'underruns': m.translated.underruns,
                    'orig_gain': round(m.active_original_gain, 3),
                    'orig_pending_s': round(
                        m.original.pending() / float(mx.OUT_BPS), 2),
                })
            self.clock_late_max_ms = 0
            if ticks:
                rec['present_ms'] = counts.get('present_ticks', 0) * CHUNK_MS
                rec['orig_rms'] = int(counts.get('orig_rms_sum', 0) / ticks)
                rec['trans_rms'] = int(counts.get('trans_rms_sum', 0) / ticks)
            for key in ('present_ticks', 'orig_rms_sum', 'trans_rms_sum'):
                counts.pop(key, None)
            rec.update(counts)
            rec.update(peaks)
            if self.gemini is not None:
                g = self.gemini
                rec['gem_sent_total'] = g.bytes_in
                rec['gem_recv_total'] = g.bytes_out
                rec['gem_sessions'] = getattr(g, 'sessions', 0)
                rec['gem_errors'] = getattr(g, 'errors', 0)
                rec['gem_connected'] = bool(g.connected)
                rec['gem_queue_s'] = round(g.queued_seconds(), 2)
                rec['gem_dropped_in_s'] = round(g.dropped_in / 32000.0, 1)
                rec['gem_send_ms'] = g.send_max_ms
                rec['gem_stale_s'] = round(g.stale_dropped / 32000.0, 1)
                g.send_max_ms = 0
            rec['silence_skipped_s'] = round(
                m.silence_skipped / float(mx.OUT_BPS), 1)
            rec['pause_trimmed_s'] = round(m.pause_trimmed / float(mx.OUT_BPS), 1)
            # Keep room for everything already waiting in the delay line.
            m.translated.max_backlog = max(
                float(self.cfg['max_backlog']),
                m.original.pending() / float(mx.OUT_BPS) + 6.0)
            rec['position'] = round(m.position(), 2)
            rec['input_pos'] = round(self.input_position(), 2)
            rec['extra_delay'] = self.extra_delay
            rec['restarts'] = self.restarts
            rec['trans_waiting'] = bool(m.translated.waiting)
            rec['trans_late_ms'] = int(m.translated.lateness * 1000)
            rec['late_dropped_ms'] = int(
                m.translated.late_dropped_bytes * 1000 / mx.OUT_BPS)
            if self.gemini is not None:
                rec['sent_pos'] = round(self.gemini.sent_position, 2)
            for name, proc in (('engine', None), ('ffin', self.ff_in),
                               ('mux', self.ff_out)):
                pid = os.getpid() if proc is None else getattr(proc, 'pid', None)
                if proc is not None:
                    rec['%s_alive' % name] = proc.poll() is None
                ticks_now = _cpu_ticks(pid) if pid else None
                if ticks_now is not None:
                    before = cpu_last.get(name)
                    if before is not None:
                        rec['cpu_%s' % name] = int(
                            (ticks_now - before) * 100.0 / tick / span)
                    cpu_last[name] = ticks_now
            self.metrics.write(rec)
        self.metrics.close()

    def position(self):
        """Seconds into the item, measured by audio actually handed to the muxer."""
        return self.start_at + self.emitted_bytes / float(mx.OUT_BPS)

    # ------------------------------------------------------------ lifecycle

    def run(self):
        self._t(self._metrics_loop, 'metrics')
        self._start_tap()
        self._t(self._http_server, 'http')
        self._t(self._control_server, 'ctl')
        self._resolve_source()
        if not self.cfg.get('passthrough'):
            if self.cfg['translate'] and self.cfg['api_key']:
                self._start_gemini()
            elif self.cfg['translate']:
                self.log('[gemini] no api_key configured, translation disabled')
                self.stats['gemini_state'] = 'no api key'
        try:
            self._supervise()
        except KeyboardInterrupt:
            pass
        self.stop()

    def _start_gemini(self):
        def on_state(state):
            self.stats['gemini_state'] = state

        def on_audio(pcm, sent_position):
            self._dump('trans24', pcm, time.time())
            lead = float(self.cfg.get('translation_lead') or 0)
            self.mixer.feed_translated(pcm, max(0.0, sent_position - lead))
        self.gemini = GeminiTranslator(
            api_key=self.cfg['api_key'],
            on_audio=on_audio,
            model=self.cfg['model'],
            language=self.cfg['language'],
            on_state=on_state,
            log=self.log,
            positional=True)
        self.gemini.on_sent = lambda pcm, t: self._dump('src16', pcm, t)
        self.gemini.play_position = self.mixer.position
        self.gemini.start()

    def _supervise(self):
        """Run pipeline generations; the decoder's connection survives them."""
        while not self.stopping.is_set():
            if self.cfg.get('passthrough'):
                reason = self._run_passthrough_once()
            else:
                reason = self._run_translate_once()
            if self.stopping.is_set() or reason == 'stopped':
                return
            if reason == 'no audio':
                # A few lists point at a video-only rendition. Translation is
                # impossible, but the picture must not loop through restarts.
                self.log('[main] source has no audio; continuing as passthrough')
                self.stats['gemini_state'] = 'no source audio'
                if self.gemini:
                    self.gemini.stop()
                    self.gemini = None
                self.cfg['passthrough'] = True
                continue
            self.restarts += 1
            if self.restarts > MAX_RESTARTS:
                self.log('[main] giving up after %d restarts' % self.restarts)
                return
            wait = min(10.0, 1.0 * self.restarts)
            self.log('[main] %s; restarting the source in %.0fs (restart %d)'
                     % (reason, wait, self.restarts))
            self.meter.add('source_restart')
            self.stopping.wait(wait)

    def _new_generation(self):
        """Forget buffered media from a failed source; keep the clocks going."""
        self.mixer.original.reset(keep_position=True)
        self.mixer.translated.clear()
        self.video.clear()
        self.input_origin = self.mixer.position()
        self.a16_bytes = 0
        if self.gemini:
            self.gemini.clear_queue()

    def _watch(self, pipe, procs):
        """Wait for a reason to end this generation."""
        up = steady()
        while not self.stopping.is_set():
            for name, proc in procs:
                if proc.poll() is not None:
                    text = ' '.join(pipe.errors[-3:])
                    if name == 'ingest' and 'matches no streams' in text:
                        return 'no audio'
                    return '%s exited rc=%s' % (name, proc.returncode)
            idle = steady() - pipe.last_input
            if idle > INGEST_STALL_S and steady() - up > INGEST_STALL_S:
                return 'no input for %.0fs' % idle
            self.stopping.wait(0.5)
        return 'stopped'

    def _end(self, pipe):
        pipe.stop.set()
        for proc in pipe.procs:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        deadline = time.time() + 2.0
        for proc in pipe.procs:
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        for fd in pipe.fds:
            try:
                os.close(fd)
            except Exception:
                pass
        for t in pipe.threads:
            t.join(2.0)
        for proc in pipe.procs:
            try:
                proc.wait()
            except Exception:
                pass
            for handle in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if handle is not None:
                        handle.close()
                except Exception:
                    pass

    def _run_translate_once(self):
        pipe = _Pipeline()
        self._new_generation()
        ingest, r48, r16 = self._spawn_ingest(pipe)
        mux, wpcm = self._spawn_mux(pipe)
        self._t(lambda: self._read_video(pipe, ingest.stdout), 'video', pipe)
        self._t(lambda: self._read_audio48(pipe, r48), 'audio48', pipe)
        if r16 is not None:
            self._t(lambda: self._read_audio16(pipe, r16), 'audio16', pipe)
        self._t(lambda: self._drain_stderr(pipe, ingest, 'ff-in'), 'ff-in-err', pipe)
        self._t(lambda: self._drain_stderr(pipe, mux, 'ff-out'), 'ff-out-err', pipe)
        video_fd = mux.stdin.fileno()
        self._t(lambda: self._pump_video(pipe, video_fd), 'pump-video', pipe)
        self._t(lambda: self._pump_audio(pipe, wpcm), 'pump-audio', pipe)
        self._t(lambda: self._serve_output(pipe, mux.stdout), 'out', pipe)
        reason = self._watch(pipe, (('ingest', ingest), ('mux', mux)))
        self._end(pipe)
        return reason

    def _run_passthrough_once(self):
        pipe = _Pipeline()
        proc = self._spawn_passthrough(pipe)

        def output():
            # Input and output are the same process here.
            while not pipe.stop.is_set():
                data = proc.stdout.read(16384)
                if not data:
                    break
                pipe.last_input = steady()
                if not self.video_started:
                    self.video_started = self.audio_started = True
                    self.log('[passthrough] streaming')
                self._send_to_client(data)
        self._t(lambda: self._drain_stderr(pipe, proc, 'ff'), 'ff-err', pipe)
        self._t(output, 'out', pipe)
        reason = self._watch(pipe, (('passthrough', proc),))
        self._end(pipe)
        return reason

    def _send_to_client(self, data):
        self.stats['out_bytes'] += len(data)
        self.meter.add('mux_out', len(data))
        with self.client_lock:
            c = self.client
        if c is None:
            self.meter.add('discard', len(data))
            return
        try:
            c.sendall(data)
            self.meter.add('client_out', len(data))
            self._tap(data)
        except Exception as exc:
            self.meter.add('client_drop')
            self.log('[out] client dropped: %s' % exc)
            with self.client_lock:
                if self.client is c:
                    self.client = None
            try:
                c.close()
            except Exception:
                pass

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.log('[main] stopping')
        if self.gemini:
            self.gemini.stop()
        for p in (self.ff_in, self.ff_out):
            if p and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        time.sleep(0.3)
        for p in (self.ff_in, self.ff_out):
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        with self.client_lock:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None


def main(argv):
    cfg = {}
    if len(argv) > 1 and argv[1] == '-':
        cfg = json.loads(sys.stdin.read())
    elif len(argv) > 1:
        with open(argv[1]) as fh:
            cfg = json.load(fh)
    else:
        sys.stderr.write('usage: engine.py <config.json>|-\n')
        return 2
    Engine(cfg).run()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
