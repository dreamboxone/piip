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
"""Delay lines, resampling and two-gain mixing for the translation pipeline.

All PCM here is signed 16-bit little-endian.
Working format for the output is 48 kHz stereo -> 192000 bytes/second.
"""

import array
import collections
import math
import sys
import threading

OUT_RATE = 48000
OUT_CH = 2
OUT_WIDTH = 2
OUT_BPS = OUT_RATE * OUT_CH * OUT_WIDTH          # 192000 bytes / second

TR_RATE = 24000                                   # Gemini output rate
TR_CH = 1

# ---------------------------------------------------------------- backends

_backend = None
try:
    import audioop                                # stdlib, removed in 3.13
    _backend = 'audioop'
except ImportError:
    try:
        import numpy as _np
        _backend = 'numpy'
    except ImportError:
        # Python 3.13 and later ship neither, and a receiver image rarely
        # carries numpy. These four operations are small enough to do here:
        # about 25 ms of CPU per second of 48 kHz stereo audio.
        _backend = 'python'


class AudioUnavailable(RuntimeError):
    pass


def _require_backend():
    """Kept for callers: there is always a backend now."""
    if _backend is None:                             # pragma: no cover
        raise AudioUnavailable('no audio backend')


def _samples(pcm):
    out = array.array('h')
    out.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if sys.byteorder != 'little':
        out.byteswap()
    return out


def _pcm(samples):
    if sys.byteorder != 'little':
        samples = array.array('h', samples)
        samples.byteswap()
    return samples.tobytes()


def _clamped(values):
    return array.array('h', [-32768 if v < -32768 else
                             (32767 if v > 32767 else v) for v in values])


def scale(pcm, gain):
    """Multiply 16-bit PCM by a float gain, with clipping."""
    if gain == 1.0:
        return pcm
    if gain == 0.0:
        return b'\0' * len(pcm)
    if _backend == 'audioop':
        return audioop.mul(pcm, 2, gain)
    if _backend == 'python':
        return _pcm(_clamped(int(x * gain) for x in _samples(pcm)))
    a = _np.frombuffer(pcm, dtype='<i2').astype(_np.float32) * gain
    return _np.clip(a, -32768, 32767).astype('<i2').tobytes()


def rms(pcm):
    """Root-mean-square level of 16-bit PCM, 0..32767."""
    if not pcm:
        return 0
    if _backend == 'audioop':
        return audioop.rms(pcm, 2)
    if _backend == 'python':
        values = _samples(pcm)
        if not values:
            return 0
        return int(math.sqrt(sum(v * v for v in values) / float(len(values))))
    a = _np.frombuffer(pcm, dtype='<i2').astype(_np.float32)
    return int(_np.sqrt(_np.mean(a * a))) if len(a) else 0


def add(a, b):
    """Sum two equal-length 16-bit PCM buffers, with clipping."""
    if len(a) != len(b):
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
    if _backend == 'audioop':
        return audioop.add(a, b, 2)
    if _backend == 'python':
        return _pcm(_clamped(map(int.__add__, _samples(a), _samples(b))))
    x = _np.frombuffer(a, dtype='<i2').astype(_np.int32)
    y = _np.frombuffer(b, dtype='<i2').astype(_np.int32)
    return _np.clip(x + y, -32768, 32767).astype('<i2').tobytes()


class Resampler(object):
    """Stateful mono 24 kHz -> stereo 48 kHz converter."""

    def __init__(self, src_rate=TR_RATE, dst_rate=OUT_RATE):
        self.src, self.dst = src_rate, dst_rate
        self._state = None
        self._offset = 0.0

    def __call__(self, pcm_mono):
        if not pcm_mono:
            return b''
        if _backend == 'audioop':
            out, self._state = audioop.ratecv(pcm_mono, 2, 1, self.src,
                                              self.dst, self._state)
            return audioop.tostereo(out, 2, 1.0, 1.0)
        if _backend == 'python':
            return self._python(pcm_mono)
        a = _np.frombuffer(pcm_mono, dtype='<i2')
        ratio = float(self.dst) / self.src
        n_out = int(len(a) * ratio)
        if n_out <= 0:
            return b''
        idx = _np.linspace(0, len(a) - 1, n_out)
        mono = _np.interp(idx, _np.arange(len(a)), a).astype('<i2')
        return _np.repeat(mono, 2).tobytes()

    def _python(self, pcm_mono):
        """Linear resample to stereo, carrying the last sample across calls.

        The carried sample is what keeps a click out of every chunk
        boundary; audioop.ratecv does the same with its state tuple.
        """
        values = _samples(pcm_mono)
        if not values:
            return b''
        previous = self._state if isinstance(self._state, int) else values[0]
        step = float(self.src) / self.dst
        out = array.array('h')
        position = self._offset
        count = len(values)
        while position < count:
            index = int(position)
            fraction = position - index
            first = previous if index == 0 else values[index - 1]
            second = values[index]
            sample = int(first + (second - first) * fraction)
            out.append(sample)
            out.append(sample)                       # the same in both ears
            position += step
        self._offset = position - count
        self._state = values[-1]
        return _pcm(out)


