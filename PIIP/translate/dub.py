# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
#
"""Translated IPTV playback through the E2Dub audio engine.

E2Dub's AudioEngine is proven on this receiver with a live DVB transport
stream behind an HTTP URL. An IPTV channel is turned into exactly that: the
PIIP engine in passthrough mode serves the channel (HLS or TS) as plain
MPEG-TS on 127.0.0.1, and E2Dub's relay, Gemini helper, mixer and HTTP relay
run on top of it unchanged:

    IPTV URL -> PIIP passthrough (TS over HTTP)
             -> e2dub_relay (fixed RAM delay + live UDP tap)
                  |-> capture ffmpeg -> e2dub_audio_helper (Gemini) -> dub PCM
             -> ffmpeg mix (track 0 dub+original, track 1 original)
             -> e2dub_http -> http://127.0.0.1:19876/e2dub.ts -> Enigma2
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
E2DUB = os.path.join(HERE, 'e2dub')
if E2DUB not in sys.path:
    sys.path.insert(0, E2DUB)

from e2dub_audio_engine import AudioEngine                    # noqa: E402

from .control import EngineHandle                             # noqa: E402

LOG = '/tmp/piip_dub.log'
KEY_FILE = '/tmp/piip_dub_apikey'
HELPER_STATE = '/tmp/e2dub-audio-helper-state'
RELAY_STATE = '/tmp/e2dub-audio-relay-state'
HTTP_STATE = '/tmp/e2dub-audio-http-state'
HTTP_PORT = 19876
DUB_UDP_PORT = 19877
LIVE_TS_UDP_PORT = 19878
LOCAL_URL = 'http://127.0.0.1:%d/e2dub.ts' % HTTP_PORT
LOCAL_DVB_REFERENCE = '1:0:1:1:1:1:0:0:0:0:'
TRANSLATED_PID = 0x110
ORIGINAL_PID = 0x111
FIXED_DELAY = 4.0
# The decoder's own buffer, ahead of the fixed RAM delay. At 1.5 s a brief
# stall on the receiver reached the end of the buffer, and DreamOS' HTTP/TS
# source answers that with EOF: the picture came back only after the player
# reattached, which is the few seconds of black seen every several minutes.
# It rides on top of a stream that is already delayed, so it costs startup
# time and nothing else -- A/V sync is fixed upstream of here.
BUFFER_MS = 5000
NUL = bytes(bytearray([0]))
# Workers of an earlier pipeline are recognised by these command-line parts.
LEFTOVER_MARKERS = ('e2dub_relay.py', 'e2dub_http.py', 'e2dub_audio_helper.py',
                    '127.0.0.1:%d' % DUB_UDP_PORT,
                    '127.0.0.1:%d' % LIVE_TS_UDP_PORT)


def _python():
    for candidate in ('/usr/bin/python', '/usr/bin/python2', '/usr/bin/python3'):
        if os.path.exists(candidate):
            return candidate
    return sys.executable or 'python'


def _setsid():
    os.setsid()


def _nice_setsid():
    os.setsid()
    try:
        os.nice(5)
    except Exception:
        pass


def read_state(path=HELPER_STATE):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {}


def kill_leftovers():
    """End workers of an earlier pipeline that were never stopped.

    They run in their own sessions, so a crashed Enigma2 or an interrupted
    test leaves them holding ports 19876-19878; the next capture then fails
    to bind and Gemini never receives any audio.
    """
    mine = os.getpid()
    for name in os.listdir('/proc'):
        if not name.isdigit() or int(name) == mine:
            continue
        try:
            with open('/proc/%s/cmdline' % name, 'rb') as fh:
                cmd = fh.read().replace(NUL, b' ').decode('latin-1')
        except Exception:
            continue
        if any(marker in cmd for marker in LEFTOVER_MARKERS):
            try:
                os.kill(int(name), 9)
            except Exception:
                pass


class DubPipeline(object):
    # The player drives this like the engine it replaces.
    url = LOCAL_URL

    def __init__(self, source_cfg, api_key, language='fa', original_volume=30,
                 ffmpeg='ffmpeg'):
        self.source_cfg = dict(source_cfg)
        self.api_key = api_key
        self.language = language if language in ('fa', 'ar') else 'fa'
        self.original_volume = int(original_volume)
        self.ffmpeg = ffmpeg
        self.source = None
        self.engine = None
        self.log_handle = None
        self.started_at = 0.0

    # ------------------------------------------------------------- runtime

    def _log(self, text):
        try:
            self.log_handle.write('%s [piip-dub] %s\n'
                                  % (time.strftime('%H:%M:%S'), text))
            self.log_handle.flush()
        except Exception:
            pass

    def _spawn(self, args, stdin=None, stdout=None, latency_sensitive=False):
        return subprocess.Popen(
            args, stdin=stdin, stdout=stdout, stderr=self.log_handle,
            close_fds=True,
            preexec_fn=_setsid if latency_sensitive else _nice_setsid)

    def _write_key(self):
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as fh:
            fh.write(self.api_key.strip() + '\n')

    # ----------------------------------------------------------- lifecycle

    def start(self):
        self.stop()
        kill_leftovers()
        time.sleep(0.3)
        self.log_handle = open(LOG, 'a')
        for path in (HELPER_STATE, RELAY_STATE, HTTP_STATE):
            try:
                os.remove(path)
            except OSError:
                pass
        self._write_key()
        cfg = dict(self.source_cfg)
        cfg.update({'translate': False, 'passthrough': True})
        self.source = EngineHandle(cfg)
        if not self.source.start():
            self._log('source engine did not start')
            return False
        context = {
            'ffmpeg_path': self.ffmpeg,
            'supports_max_muxing_queue': True,
            'has_mix_limiter': True,
            'source_url': self.source.url,
            'audio_stream': '0:a:0',
            'capture_backend': {'mode': 'dreamos-raw-pcm'},
            'target_language': self.language,
            'original_volume': self.original_volume,
            'fixed_delay': FIXED_DELAY,
            'audio_sync_correction': 0.0,
            'worker_python': _python(),
            'key_file': KEY_FILE,
            'audio_helper': os.path.join(E2DUB, 'e2dub_audio_helper.py'),
            'relay': os.path.join(E2DUB, 'e2dub_relay.py'),
            'http_relay': os.path.join(E2DUB, 'e2dub_http.py'),
            'relay_state_file': RELAY_STATE,
            'http_state_file': HTTP_STATE,
            'dub_udp_port': DUB_UDP_PORT,
            'live_ts_udp_port': LIVE_TS_UDP_PORT,
            'http_port': HTTP_PORT,
            'local_service_id': 1,
            'local_tsid': 1,
            'local_onid': 1,
            'translated_audio_pid': TRANSLATED_PID,
            'original_audio_pid': ORIGINAL_PID,
            'is_oe_alliance': False,
        }
        self.engine = AudioEngine({'spawn': self._spawn, 'log': self._log})
        self.engine.start(context)
        self.started_at = time.time()
        self._log('dub pipeline started for %s' % self.source.url)
        return True

    def processes(self):
        return [p for p in (self.engine.values() if self.engine else ()) if p]

    def alive(self):
        procs = self.processes()
        return (bool(procs) and all(p.poll() is None for p in procs) and
                self.source is not None and self.source.alive())

    def helper_state(self):
        return read_state(HELPER_STATE)

    def status(self):
        helper = self.helper_state()
        state = helper.get('state', 'starting')
        return {
            'ok': True,
            'flowing': bool(read_state(HTTP_STATE)) or
                       time.time() - self.started_at > 8,
            'gemini': {'audio': 'connected', 'streaming': 'connected'}.get(
                state, state),
            'dub_state': state,
            'backlog': 0.0,
            'position': 0.0,
            'helper': helper,
        }

    def set_gain(self, original=None, translated=None):
        return None

    def set_delay(self, seconds):
        return None

    def seek(self, seconds):
        return False

    def stop(self):
        for proc in self.processes():
            try:
                if proc.poll() is None:
                    os.killpg(proc.pid, 15)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        deadline = time.time() + 2.0
        for proc in self.processes():
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, 9)
                except Exception:
                    pass
        if self.engine is not None:
            self.engine.clear()
        self.engine = None
        if self.source is not None:
            self.source.stop()
            self.source = None
        try:
            os.remove(KEY_FILE)
        except OSError:
            pass
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except Exception:
                pass
            self.log_handle = None