# ------------------------------------------------------------- delay lines

class ByteDelay(object):
    """Fixed-rate stream delayed by an exact number of bytes.

    Reads advance an offset instead of deleting from the front: with tens of
    seconds buffered, `del buf[:n]` every 20 ms moved megabytes per tick and
    kept a whole CPU core busy, which made the audio clock late.
    """

    COMPACT = 1 << 20

    def __init__(self, bytes_per_second, seconds):
        self.bps = bytes_per_second
        self._buf = bytearray()
        self._off = 0
        self._lock = threading.Lock()
        self.read_bytes = 0
        self.set_delay(seconds)

    def set_delay(self, seconds):
        self.seconds = max(0.0, float(seconds))
        n = int(self.bps * self.seconds)
        self.target = n - (n % (OUT_CH * OUT_WIDTH))

    def write(self, data):
        with self._lock:
            self._buf += data

    def read(self, n):
        """Return n bytes once the buffer has filled past the delay target."""
        with self._lock:
            if len(self._buf) - self._off < self.target + n:
                return None
            out = bytes(self._buf[self._off:self._off + n])
            self._off += n
            self.read_bytes += n
            if self._off >= self.COMPACT:
                del self._buf[:self._off]
                self._off = 0
            return out

    def pending(self):
        with self._lock:
            return len(self._buf) - self._off

    def position(self):
        """Seconds of the stream handed out so far."""
        return self.read_bytes / float(self.bps)

    def reset(self, keep_position=False):
        with self._lock:
            self._buf = bytearray()
            self._off = 0
            if not keep_position:
                self.read_bytes = 0


class PacketDelay(object):
    """Delays opaque packets (MPEG-TS) by wall-clock arrival time."""

    def __init__(self, seconds, clock):
        self.seconds = float(seconds)
        self.clock = clock
        self._q = collections.deque()
        self._lock = threading.Lock()
        self.bytes_held = 0

    def set_delay(self, seconds):
        self.seconds = max(0.0, float(seconds))

    def write(self, data):
        with self._lock:
            self._q.append((self.clock(), data))
            self.bytes_held += len(data)

    def clear(self):
        with self._lock:
            self._q.clear()
            self.bytes_held = 0

    def drain(self):
        """Yield every packet whose delay has elapsed."""
        now = self.clock()
        out = []
        with self._lock:
            while self._q and now - self._q[0][0] >= self.seconds:
                t, data = self._q.popleft()
                self.bytes_held -= len(data)
                out.append(data)
        return out


SILENCE_RMS = 80        # Gemini pads turns with digital near-silence
AUDIBLE_RMS = 150       # a 20 ms frame with speech in it
DUCK_HOLD_TICKS = 30    # keep the programme lowered 600 ms past a word
FRAME = OUT_BPS // 50   # 20 ms of 48 kHz stereo
MAX_PAUSE_FRAMES = 10   # pauses inside translated speech kept up to 200 ms


class TranslationBuffer(object):
    """Translated speech, each piece scheduled against the programme.

    Every write carries `not_before`: the programme position (seconds of
    original audio) that had already been sent to Gemini when the speech
    came back, less a small lead. Speech is held until the viewer's playback
    reaches that position, so it follows the picture it belongs to however
    much the stream is buffered - not the moment it arrived over the
    network. Pieces that fall more than `max_late` behind are dropped
    unheard, and a due backlog is played up to 8 percent faster with
    pitch-preserving splices; the programme's own clocks stay at 1.000x.
    Writes without a position (tests, old callers) are due at once.
    """

    def __init__(self, max_backlog=6.0, max_late=8.0):
        self._segs = collections.deque()     # [not_before, bytearray, offset]
        self._queued = 0
        self._lock = threading.Lock()
        self.max_backlog = max_backlog
        self.max_late = max_late
        self.dropped_bytes = 0
        self.late_dropped_bytes = 0
        self.compressed_bytes = 0
        self.underruns = 0
        self.speed = 1.0
        self.waiting = False
        self.lateness = 0.0
        self._was_present = False

    def write(self, pcm48_stereo, not_before=None):
        if not pcm48_stereo:
            return
        with self._lock:
            last = self._segs[-1] if self._segs else None
            if last is not None and (
                    not_before is None or last[0] is None or
                    not_before <= last[0] + (len(last[1]) - last[2]) /
                    float(OUT_BPS) + 0.3):
                last[1] += pcm48_stereo            # the same utterance goes on
            else:
                self._segs.append([not_before, bytearray(pcm48_stereo), 0])
            self._queued += len(pcm48_stereo)
            cap = int(self.max_backlog * OUT_BPS)
            while self._queued > cap and self._segs:
                head = self._segs[0]
                excess = self._queued - cap
                excess -= excess % (OUT_CH * OUT_WIDTH)
                left = len(head[1]) - head[2]
                if left <= excess or excess <= 0:
                    self._segs.popleft()
                    self._queued -= left
                    self.dropped_bytes += left
                    if excess <= 0:
                        break
                else:
                    head[2] += excess
                    self._queued -= excess
                    self.dropped_bytes += excess

    def _compress(self, pcm, size):
        """Pitch-preserving overlap/splice compression for one PCM frame.

        Dropping a tiny, waveform-aligned region preserves the pitch of the
        retained speech.  A sample-rate conversion would produce the familiar
        fast/high voice and is deliberately not used here.
        """
        if len(pcm) <= size:
            return pcm + b'\0' * (size - len(pcm))
        samples = array.array('h')
        loader = getattr(samples, 'frombytes', None) or samples.fromstring
        loader(pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        in_frames = len(samples) // OUT_CH
        out_frames = size // (OUT_WIDTH * OUT_CH)
        remove = max(1, in_frames - out_frames)
        overlap = min(96, out_frames // 4)
        left = max(overlap, (out_frames - overlap) // 2)
        right = left + remove
        result = array.array('h', samples[:left * OUT_CH])
        for frame in range(overlap):
            weight = frame / float(max(1, overlap - 1))
            for channel in range(OUT_CH):
                a = samples[(left + frame) * OUT_CH + channel]
                b = samples[(right + frame) * OUT_CH + channel]
                result.append(int(a * (1.0 - weight) + b * weight))
        result.extend(samples[(right + overlap) * OUT_CH:])
        result = result[:out_frames * OUT_CH]
        if sys.byteorder != 'little':
            result.byteswap()
        dumper = getattr(result, 'tobytes', None) or result.tostring
        out = dumper()
        return out[:size] + b'\0' * max(0, size - len(out))

    def _due(self, position):
        """Bytes queued whose time has come."""
        if position is None:
            return self._queued
        due = 0
        for nb, buf, off in self._segs:
            if nb is not None and nb > position:
                break
            due += len(buf) - off
        return due

    def read_with_presence(self, n, position=None):
        """Return fixed-size audio plus whether translated PCM was played."""
        with self._lock:
            if position is not None:
                while self._segs:
                    nb, buf, off = self._segs[0]
                    # Measured from the part not yet played: a long sentence
                    # that is playing is on time, however long ago it began.
                    if nb is None or position - (nb + off / float(OUT_BPS)) <= self.max_late:
                        break
                    # Too late to belong to what is on screen any more.
                    self._segs.popleft()
                    self._queued -= len(buf) - off
                    self.late_dropped_bytes += len(buf) - off
            head = self._segs[0] if self._segs else None
            if head is None or (position is not None and head[0] is not None
                                and head[0] > position and head[2] == 0):
                self.waiting = head is not None
                if self._was_present and head is None:
                    self.underruns += 1
                self._was_present = False
                self.speed = max(1.0, self.speed - 0.002)
                return b'\0' * n, False
            self.waiting = False
            self.lateness = (max(0.0, position - head[0] - head[2] / float(OUT_BPS))
                             if position is not None and head[0] is not None
                             else 0.0)
            due = self._due(position) / float(OUT_BPS)
            excess = max(due - 0.5, self.lateness - 2.0, 0.0)
            target = 1.0 + min(0.08, excess * 0.04)
            step = 0.0015
            self.speed += max(-step, min(step, target - self.speed))
            wanted = int(n * self.speed)
            wanted -= wanted % (OUT_CH * OUT_WIDTH)
            wanted = max(n, wanted)
            parts, take = [], 0
            while self._segs and take < wanted:
                nb, buf, off = self._segs[0]
                if take and position is not None and nb is not None and nb > position:
                    break
                chunk = min(wanted - take, len(buf) - off)
                parts.append(bytes(buf[off:off + chunk]))
                take += chunk
                self._segs[0][2] += chunk
                if self._segs[0][2] >= len(buf):
                    self._segs.popleft()
            self._queued -= take
            out = b''.join(parts)
            take -= take % (OUT_CH * OUT_WIDTH)
            out = out[:take]
            self._was_present = bool(take)
        if take > n:
            self.compressed_bytes += take - n
            out = self._compress(out, n)
        elif take < n:
            out += b'\0' * (n - take)
        return out, bool(take)

    def read(self, n, position=None):
        return self.read_with_presence(n, position)[0]

    def backlog_seconds(self):
        with self._lock:
            return self._queued / float(OUT_BPS)

    def clear(self):
        with self._lock:
            self._segs.clear()
            self._queued = 0


class Mixer(object):
    """Combines delayed original audio with translated audio."""

    def __init__(self, delay_seconds, max_backlog=6.0):
        _require_backend()
        self.original = ByteDelay(OUT_BPS, delay_seconds)
        self.translated = TranslationBuffer(max_backlog)
        self.resampler = Resampler()
        self.gain_original = 0.25
        self.gain_translated = 1.0
        self.active_original_gain = 1.0
        self.fallback = True
        # What the last pull contained, for the engine's per-second metrics.
        self.last_present = False
        self.last_orig_rms = 0
        self.last_trans_rms = 0
        self.silence_skipped = 0
        self.pause_trimmed = 0
        self._pause_frames = 0
        self._trim_rest = b''
        self._hold = 0

    def set_delay(self, seconds):
        self.original.set_delay(seconds)

    def position(self):
        """Programme seconds already handed to the muxer."""
        return self.original.position()

    def feed_original(self, pcm48_stereo):
        self.original.write(pcm48_stereo)

    def _trim_pauses(self, pcm):
        """Shorten pauses in translated speech to MAX_PAUSE_FRAMES.

        Persian renderings run longer than the source and Gemini leaves
        long gaps between phrases; keeping every gap makes the translation
        fall behind the picture until whole sentences are dropped. Words
        are never touched, only silence beyond a natural pause.
        """
        pcm = self._trim_rest + pcm
        whole = len(pcm) - len(pcm) % FRAME
        self._trim_rest = pcm[whole:]
        kept = []
        for i in range(0, whole, FRAME):
            frame = pcm[i:i + FRAME]
            if rms(frame) < SILENCE_RMS:
                self._pause_frames += 1
                if self._pause_frames > MAX_PAUSE_FRAMES:
                    self.pause_trimmed += FRAME
                    continue
            else:
                self._pause_frames = 0
            kept.append(frame)
        return b''.join(kept)

    def feed_translated(self, pcm24_mono, not_before=None):
        pcm = self._trim_pauses(self.resampler(pcm24_mono))
        if not pcm:
            return
        if (rms(pcm) < SILENCE_RMS and
                self.translated.backlog_seconds() <= 0.0):
            # Silence between turns carries nothing: queued, it would lower
            # the programme and delay the next real sentence.
            self.silence_skipped += len(pcm)
            return
        self.translated.write(pcm, not_before)

    def pull(self, n):
        """Produce n bytes of mixed audio, or None while the delay fills."""
        position = self.original.position()
        orig = self.original.read(n)
        if orig is None:
            return None
        trans, queued = self.translated.read_with_presence(n, position)
        level = rms(trans) if queued else 0
        # Only audible translated speech lowers the programme; padding and
        # pauses leave it at full level after a short hold.
        if level >= AUDIBLE_RMS:
            self._hold = DUCK_HOLD_TICKS
        elif self._hold:
            self._hold -= 1
        present = self._hold > 0
        # If Gemini pauses, preserve the fixed A/V timeline and fade the
        # original programme up instead of restarting or silencing playback.
        target = self.gain_original if present else 1.0
        step = 0.08
        self.active_original_gain += max(
            -step, min(step, target - self.active_original_gain))
        self.fallback = not present
        translated = scale(trans, self.gain_translated)
        self.last_present = level >= AUDIBLE_RMS
        self.last_orig_rms = rms(orig)
        self.last_trans_rms = rms(translated) if queued else 0
        return add(scale(orig, self.active_original_gain), translated)
