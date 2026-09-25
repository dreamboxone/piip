#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function

import base64
import array
import math
import collections
import errno
import hashlib
import json
import os
import re
import signal
import socket
import ssl
import struct
import sys
import threading
import time

try:
    import Queue as queue
except ImportError:
    import queue

HOST = "generativelanguage.googleapis.com"
PORT = 443
MODEL = "gemini-3.5-live-translate-preview"
DEFAULT_KEY_FILE = "/root/apikey.txt"
# PIIP resolves the key itself -- from either home, /etc/enigma2 or the
# settings -- and hands it over in its own 0600 file. Refusing that path sent
# the helper to /root/apikey.txt, which on an OE-Alliance image does not
# exist because /root does not: it exited at once, no PCM reached the mixer,
# and the viewer saw a black picture.
ALLOWED_KEY_FILES = (DEFAULT_KEY_FILE, "/home/root/apikey.txt",
                     "/tmp/piip_dub_apikey")
STATE_FILE = "/tmp/e2dub-audio-helper-state"
INPUT_STATE_FILE = "/tmp/e2dub-audio-input-state"
INPUT_CHUNK_BYTES = 3200       # 100 ms, s16le mono, 16 kHz
OUTPUT_FRAME_BYTES = 960       # 20 ms, s16le mono, 24 kHz
INPUT_SIGNAL_PEAK_THRESHOLD = 32
INPUT_SIGNAL_MIN_SAMPLES = 8
INPUT_SIGNAL_CONFIRM_FRAMES = 3
# Raw Gemini PCM is consumed by the adaptive 20 ms playout clock. This cap
# limits burst headroom independently of the source A/V startup delay.
MAX_OUTPUT_BYTES = 288000      # 6 seconds burst headroom, not a startup delay
AUDIO_JITTER_SECONDS = 0.24
AUDIO_INPUT_MAX_AGE_SECONDS = 0.8
# Live Translate spends rendering time on silence exactly as it does on
# speech, and it has none to spare, so the pauses of the programme are sent
# as the model's catch-up time rather than as audio.
INPUT_SILENCE_GATE = True
INPUT_PREROLL_FRAMES = 3       # 300 ms kept before speech, for weak onsets
INPUT_HANGOVER_SECONDS = 0.8   # keep sending after speech ends, for tails
# Pause the input only when translated PCM is accumulating beyond the
# scheduled A/V reserve. A blind pause every minute discarded live speech
# even when the output queue was healthy.
MODEL_QUIET_SECONDS = 3.0      # returned silence that counts as "nothing left"
FEED_WINDOW_SECONDS = 60.0     # minimum interval between backlog probes
FEED_PRESSURE_SECONDS = 1.5    # queued PCM beyond the A/V sync reserve
DRAIN_MAX_SECONDS = 20.0       # never starve the translation on a silent model
DRIFT_MIN_SESSION_SECONDS = 45.0


def should_probe_backlog(now, fed_since, playout):
    """Avoid dropping live speech while translated PCM fits its sync reserve."""
    if now - fed_since <= FEED_WINDOW_SECONDS or not playout:
        return False
    excess_ms = (playout.get('queued_ms', 0) -
                 playout.get('sync_reserve_ms', 0))
    return excess_ms > FEED_PRESSURE_SECONDS * 1000
DUB_UDP_HOST = "127.0.0.1"
DUB_UDP_PORT = 19877
MAX_WS_MESSAGE_BYTES = 8 * 1024 * 1024
SETUP_TIMEOUT_SECONDS = 15
TLS_HANDSHAKE_TIMEOUT_SECONDS = 15
HTTP_UPGRADE_TIMEOUT_SECONDS = 10
WEBSOCKET_READ_TIMEOUT_SECONDS = 2
# Short drain budget for a rejected upgrade's error body; it must never
# delay the reconnect backoff.
ERROR_BODY_TIMEOUT_SECONDS = 2
HEALTHY_RECONNECT_DELAY_SECONDS = 0.25
FLOW_LOG_INTERVAL_SECONDS = 30
# Diagnostics tap: a file holding a directory path turns it on (see dump_pcm).
DUMP_MARKER = "/tmp/piip_dub_dump"
DUMP_DIR = [None]
DUMP_FILES = {}
DUMP_LOCK = threading.Lock()
MATROSKA_PCM_MODE = "--matroska-pcm" in sys.argv[1:]
CONNECTION_PROBE_MODE = "--probe" in sys.argv[1:]


def steady_time():
    """Cross-process monotonic clock available on Python 2 and Python 3."""
    callback = getattr(time, "monotonic", None)
    if callback is not None:
        return float(callback())
    return float(os.times()[4])


def command_line_language(arguments):
    try:
        index = arguments.index("--language")
        value = str(arguments[index + 1]).lower()
    except (ValueError, IndexError, TypeError):
        value = "fa"
    return value if value in ("fa", "ar") else "fa"



def command_line_float(arguments, name, default, minimum, maximum):
    try:
        index = arguments.index(name)
        value = float(arguments[index + 1])
    except (ValueError, IndexError, TypeError):
        value = float(default)
    return max(float(minimum), min(float(maximum), value))

def command_line_key_file(arguments):
    try:
        index = arguments.index("--key-file")
        value = str(arguments[index + 1])
    except (ValueError, IndexError, TypeError):
        value = DEFAULT_KEY_FILE
    return value if value in ALLOWED_KEY_FILES else DEFAULT_KEY_FILE


TARGET_LANGUAGE = command_line_language(sys.argv[1:])
KEY_FILE = command_line_key_file(sys.argv[1:])
PLAYBACK_DELAY_SECONDS = command_line_float(
    sys.argv[1:], "--playback-delay", 4.0, 0.5, 12.0
)
AUDIO_SYNC_CORRECTION_SECONDS = command_line_float(
    sys.argv[1:], "--sync-correction", 0.0, -2.0, 4.0
)
ADAPTIVE_STARTUP = "--adaptive-startup" in sys.argv[1:]
RELAY_STATE_FILE = "/tmp/e2dub-audio-relay-state"
try:
    RELAY_STATE_FILE = sys.argv[sys.argv.index("--relay-state-file") + 1]
except (ValueError, IndexError):
    pass


def create_ipv4_connection(host, port, timeout):
    """Connect over IPv4 so full-device IPv4 TUN clients carry Gemini traffic."""
    last_error = None
    addresses = socket.getaddrinfo(
        host, port, socket.AF_INET, socket.SOCK_STREAM
    )
    for family, socktype, proto, _canonname, sockaddr in addresses:
        raw = socket.socket(family, socktype, proto)
        raw.settimeout(timeout)
        try:
            raw.connect(sockaddr)
            return raw
        except Exception as error:
            last_error = error
            try:
                raw.close()
            except Exception:
                pass
    if last_error is not None:
        raise last_error
    raise socket.error("No IPv4 address found for %s" % host)


def is_read_timeout(error):
    """Recognize socket and Python 2.7/OpenSSL read-timeout variants."""
    if isinstance(error, socket.timeout):
        return True
    error_number = getattr(error, "errno", None)
    if error_number is None:
        try:
            error_number = error.args[0]
        except Exception:
            error_number = None
    transient = (errno.EAGAIN, errno.EWOULDBLOCK)
    if error_number in transient:
        return True
    if isinstance(error, ssl.SSLError):
        message = str(error).lower()
        return (
            "timed out" in message or
            "read operation timed out" in message or
            "did not complete (read)" in message or
            "want read" in message
        )
    return False


def to_bytes(value):
    """Return exact byte content on both Python 2 and Python 3."""
    if isinstance(value, bytearray):
        if sys.version_info[0] >= 3:
            return bytes(value)
        return value.decode("latin-1").encode("latin-1")
    return value


def log(message):
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        sys.stderr.write("%s [audio] %s\n" % (stamp, message))
        sys.stderr.flush()
    except Exception:
        pass


def sanitize_detail(value):
    """Keep state/log diagnostics useful without leaking credentials or payloads."""
    try:
        value = str(value).replace("\r", " ").replace("\n", " ")
    except Exception:
        value = "unknown error"
    if "?key=" in value:
        value = value.split("?key=", 1)[0] + "?key=[redacted]"
    return value[:240]


def set_state(value, profile=None, attempt=None, detail=None,
              error_type=None, **metrics):
    """Publish non-secret structured readiness state atomically."""
    temporary = "%s.%s.%s" % (STATE_FILE, os.getpid(), threading.current_thread().ident)
    try:
        state = {"state": value, "updated": int(time.time())}
        if profile:
            state["profile"] = profile
        if attempt is not None:
            state["attempt"] = int(attempt)
        if detail:
            state["detail"] = sanitize_detail(detail)
        if error_type:
            state["error_type"] = sanitize_detail(error_type)
        for key in ("first_audio_latency_ms", "first_audio_send_latency_ms"):
            if metrics.get(key) is not None:
                state[key] = int(metrics.get(key))
        for key in ("audio_arrived_monotonic", "source_capture_anchor"):
            if metrics.get(key) is not None:
                state[key] = float(metrics[key])
        payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
        with open(temporary, "wb") as handle:
            handle.write(payload.encode("utf-8"))
        os.rename(temporary, STATE_FILE)
    except Exception as error:
        log("Helper state publish failed: %s" % sanitize_detail(error))
        try:
            os.unlink(temporary)
        except Exception:
            pass




def set_input_state(state, total_bytes=0, signal_updated_monotonic=0.0):
    """Publish source-media progress independently from Gemini state."""
    temporary = "%s.%s" % (INPUT_STATE_FILE, os.getpid())
    try:
        payload = json.dumps({
            "state": state,
            "bytes": int(total_bytes),
            "updated": time.time(),
            "updated_monotonic": steady_time(),
            "signal_updated_monotonic": float(signal_updated_monotonic or 0.0),
        }, separators=(",", ":"), sort_keys=True)
        with open(temporary, "wb") as handle:
            handle.write(payload.encode("ascii"))
        replace = getattr(os, "replace", os.rename)
        replace(temporary, INPUT_STATE_FILE)
    except Exception:
        try:
            os.unlink(temporary)
        except Exception:
            pass


    # Do not publish an unfinished transcription chunk. Gemini commonly sends
    # one phrase as growing deltas; the overlay must receive it only after
    # punctuation, the length boundary above, or server turnComplete.


def dump_pcm(name, data, at=None):
    """Optional tap of the live dub path for translate/diagquality.py.

    Writing anything to DUMP_MARKER (a directory path) makes the next
    pipeline record what was sent to Gemini and what came back, with send
    and arrival times, in the same src16/trans24 .pcm+.idx pairs the engine
    diagnostics already produce. Without the marker nothing is opened.
    """
    if DUMP_DIR[0] is None:
        return
    with DUMP_LOCK:
        entry = DUMP_FILES.get(name)
        if entry is None:
            try:
                entry = [open(os.path.join(DUMP_DIR[0], name + '.pcm'), 'ab'),
                         open(os.path.join(DUMP_DIR[0], name + '.idx'), 'a', 1),
                         0]
            except Exception:
                entry = [None, None, 0]
            DUMP_FILES[name] = entry
        if entry[0] is None:
            return
        try:
            entry[0].write(data)
            entry[1].write('%.3f %d %d\n' % (at or time.time(),
                                              entry[2], len(data)))
            entry[2] += len(data)
        except Exception:
            pass


def open_dump_dir():
    try:
        with open(DUMP_MARKER) as handle:
            folder = handle.read().strip()
    except Exception:
        return
    if not folder:
        return
    folder = os.path.join(folder, time.strftime('%H%M%S'))
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        DUMP_DIR[0] = folder
        log("Audio tap recording to %s" % sanitize_detail(folder))
    except Exception as error:
        log("Audio tap unavailable: %s" % sanitize_detail(error))


def pcm_has_meaningful_signal(data):
    """Reject synthetic near-zero PCM while preserving ordinary quiet audio."""
    try:
        samples = bytearray(data)
    except Exception:
        return False
    meaningful = 0
    end = len(samples) - (len(samples) % 2)
    for index in range(0, end, 2):
        sample = samples[index] | (samples[index + 1] << 8)
        if sample >= 32768:
            sample -= 65536
        if abs(sample) >= INPUT_SIGNAL_PEAK_THRESHOLD:
            meaningful += 1
            if meaningful >= INPUT_SIGNAL_MIN_SAMPLES:
                return True
    return False


def pcm_speech_level(data, stride=16):
    """Peak of every stride-th sample: a speech test cheap enough per frame."""
    samples = bytearray(data)
    peak = 0
    end = len(samples) - (len(samples) % 2)
    for index in range(0, end, 2 * stride):
        sample = samples[index] | (samples[index + 1] << 8)
        if sample >= 32768:
            sample -= 65536
        if abs(sample) > peak:
            peak = abs(sample)
    return peak


class AudioBuffer(object):
    def __init__(self, maximum=MAX_OUTPUT_BYTES):
        self._data = bytearray()
        self._lock = threading.Lock()
        self._dropped_bytes = 0
        self._waiting_since = None
        self._playing = False
        self._maximum = int(maximum)

    def append(self, data):
        if not data:
            return
        with self._lock:
            if not self._data:
                self._waiting_since = steady_time()
            self._data.extend(bytearray(data))
            if len(self._data) > self._maximum:
                excess = len(self._data) - self._maximum
                excess += excess % 2
                del self._data[:excess]
                self._dropped_bytes += excess

    def take_with_presence(self, size):
        with self._lock:
            count = min(size, len(self._data))
            result = self._data[:count]
            del self._data[:count]
        if count < size:
            result.extend(bytearray(size - count))
        return to_bytes(result), bool(count)

    def take(self, size):
        result, _present = self.take_with_presence(size)
        return result

    def take_for_playback(self, size, now):
        """Absorb short network gaps without cutting PCM or delaying video."""
        with self._lock:
            if not self._data:
                self._playing = False
                self._waiting_since = None
                return b"\x00" * size, False
            if not self._playing:
                started = self._waiting_since
                waited = max(0.0, now - (started if started is not None else now))
                if (len(self._data) < int(AUDIO_JITTER_SECONDS * 48000) and
                        waited < AUDIO_JITTER_SECONDS):
                    return b"\x00" * size, False
                self._playing = True
            count = min(size, len(self._data))
            count -= count % 2
            result = self._data[:count]
            del self._data[:count]
            if count < size:
                result.extend(bytearray(size - count))
                self._playing = False
            return to_bytes(result), bool(count)

    def clear(self):
        with self._lock:
            del self._data[:]
            self._playing = False
            self._waiting_since = None

    def size(self):
        with self._lock:
            return len(self._data)

    def dropped_size(self):
        with self._lock:
            return self._dropped_bytes


class AdaptivePlayout(object):
    """Bounded speech playout: WSOLA, conservative pause trim, adaptive jitter.

    Queue duration is an overload signal, not a semantic A/V timestamp.
    All DSP runs on received PCM; missing network audio is never trimmed.
    """
    HOP = 480                    # 20 ms at 24 kHz
    SEARCH = 120                 # +/- 5 ms waveform alignment

    def __init__(self, buffer):
        self.buffer = buffer
        self.speed = 1.0
        self.reserve_seconds = 0.0
        self.pressure = 0.0
        self.jitter = AUDIO_JITTER_SECONDS
        self.underruns = 0
        self.trimmed_samples = 0
        self.compressed_samples = 0
        self.peak_queue = 0.0
        self.played_samples = 0
        self._tail = None
        self._expected = 0.0
        self._base = 0
        self._quiet_frames = 0
        self._was_playing = False
        self._last_now = None

    def reset(self):
        self._tail = None
        self._expected = 0.0
        self._base = 0
        self._quiet_frames = 0
        self._was_playing = False
        self.speed = 1.0
        self.pressure = 0.0
        self._last_now = None

    @staticmethod
    def _samples(data):
        result = array.array('h')
        callback = getattr(result, 'frombytes', None) or result.fromstring
        callback(to_bytes(data))
        if sys.byteorder != 'little':
            result.byteswap()
        return result

    @staticmethod
    def _bytes(samples):
        result = array.array('h', samples)
        if sys.byteorder != 'little':
            result.byteswap()
        callback = getattr(result, 'tobytes', None) or result.tostring
        return callback()

    @staticmethod
    def _quiet(samples):
        # Both a low peak and low RMS are required: protect weak consonants.
        return bool(samples) and max(abs(x) for x in samples) <= 48 and \
            sum(x * x for x in samples) <= len(samples) * 16 * 16

    def _alignment(self, samples, target):
        low = max(0, target - self.SEARCH)
        high = min(len(samples) - 2 * self.HOP, target + self.SEARCH)
        target = max(low, min(high, target))
        if self._tail is None or high <= low:
            return target
        reference = self._tail[::8]
        energy = sum(x * x for x in reference)
        if energy < len(reference) * 16 * 16:
            return target
        best, score = target, -2.0
        candidates = list(range(low, high + 1, 8)) + [target]
        for offset in candidates:
            candidate = samples[offset:offset + self.HOP:8]
            norm = sum(x * x for x in candidate)
            correlation = sum(a * b for a, b in zip(reference, candidate))
            value = correlation / math.sqrt(max(1.0, float(energy) * norm))
            value -= abs(offset - target) * 0.00001
            if value > score:
                best, score = offset, value
        # Refine locally to avoid coarse-search phase steps.
        for offset in range(max(low, best - 7), min(high, best + 7) + 1):
            candidate = samples[offset:offset + self.HOP:8]
            norm = sum(x * x for x in candidate)
            correlation = sum(a * b for a, b in zip(reference, candidate))
            value = correlation / math.sqrt(max(1.0, float(energy) * norm))
            value -= abs(offset - target) * 0.00001
            if value > score:
                best, score = offset, value
        return best

    def read(self, now):
        dt = .02 if self._last_now is None else max(0.0, min(.1, now - self._last_now))
        self._last_now = now
        with self.buffer._lock:
            data = self.buffer._data
            queued = len(data) / 48000.0
            self.peak_queue = max(self.peak_queue, queued)
            # Two-second smoothing avoids accelerating for an ordinary burst.
            self.pressure += (queued - self.pressure) * min(1.0, dt / 2.0)
            target = 1.0 + min(.12, max(0.0, self.pressure - self.reserve_seconds - .65) * .06)
            if queued < self.reserve_seconds + .35:
                target = 1.0
            step = dt * .025
            self.speed += max(-step, min(step, target - self.speed))
            if not data:
                if self._was_playing:
                    self.underruns += 1
                    self.jitter = min(.48, self.jitter + .04)
                self._was_playing = False
                self._tail = None
                self._base = 0
                self._expected = 0.0
                self._quiet_frames = 0
                self.buffer._playing = False
                self.buffer._waiting_since = None
                return b'\0' * OUTPUT_FRAME_BYTES, False
            if not self.buffer._playing:
                start = self.buffer._waiting_since
                waited = now - (start if start is not None else now)
                if queued < self.jitter and waited < self.jitter:
                    return b'\0' * OUTPUT_FRAME_BYTES, False
                self.buffer._playing = True
            self._was_playing = True
            self.jitter = max(.16, self.jitter - dt * .001)

            # Inspect only the small DSP window, not the whole six-second FIFO.
            count = min(len(data) // 2, 2 * self.HOP + 2 * self.SEARCH + 128)
            samples = self._samples(data[:count * 2])
            quiet = self._quiet(samples[:self.HOP])
            self._quiet_frames = self._quiet_frames + 1 if quiet else 0
            # Keep at least 180 ms of an actual PCM pause. Never trim a pause
            # when there is no received continuation or no queue pressure.
            if (self._quiet_frames > 9 and queued > self.reserve_seconds + .65
                    and self.pressure > self.reserve_seconds + .65
                    and len(samples) >= 2 * self.HOP
                    and self._quiet(samples[self.HOP:2 * self.HOP])):
                del data[:self.HOP * 2]
                self.trimmed_samples += self.HOP
                samples = samples[self.HOP:]
                self._tail = None
                self._base = 0
                self._expected = 0.0

            if len(samples) < 2 * self.HOP or (self.speed < 1.001 and self._tail is None):
                output = samples[:self.HOP]
                consumed = len(output)
                self._tail = None
                self._base = 0
                self._expected = 0.0
            elif self._tail is None:
                output = samples[:self.HOP]
                self._tail = samples[self.HOP:2 * self.HOP]
                consumed = self.HOP
                self._expected = self.HOP * self.speed
                self._base = self.HOP
            else:
                offset = self._alignment(samples, int(round(self._expected - self._base)))
                output = [int((a * (self.HOP - i) + samples[offset + i] * i) / self.HOP)
                          for i, a in enumerate(self._tail)]
                self._tail = samples[offset + self.HOP:offset + 2 * self.HOP]
                consumed = offset + self.HOP
                self.compressed_samples += offset
                self._base += consumed
                self._expected += self.HOP * self.speed
            del data[:consumed * 2]
            self.played_samples += len(output)
            result = self._bytes(output)
            return result + b'\0' * (OUTPUT_FRAME_BYTES - len(result)), bool(output)

    def metrics(self):
        return dict(tempo=round(self.speed, 4), queued_ms=int(self.buffer.size() / 48),
                    sync_reserve_ms=int(self.reserve_seconds * 1000),
                    queue_peak_ms=int(self.peak_queue * 1000),
                    jitter_ms=int(self.jitter * 1000), underruns=self.underruns,
                    silence_trimmed_ms=int(self.trimmed_samples / 24),
                    time_saved_ms=int(self.compressed_samples / 24),
                    overflow_ms=int(self.buffer.dropped_size() / 48))

class WebSocketClosed(IOError):
    def __init__(self, code, reason):
        self.code = code
        self.reason = sanitize_detail(reason)
        IOError.__init__(self, "WebSocket closed (code=%s, reason=%s)" %
                         (code, self.reason or "none"))


class LiveAPIError(IOError):
    pass


class DriftResync(LiveAPIError):
    """The session is translating the past; start a new one on live audio."""


class GoAwayError(LiveAPIError):
    """The server asked a healthy resumable session to migrate."""


def goaway_reconnect_delay(value, margin=8.0):
    """Return when to rotate, leaving setup latency before server shutdown."""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if match is None:
        return 0.0
    return max(0.0, float(match.group(1)) - float(margin))


class WebSocketUpgradeError(IOError):
    def __init__(self, status_code, status_line, error_kind=""):
        self.status_code = status_code
        self.status_line = sanitize_detail(status_line)
        self.error_kind = error_kind
        IOError.__init__(
            self, "WebSocket upgrade rejected (%s)" % self.status_line
        )


# The one sentence Google's edge serves when it refuses the client itself.
EDGE_BLOCK_MARKERS = (
    "does not have permission to get url",
    "client does not have permission",
)
EDGE_BLOCK_REPORTED = [False]


def upgrade_rejection_kind(status_code, body_detail):
    """Separate a Gemini denial from a refusal somewhere on the network path.

    The Live API answers a denied request with its documented JSON error body.
    A 403 carrying an HTML page was written by something in front of the API -
    Google's own edge refusing the client IP, or a proxy or captive portal - so
    the request never reached Gemini and the API key cannot be the cause.
    """
    lowered = (body_detail or "").lower()
    if any(marker in lowered for marker in EDGE_BLOCK_MARKERS):
        return "edge_block"
    if status_code == 403 and lowered.startswith("unparsed_body="):
        return "edge_block"
    return ""


def report_edge_block():
    """Explain a network-path refusal once, not on every retry.

    Without this the viewer only ever sees "403" and spends the evening
    replacing a working API key.
    """
    if EDGE_BLOCK_REPORTED[0]:
        return
    EDGE_BLOCK_REPORTED[0] = True
    log("Gemini refused before the Live API was reached: HTTP 403 whose body "
        "is an HTML page instead of the API's JSON error. The request never "
        "arrived at Gemini, so the API key is not the cause - the exit IP of "
        "the current Internet path is blocked. Replacing the key will not "
        "help; change the VPN/proxy server or the network route.")


def parse_http_status(response):
    """Return a safe HTTP status without logging the credential-bearing URL."""
    try:
        first = response.split("\r\n", 1)[0].strip()
    except Exception:
        first = "unreadable HTTP response"
    first = sanitize_detail(first)
    code = None
    parts = first.split(" ", 2)
    if len(parts) >= 2:
        try:
            code = int(parts[1])
        except Exception:
            pass
    return code, first


def parse_http_error_body(body):
    """Extract only documented Google error fields; never log arbitrary HTML."""
    if not body:
        return ""
    try:
        if not isinstance(body, str):
            body = body.decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except ValueError:
            # Chunked framing wraps the JSON in hex length lines, so fall back
            # to the outermost brace pair before giving up on the payload.
            start = body.find("{")
            end = body.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(body[start:end + 1])
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if not isinstance(error, dict):
            return ""
        parts = []
        for key in ("code", "status", "message"):
            if error.get(key) is not None:
                parts.append("%s=%s" % (key, sanitize_detail(error.get(key))))
        return ", ".join(parts)[:240]
    except Exception:
        # A proxy or captive portal can answer with an HTML page instead. Log a
        # short, tag-free snippet so the cause is still visible, rather than
        # dropping the only evidence the user has.
        try:
            if not isinstance(body, str):
                body = body.decode("utf-8", "replace")
            # Google's edge 403 page carries its stylesheet inline, which
            # otherwise fills the whole snippet with CSS and truncates away the
            # one sentence that says why the request was refused.
            cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
            text = re.sub(r"<[^>]*>", " ", cleaned)
            text = " ".join(text.split())
            return ("unparsed_body=%s" % sanitize_detail(text)[:180]) if text else ""
        except Exception:
            return ""


def certificate_common_name(certificate, field):
    """Return one public certificate CN without dumping the full certificate."""
    try:
        for relative_name in certificate.get(field, ()):
            for name, value in relative_name:
                if name == "commonName":
                    return sanitize_detail(value)
    except Exception:
        pass
    return "unknown"


def tls_session_summary(tls, verified):
    """Return non-secret TLS diagnostics supported by old embedded Python."""
    version = "unknown"
    cipher_name = "unknown"
    subject = "unknown"
    issuer = "unknown"
    try:
        callback = getattr(tls, "version", None)
        if callback is not None:
            version = sanitize_detail(callback())
    except Exception:
        pass
    try:
        cipher = tls.cipher()
        if cipher:
            cipher_name = sanitize_detail(cipher[0])
    except Exception:
        pass
    try:
        certificate = tls.getpeercert() or {}
        subject = certificate_common_name(certificate, "subject")
        issuer = certificate_common_name(certificate, "issuer")
    except Exception:
        pass
    return ("version=%s cipher=%s verified=%s subject_cn=%s issuer_cn=%s" %
            (version, cipher_name, "yes" if verified else "legacy",
             subject, issuer))


class WebSocket(object):
    def __init__(self, api_key):
        self.api_key = api_key
        self.sock = None
        self.write_lock = threading.Lock()
        self.fragments = bytearray()
        self.fragment_opcode = None
        self.recv_buffer = bytearray()

    def connect(self):
        # Prefer IPv4 because many receiver/router VPN policies cover IPv4 but
        # let an AAAA route bypass the tunnel. Log stage boundaries so a TCP,
        # TLS, proxy/DPI or WebSocket failure can be distinguished remotely.
        tcp_started = steady_time()
        log("Gemini connection stage=tcp_connect started host=%s port=%d family=IPv4" %
            (HOST, PORT))
        try:
            raw = create_ipv4_connection(HOST, PORT, 15)
        except Exception as error:
            log("Gemini connection stage=tcp_connect failed elapsed=%.2fs detail=%s" %
                (steady_time() - tcp_started, sanitize_detail(error)))
            raise
        try:
            peer = raw.getpeername()[0]
            log("Gemini connection stage=tcp_connect complete elapsed=%.2fs peer=%s" %
                (steady_time() - tcp_started, peer))
        except Exception:
            log("Gemini connection stage=tcp_connect complete elapsed=%.2fs peer=unknown" %
                (steady_time() - tcp_started))
        # Keep the connection timeout for the TLS handshake.  Version 0.3.0
        # shortened this to two seconds before wrap_socket(), which made
        # otherwise healthy embedded receivers fail behind a TUN/VPN.
        raw.settimeout(TLS_HANDSHAKE_TIMEOUT_SECONDS)
        context = None
        if hasattr(ssl, "create_default_context"):
            context = ssl.create_default_context()
        tls_started = steady_time()
        log("Gemini connection stage=tls_handshake started timeout=%.1fs sni=%s" %
            (TLS_HANDSHAKE_TIMEOUT_SECONDS, HOST))
        try:
            if context is not None:
                tls = context.wrap_socket(raw, server_hostname=HOST)
            else:
                tls = ssl.wrap_socket(raw, ssl_version=ssl.PROTOCOL_TLSv1_2)
        except Exception as error:
            log("Gemini connection stage=tls_handshake failed elapsed=%.2fs detail=%s" %
                (steady_time() - tls_started, sanitize_detail(error)))
            try:
                raw.close()
            except Exception:
                pass
            raise
        log("Gemini connection stage=tls_handshake complete elapsed=%.2fs %s" %
            (steady_time() - tls_started,
             tls_session_summary(tls, context is not None)))
        tls.settimeout(HTTP_UPGRADE_TIMEOUT_SECONDS)

        nonce = base64.b64encode(os.urandom(16))
        if not isinstance(nonce, str):
            nonce = nonce.decode("ascii")
        path = ("/ws/google.ai.generativelanguage.v1beta."
                "GenerativeService.BidiGenerateContent?key=" + self.api_key)
        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: e2dub/1.2.42\r\n\r\n"
        ) % (path, HOST, nonce)
        upgrade_started = steady_time()
        log("Gemini connection stage=websocket_upgrade started timeout=%.1fs" %
            HTTP_UPGRADE_TIMEOUT_SECONDS)
        try:
            tls.sendall(request.encode("ascii"))
            log("Gemini connection stage=websocket_upgrade request_sent")
            response, remainder = self._read_headers(tls)
            lines = response.split("\r\n")
            status_code, status_line = parse_http_status(response)
            log("Gemini connection stage=websocket_upgrade response elapsed=%.2fs status=%s" %
                (steady_time() - upgrade_started,
                 status_code if status_code is not None else "unknown"))
            if not lines or " 101 " not in lines[0]:
                body = self._read_http_error_body(tls, lines, remainder)
                body_detail = parse_http_error_body(body)
                if body_detail:
                    body_detail = body_detail.replace(self.api_key, "[redacted]")
                    status_line = "%s: %s" % (status_line, body_detail)
                raise WebSocketUpgradeError(
                    status_code, status_line,
                    upgrade_rejection_kind(status_code, body_detail),
                )
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1(
                (nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest())
            if not isinstance(expected, str):
                expected = expected.decode("ascii")
            if headers.get("sec-websocket-accept") != expected:
                raise IOError("Invalid WebSocket handshake")
        except Exception as error:
            log("Gemini connection stage=websocket_upgrade failed elapsed=%.2fs detail=%s" %
                (steady_time() - upgrade_started, sanitize_detail(error)))
            try:
                tls.close()
            except Exception:
                pass
            raise
        tls.settimeout(WEBSOCKET_READ_TIMEOUT_SECONDS)
        self.recv_buffer = bytearray(remainder)
        self.sock = tls
        log("Gemini connection stage=websocket_upgrade complete elapsed=%.2fs buffered=%d" %
            (steady_time() - upgrade_started, len(remainder)))

    def _read_headers(self, sock):
        data = bytearray()
        marker = b"\r\n\r\n"
        while data.find(marker) < 0:
            chunk = sock.recv(1024)
            if not chunk:
                raise IOError("Connection closed during handshake")
            data.extend(bytearray(chunk))
            if len(data) > 32768:
                raise IOError("Oversized handshake")
        end = data.find(marker) + len(marker)
        raw = to_bytes(data[:end])
        remainder = to_bytes(data[end:])
        text = raw.decode("iso-8859-1") if not isinstance(raw, str) else raw
        return text, remainder

    def _read_http_error_body(self, sock, header_lines, remainder):
        length = 0
        for line in header_lines[1:]:
            if line.lower().startswith("content-length:"):
                try:
                    length = min(4096, int(line.split(":", 1)[1].strip()))
                except Exception:
                    length = 0
                break
        data = bytearray(remainder[:4096])
        while length and len(data) < length:
            try:
                chunk = sock.recv(min(1024, length - len(data)))
            except Exception as error:
                if is_read_timeout(error):
                    break
                raise
            if not chunk:
                break
            data.extend(bytearray(chunk))
        if not length:
            # Google returns its JSON error with Transfer-Encoding: chunked and
            # no Content-Length, so the old code kept only whatever happened to
            # arrive in the header buffer -- usually nothing, which is why a
            # rejected key logged a bare "403 Forbidden" with no reason.
            # Best-effort drain instead, bounded by size and the read timeout.
            try:
                sock.settimeout(ERROR_BODY_TIMEOUT_SECONDS)
            except Exception:
                pass
            while len(data) < 4096:
                try:
                    chunk = sock.recv(min(1024, 4096 - len(data)))
                except Exception as error:
                    if is_read_timeout(error):
                        break
                    raise
                if not chunk:
                    break
                data.extend(bytearray(chunk))
        return to_bytes(data[:length or len(data)])

    def send_json(self, value):
        payload = json.dumps(value, separators=(",", ":"))
        self.send_frame(0x1, payload.encode("utf-8"))

    def send_frame(self, opcode, payload):
        if self.sock is None:
            raise IOError("WebSocket is closed")
        if isinstance(payload, bytearray):
            payload = to_bytes(payload)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xffff:
            header.append(0x80 | 126)
            header.extend(bytearray(struct.pack("!H", length)))
        else:
            header.append(0x80 | 127)
            header.extend(bytearray(struct.pack("!Q", length)))
        mask = os.urandom(4)
        header.extend(bytearray(mask))
        masked = bytearray(payload)
        mask_values = bytearray(mask)
        for index in range(length):
            masked[index] ^= mask_values[index & 3]
        packet = header + masked
        packet = to_bytes(packet)
        with self.write_lock:
            self.sock.sendall(packet)

    def recv_message(self):
        while True:
            first = self._recv_exact(2)
            b1, b2 = bytearray(first)
            final = bool(b1 & 0x80)
            if b1 & 0x70:
                raise IOError("Unsupported WebSocket RSV bits")
            opcode = b1 & 0x0f
            masked = bool(b2 & 0x80)
            if masked:
                raise IOError("Protocol error: masked server frame")
            length = b2 & 0x7f
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            if length > MAX_WS_MESSAGE_BYTES:
                raise IOError("WebSocket frame is too large")
            if opcode >= 0x8 and (not final or length > 125):
                raise IOError("Invalid WebSocket control frame")
            mask = self._recv_exact(4) if masked else None
            payload = bytearray(self._recv_exact(length))
            if mask:
                mask_values = bytearray(mask)
                for index in range(length):
                    payload[index] ^= mask_values[index & 3]

            raw_payload = to_bytes(payload)
            if opcode == 0x8:
                code = 1005
                reason = ""
                if len(raw_payload) >= 2:
                    code = struct.unpack("!H", raw_payload[:2])[0]
                    try:
                        reason = raw_payload[2:].decode("utf-8", "replace")
                    except Exception:
                        reason = "unreadable"
                try:
                    self.send_frame(0x8, raw_payload or struct.pack("!H", 1000))
                except Exception:
                    pass
                raise WebSocketClosed(code, reason)
            if opcode == 0x9:
                self.send_frame(0xA, raw_payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                if self.fragment_opcode is not None:
                    raise IOError("Unexpected data frame during fragmentation")
                if final:
                    return opcode, raw_payload
                self.fragment_opcode = opcode
                self.fragments = bytearray(payload)
                continue
            if opcode == 0x0 and self.fragment_opcode is not None:
                self.fragments.extend(payload)
                if len(self.fragments) > MAX_WS_MESSAGE_BYTES:
                    raise IOError("WebSocket message is too large")
                if final:
                    result = self.fragments
                    result_opcode = self.fragment_opcode
                    self.fragments = bytearray()
                    self.fragment_opcode = None
                    raw = to_bytes(result)
                    return result_opcode, raw
                continue
            raise IOError("Unsupported WebSocket opcode %s" % opcode)

    def _recv_exact(self, size):
        chunks = []
        remaining = size
        if self.recv_buffer:
            count = min(remaining, len(self.recv_buffer))
            chunks.append(to_bytes(self.recv_buffer[:count]))
            del self.recv_buffer[:count]
            remaining -= count
        sock = self.sock
        if sock is None:
            raise IOError("WebSocket is closed")
        while remaining:
            try:
                chunk = sock.recv(remaining)
            except Exception as error:
                if is_read_timeout(error):
                    if STOP.is_set():
                        raise IOError("Stopping")
                    continue
                raise
            if not chunk:
                raise IOError("WebSocket connection lost")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def close(self):
        sock = self.sock
        self.sock = None
        if sock is not None:
            # SIGTERM can interrupt send_frame while its write lock is held.
            # Never acquire that lock during shutdown.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass


STOP = threading.Event()
INPUT_QUEUE = queue.Queue(50)
INPUT_READY = threading.Event()
# Include intentional A/V waiting in the cap; a long user sync correction
# must not discard speech before its first presentation deadline. <= 864 KB
# for the normal 4..12 s startup policy and the supported +4 s correction.
OUTPUT = AudioBuffer(max(MAX_OUTPUT_BYTES, int((
    max(12.0 if ADAPTIVE_STARTUP else 0.0, PLAYBACK_DELAY_SECONDS) +
    max(0.0, AUDIO_SYNC_CORRECTION_SECONDS) + 6.0) * 48000)))
OUTPUT_UDP_DROPS = [0]
CURRENT_WS = [None]
SESSION_HANDLE = [None]
SOURCE_CAPTURE_ANCHOR = [None]
# Audio captured while a fresh session is still negotiating cannot be
# translated until after setup latency, and sending it afterwards makes the
# model work through history it can never catch up on -- a startup backlog
# that becomes a permanent offset. The subtitle engine learned this first.
STREAM_ACCEPTING_INPUT = threading.Event()
INPUT_DISCONNECTED_DROPS = [0]
INPUT_QUEUE_FULL_DROPS = [0]
INPUT_STALE_DROPS = [0]
RECV_SPEECH_AT = [0.0]      # last translated speech that arrived
MODEL_IDLE_AT = [0.0]       # last time the model had nothing left to say
RESYNC_REQUEST = [False]    # a drain that never finished: rebuild the session
DRIFT_SECONDS = [0.0]       # backlog measured by the last drain
FEEDING = [True]
FIRST_TRANSLATED_AT = [None]
FIRST_TRANSLATED_SOURCE_ANCHOR = [None]
TRANSLATED_OUTPUT_STARTED = threading.Event()
OUTPUT_RESET_TOKEN = [0]
AUDIO_READY_CONTEXT = [{}]
PLAYOUT_METRICS = [{}]


def read_api_key():
    with open(KEY_FILE, "rb") as handle:
        key = handle.read(4096).strip()
    if not key:
        raise ValueError("API key file is empty")
    if not isinstance(key, str):
        key = key.decode("ascii")
    if any(ch.isspace() for ch in key):
        raise ValueError("API key file contains whitespace")
    return key


def ebml_vint(data, offset, keep_marker=False):
    if offset >= len(data):
        return None
    first = data[offset]
    if not isinstance(first, int):
        first = ord(first)
    mask = 0x80
    width = 1
    while width <= 8 and not (first & mask):
        mask >>= 1
        width += 1
    if width > 8 or offset + width > len(data):
        return None
    value = first if keep_marker else first & (mask - 1)
    for index in range(1, width):
        item = data[offset + index]
        if not isinstance(item, int):
            item = ord(item)
        value = (value << 8) | item
    return value, width


class MatroskaPCMExtractor(object):
    """Extract un-laced PCM blocks from FFmpeg's bounded live clusters."""
    CLUSTER_ID = b"\x1f\x43\xb6\x75"

    def __init__(self):
        self.buffer = bytearray()

    def _block(self, payload):
        track = ebml_vint(payload, 0)
        if track is None:
            return b""
        _track_number, width = track
        if len(payload) < width + 3:
            return b""
        flags = payload[width + 2]
        if not isinstance(flags, int):
            flags = ord(flags)
        if flags & 0x06:
            return b""
        return bytes(payload[width + 3:])

    def _elements(self, payload):
        output = []
        offset = 0
        while offset < len(payload):
            id_info = ebml_vint(payload, offset, keep_marker=True)
            if id_info is None:
                break
            identifier, id_width = id_info
            size_info = ebml_vint(payload, offset + id_width)
            if size_info is None:
                break
            size, size_width = size_info
            start = offset + id_width + size_width
            end = start + size
            if end > len(payload):
                break
            body = payload[start:end]
            if identifier in (0xA3, 0xA1):
                pcm = self._block(body)
                if pcm:
                    output.append(pcm)
            elif identifier == 0xA0:
                output.extend(self._elements(body))
            offset = end
        return output

    def feed(self, chunk):
        if chunk:
            self.buffer.extend(bytearray(chunk))
        output = []
        while True:
            start = self.buffer.find(self.CLUSTER_ID)
            if start < 0:
                if len(self.buffer) > 3:
                    del self.buffer[:-3]
                break
            if start:
                del self.buffer[:start]
            size_info = ebml_vint(self.buffer, len(self.CLUSTER_ID))
            if size_info is None:
                break
            size, width = size_info
            header = len(self.CLUSTER_ID) + width
            if size > 1024 * 1024:
                del self.buffer[0]
                continue
            end = header + size
            if len(self.buffer) < end:
                break
            output.extend(self._elements(self.buffer[header:end]))
            del self.buffer[:end]
        return output


def stdin_reader():
    pending = bytearray()
    extractor = MatroskaPCMExtractor() if MATROSKA_PCM_MODE else None
    total_bytes = 0
    last_state_at = 0.0
    last_signal_at = 0.0
    signal_frames = 0
    preroll = []
    paused_at = 0.0
    fed_since = steady_time()
    set_input_state("waiting", 0, 0.0)
    while not STOP.is_set():
        try:
            chunk = os.read(0, 8192)
        except OSError as error:
            if error.errno == errno.EINTR:
                continue
            log("Source PCM read failed: %s" % sanitize_detail(error))
            set_input_state("stopped", total_bytes, last_signal_at)
            STOP.set()
            return
        if not chunk:
            set_input_state("stopped", total_bytes, last_signal_at)
            STOP.set()
            return
        chunks = extractor.feed(chunk) if extractor is not None else (chunk,)
        for pcm in chunks:
            pending.extend(bytearray(pcm))
            while len(pending) >= INPUT_CHUNK_BYTES:
                frame = pending[:INPUT_CHUNK_BYTES]
                del pending[:INPUT_CHUNK_BYTES]
                raw = to_bytes(frame)
                dump_pcm('cap16', raw)
                source_start = total_bytes / 32000.0
                total_bytes += len(raw)
                source_end = total_bytes / 32000.0
                captured_at = steady_time()
                if SOURCE_CAPTURE_ANCHOR[0] is None:
                    SOURCE_CAPTURE_ANCHOR[0] = captured_at
                speaking = pcm_has_meaningful_signal(raw)
                if speaking:
                    signal_frames += 1
                    last_signal_at = captured_at
                    if signal_frames >= INPUT_SIGNAL_CONFIRM_FRAMES:
                        INPUT_READY.set()
                    input_state = ("ready" if INPUT_READY.is_set()
                                   else "detecting")
                else:
                    signal_frames = 0
                    input_state = "silence"
                now = steady_time()
                if not last_state_at or now - last_state_at >= 1.0:
                    set_input_state(input_state, total_bytes, last_signal_at)
                    last_state_at = now
                # Silence costs the model as much rendering time as speech
                # does, and it has none to spare. Send speech with a short
                # run-up and tail; hold the rest back as catch-up time.
                send = [(raw, source_start, source_end, captured_at)]
                if INPUT_SILENCE_GATE:
                    if speaking:
                        send = list(preroll) + send
                        preroll = []
                    elif captured_at - last_signal_at <= INPUT_HANGOVER_SECONDS:
                        pass
                    else:
                        preroll.append(send[0])
                        del preroll[:-INPUT_PREROLL_FRAMES]
                        send = []
                # Probe only when received translation exceeds the scheduled
                # A/V reserve. The reserve itself is intentional, not drift.
                idle = MODEL_IDLE_AT[0]
                if FEEDING[0]:
                    if (TRANSLATED_OUTPUT_STARTED.is_set() and
                            should_probe_backlog(captured_at, fed_since,
                                                 PLAYOUT_METRICS[0])):
                        FEEDING[0] = False
                        paused_at = captured_at
                        log("Pausing the source feed to measure and clear any "
                            "translation backlog")
                elif idle >= paused_at or captured_at - paused_at > DRAIN_MAX_SECONDS:
                    drained = idle >= paused_at
                    DRIFT_SECONDS[0] = max(0.0, (idle if drained else captured_at)
                                           - paused_at)
                    FEEDING[0] = True
                    fed_since = captured_at
                    preroll = []
                    MODEL_IDLE_AT[0] = captured_at
                    if drained:
                        log("Backlog drained in %.1fs; feeding live audio again"
                            % DRIFT_SECONDS[0])
                    else:
                        # Still talking after a full drain window: the session
                        # is too far behind to recover by feeding alone.
                        RESYNC_REQUEST[0] = True
                        log("Backlog still not clear after %.0fs; asking for a "
                            "new session on live audio" % DRAIN_MAX_SECONDS)
                if not FEEDING[0] or not STREAM_ACCEPTING_INPUT.is_set():
                    if send and not STREAM_ACCEPTING_INPUT.is_set():
                        INPUT_DISCONNECTED_DROPS[0] += len(send)
                    send = []
                for item in send:
                    try:
                        INPUT_QUEUE.put_nowait(item)
                    except queue.Full:
                        # Live translation prefers the newest speech: drop the
                        # oldest frame rather than build a FIFO behind it.
                        try:
                            INPUT_QUEUE.get_nowait()
                            INPUT_QUEUE_FULL_DROPS[0] += 1
                        except queue.Empty:
                            pass
                        try:
                            INPUT_QUEUE.put_nowait(item)
                        except queue.Full:
                            INPUT_QUEUE_FULL_DROPS[0] += 1


def pcm_writer():
    """One 20 ms output clock; video and original audio never wait for Gemini.

    Read translated samples only when they will actually be played. A second
    producer clock used to insert silence into a delayed queue even though
    the missing samples arrived before the viewer's playback deadline.
    """
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setblocking(False)
    destination = (DUB_UDP_HOST, DUB_UDP_PORT)
    silence = b"\x00" * OUTPUT_FRAME_BYTES
    sender_tick = None
    reset_token = OUTPUT_RESET_TOKEN[0]
    playback_reported = False
    player = AdaptivePlayout(OUTPUT)
    playback_delay = None if ADAPTIVE_STARTUP else PLAYBACK_DELAY_SECONDS
    last_probe = 0.0
    last_metrics = 0.0
    clock_late_max_ms = 0
    try:
        while not STOP.is_set():
            now = steady_time()
            source_anchor = SOURCE_CAPTURE_ANCHOR[0]
            if playback_delay is None and now - last_probe >= .1:
                last_probe = now
                try:
                    with open(RELAY_STATE_FILE, 'r') as handle:
                        relay = json.load(handle)
                    if relay.get('startup_locked') and relay.get('started_monotonic', 0) >= (source_anchor or now) - 2:
                        playback_delay = float(relay['delay_ms']) / 1000.0
                except Exception:
                    pass
                if source_anchor is not None and now - source_anchor >= 12.5:
                    playback_delay = 12.0 if playback_delay is None else playback_delay
            video_due = (source_anchor + playback_delay
                         if source_anchor is not None and playback_delay is not None else None)
            translated_source_anchor = FIRST_TRANSLATED_SOURCE_ANCHOR[0]
            translated_due = None
            if translated_source_anchor is not None and playback_delay is not None:
                translated_due = (
                    translated_source_anchor + playback_delay +
                    AUDIO_SYNC_CORRECTION_SECONDS
                )
                if video_due is not None and translated_due < video_due:
                    translated_due = video_due
            if OUTPUT_RESET_TOKEN[0] != reset_token:
                reset_token = OUTPUT_RESET_TOKEN[0]
                playback_reported = False
                player.reset()
            if translated_due is not None and FIRST_TRANSLATED_AT[0] is not None:
                # Only backlog beyond scheduled waiting is overload. Otherwise
                # compression erases A/V delay and can move speech ahead of video.
                player.reserve_seconds = max(0.0, translated_due - FIRST_TRANSLATED_AT[0])
            if video_due is not None and now >= video_due:
                if sender_tick is None:
                    sender_tick = now
                clock_late_max_ms = max(clock_late_max_ms, int(max(0.0, now - sender_tick) * 1000))
                sent_frames = 0
                while sender_tick <= now + 0.001 and sent_frames < 5:
                    if (translated_due is not None and
                            sender_tick + 0.0005 >= translated_due and
                            TRANSLATED_OUTPUT_STARTED.is_set()):
                        frame, present = player.read(now)
                    else:
                        frame, present = silence, False
                    delivered = False
                    try:
                        udp.sendto(frame, destination)
                        delivered = True
                    except socket.error:
                        OUTPUT_UDP_DROPS[0] += 1
                    if present and delivered and not playback_reported:
                        context = dict(AUDIO_READY_CONTEXT[0] or {})
                        set_state("audio", **context)
                        playback_reported = True
                        log(
                            "Translated PCM reached delayed source timeline "
                            "(video_delay=%dms sync=%+dms)" %
                            (int(round(playback_delay * 1000.0)),
                             int(round(AUDIO_SYNC_CORRECTION_SECONDS * 1000.0)))
                        )
                    sender_tick += 0.02
                    sent_frames += 1
                # Keep the sample clock after a scheduling pause. The next
                # pass drains at most five frames too; dropping clock slots
                # here permanently shortened PCM relative to source video.
            if now - last_metrics >= 1.0:
                last_metrics = now
                metrics = player.metrics()
                metrics.update(updated_monotonic=now, playback_delay_ms=(
                    int(playback_delay * 1000) if playback_delay is not None else None))
                metrics.update(clock_late_max_ms=clock_late_max_ms,
                               udp_drops=OUTPUT_UDP_DROPS[0])
                PLAYOUT_METRICS[0] = metrics
                path = STATE_FILE + '-playout'
                temporary = path + '.tmp'
                try:
                    with open(temporary, 'w') as handle:
                        json.dump(metrics, handle, separators=(',', ':'))
                    os.rename(temporary, path)
                except Exception:
                    pass
            # Nothing said for MODEL_QUIET_SECONDS: the model has no
            # backlog left. Marked here, on the clock that always runs, and
            # not in the receiver, which stops with the arriving frames.
            if RECV_SPEECH_AT[0] and now - RECV_SPEECH_AT[0] >= MODEL_QUIET_SECONDS:
                MODEL_IDLE_AT[0] = now
            wake = now + 0.02
            if sender_tick is not None:
                wake = min(wake, sender_tick)
            elif video_due is not None:
                wake = min(wake, video_due)
            STOP.wait(max(0.001, min(0.02, wake - steady_time())))
    finally:
        udp.close()


def discard_queued_input():
    """Empty the input queue and report how many frames were thrown away."""
    dropped = 0
    while True:
        try:
            INPUT_QUEUE.get_nowait()
            dropped += 1
        except queue.Empty:
            return dropped


def setup_message(profile="official", target_language=None,
                  session_handle=None):
    """Build a dedicated translated-audio Gemini Live session."""
    target_language = target_language or TARGET_LANGUAGE
    if target_language not in ("fa", "ar"):
        raise ValueError("Unsupported target language")
    setup = {
        "model": "models/" + MODEL,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "translationConfig": {
                "targetLanguageCode": target_language,
                "echoTargetLanguage": False
            }
        },
        # Request resumable state on the first connection (JSON null handle)
        # and attach the newest server token on every planned rotation.
        "sessionResumption": {"handle": session_handle},
    }
    # Live Translate processes continuous speech. Conversational VAD and
    # barge-in settings can cancel a translation when the next speaker starts.
    # Keep old profile names as call-site aliases to the same bare setup.
    if profile not in ("official", "managed", "minimal"):
        raise ValueError("Unknown setup profile")
    return {"setup": setup}


def api_error_text(error):
    if not isinstance(error, dict):
        return sanitize_detail(error)
    parts = []
    for key in ("code", "status", "message"):
        if error.get(key) is not None:
            parts.append("%s=%s" % (key, sanitize_detail(error.get(key))))
    return ", ".join(parts) or "unspecified Live API error"


def should_fast_reconnect(error):
    """Retry transport loss quickly, but back off quota/policy failures."""
    if isinstance(error, GoAwayError):
        return True
    if isinstance(error, (LiveAPIError, WebSocketUpgradeError)):
        return False
    if isinstance(error, WebSocketClosed):
        return error.code not in (1008, 1011, 1013)
    return True


def receiver(ws, dead, ready, failure, state_context, flow):
    """Receive translated PCM only; subtitle timing/state does not exist here."""
    reported_audio = False
    try:
        while not STOP.is_set() and not dead.is_set():
            rotate_at = flow.get("go_away_reconnect_at")
            if rotate_at is not None and steady_time() >= rotate_at:
                raise GoAwayError("scheduled session rotation")
            opcode, payload = ws.recv_message()
            if not isinstance(payload, str):
                payload = payload.decode("utf-8", "replace")
            message = json.loads(payload)
            if not isinstance(message, dict):
                raise IOError("Unexpected non-object Live API message")
            if message.get("error") is not None:
                raise LiveAPIError(api_error_text(message.get("error")))
            if message.get("setupComplete") is not None:
                set_state("ready", **state_context)
                ready.set()
            update = message.get("sessionResumptionUpdate")
            if update and update.get("resumable") and update.get("newHandle"):
                SESSION_HANDLE[0] = update.get("newHandle")
            if message.get("goAway") is not None:
                go_away = message.get("goAway") or {}
                # goAway is advance notice, not an immediate failure.  Gemini
                # continues serving this socket until its advertised deadline.
                # Closing here wasted that window and created a multi-second
                # translation hole at every planned session rotation.
                if not flow.get("go_away_seen"):
                    flow["go_away_seen"] = True
                    flow["go_away_reconnect_at"] = (
                        steady_time() + goaway_reconnect_delay(
                            go_away.get("timeLeft"))
                    )
                    log("Gemini session rotation announced; continuing until "
                        "the safe reconnect point (timeLeft=%s)" %
                        sanitize_detail(go_away.get("timeLeft", "unknown")))
            content = message.get("serverContent") or {}
            if content.get("interrupted"):
                # Live Translate may mark a model turn interrupted when fresh
                # source speech arrives.  Unlike an interactive voice agent,
                # the viewer did not barge in and every PCM frame already in
                # OUTPUT is valid translation that still belongs on the fixed
                # playback timeline.  Clearing this FIFO used to discard up
                # to several seconds in the middle of a sentence, then jump
                # straight to the next turn.  Preserve received PCM; Gemini
                # itself simply stops producing the unfinished remainder.
                flow["interruptions"] = flow.get("interruptions", 0) + 1
                log("Gemini marked output interrupted; preserved buffered translated audio")
            turn = content.get("modelTurn") or {}
            for part in turn.get("parts") or []:
                inline = part.get("inlineData") or {}
                data = inline.get("data")
                if not data:
                    continue
                try:
                    decoded = base64.b64decode(data)
                except Exception:
                    log("Ignored malformed audio frame")
                    continue
                dump_pcm('trans24', decoded)
                flow["output_bytes"] += len(decoded)
                now = steady_time()
                flow["last_audio_at"] = now
                if not reported_audio:
                    captured_at = flow.get("first_input_captured_at")
                    sent_at = flow.get("first_input_sent_at")
                    capture_latency_ms = (
                        int(round(max(0.0, now - captured_at) * 1000.0))
                        if captured_at is not None else None
                    )
                    send_latency_ms = (
                        int(round(max(0.0, now - sent_at) * 1000.0))
                        if sent_at is not None else None
                    )
                    log(
                        "First translated audio received (%s PCM bytes, "
                        "capture_to_audio=%sms send_to_audio=%sms)" %
                        (len(decoded), capture_latency_ms, send_latency_ms)
                    )
                    metrics = dict(state_context)
                    metrics["first_audio_latency_ms"] = capture_latency_ms
                    metrics["first_audio_send_latency_ms"] = send_latency_ms
                    metrics["audio_arrived_monotonic"] = now
                    metrics["source_capture_anchor"] = SOURCE_CAPTURE_ANCHOR[0]
                    AUDIO_READY_CONTEXT[0] = metrics
                    if FIRST_TRANSLATED_AT[0] is None:
                        FIRST_TRANSLATED_AT[0] = now
                        FIRST_TRANSLATED_SOURCE_ANCHOR[0] = captured_at
                    # "audio" is published only when a real translated frame
                    # reaches the delayed playback timeline.  This prevents the
                    # UI from leaving original-audio fallback too early.
                    set_state(
                        "audio" if TRANSLATED_OUTPUT_STARTED.is_set()
                        else "audio_buffering", **metrics
                    )
                    reported_audio = True
                OUTPUT.append(decoded)
                TRANSLATED_OUTPUT_STARTED.set()
                # When this stops advancing the model has run dry, which is
                # what a paused feed is waiting to see.
                if pcm_speech_level(decoded) >= INPUT_SIGNAL_PEAK_THRESHOLD * 4:
                    RECV_SPEECH_AT[0] = now
                if (RESYNC_REQUEST[0] and
                        now - flow["started"] > DRIFT_MIN_SESSION_SECONDS):
                    RESYNC_REQUEST[0] = False
                    raise DriftResync(
                        "translation could not be brought back to the picture; "
                        "resyncing on live audio")
    except Exception as error:
        if not STOP.is_set():
            failure.append(error)
            log("Receiver disconnected: %s" % sanitize_detail(error))
        dead.set()


def connect_and_stream(api_key, profile, attempt, result,
                       reconnect_detail=None, resume=False):
    if not resume:
        # A rotation resumes mid-programme and its short gap is worth
        # bridging, but a fresh session starts level with the picture only if
        # nothing from before it is sent.
        STREAM_ACCEPTING_INPUT.clear()
        discard_queued_input()
    ws = WebSocket(api_key)
    CURRENT_WS[0] = ws
    setup_started_at = steady_time()
    try:
        state_context = {"profile": profile, "attempt": attempt}
        set_state("connecting", detail=reconnect_detail, **state_context)
        ws.connect()
        log("Connected to Gemini Live API; audio profile=%s attempt=%s" %
            (profile, attempt))
        if resume and SESSION_HANDLE[0]:
            log("Resuming Gemini session with server-issued token")
        ws.send_json(setup_message(
            profile, session_handle=SESSION_HANDLE[0] if resume else None
        ))
        dead = threading.Event()
        ready = threading.Event()
        failure = []
        flow = {
            "input_bytes": 0,
            "output_bytes": 0,
            "started": steady_time(),
            "last_log": steady_time(),
            "last_audio_at": 0.0,
        }
        thread = threading.Thread(
            target=receiver,
            args=(ws, dead, ready, failure, state_context, flow),
        )
        thread.daemon = True
        thread.start()
        deadline = steady_time() + SETUP_TIMEOUT_SECONDS
        while not STOP.is_set() and not dead.is_set() and not ready.is_set():
            if steady_time() >= deadline:
                raise IOError("Timed out waiting for setupComplete")
            STOP.wait(0.1)
        if dead.is_set():
            if failure:
                raise failure[0]
            raise IOError("Connection ended during setup without an error message")
        log("Gemini audio session is ready (profile=%s, setup=%.1fs)" %
            (profile, steady_time() - setup_started_at))
        result["ready"] = True
        if not resume:
            DRIFT_SECONDS[0] = 0.0
            FEEDING[0] = True
            MODEL_IDLE_AT[0] = steady_time()
            RECV_SPEECH_AT[0] = 0.0
            RESYNC_REQUEST[0] = False
        startup_dropped = discard_queued_input()
        STREAM_ACCEPTING_INPUT.set()
        if startup_dropped:
            log("Discarded %d source frames captured during setup"
                % startup_dropped)
        reported_input_send = False
        while not STOP.is_set() and not dead.is_set():
            chunk = None
            try:
                chunk = INPUT_QUEUE.get(timeout=0.25)
            except queue.Empty:
                pass
            if chunk is not None:
                source_start = None
                source_end = None
                captured_at = None
                if isinstance(chunk, tuple) and len(chunk) == 4:
                    chunk, source_start, source_end, captured_at = chunk
                input_age_allowance = AUDIO_INPUT_MAX_AGE_SECONDS
                if resume:
                    input_age_allowance = max(
                        input_age_allowance,
                        min(PLAYBACK_DELAY_SECONDS,
                            steady_time() - setup_started_at + .5),
                    )
                if (captured_at is not None and
                        steady_time() - captured_at > input_age_allowance):
                    # Never translate historical speech against the current
                    # picture; the next fresh frame is worth more.
                    INPUT_STALE_DROPS[0] += 1
                    continue
                if flow.get("first_input_captured_at") is None and captured_at is not None:
                    flow["first_input_captured_at"] = captured_at
                    flow["first_input_sent_at"] = steady_time()
                encoded = base64.b64encode(chunk)
                if not isinstance(encoded, str):
                    encoded = encoded.decode("ascii")
                if not reported_input_send:
                    log("Source PCM is streaming to Gemini audio engine")
                    set_state("streaming", profile=profile, attempt=attempt)
                    reported_input_send = True
                ws.send_json({
                    "realtimeInput": {
                        "audio": {
                            "mimeType": "audio/pcm;rate=16000",
                            "data": encoded
                        }
                    }
                })
                dump_pcm('src16', chunk)
                flow["input_bytes"] += len(chunk)
                if source_end is not None:
                    sent_at = steady_time()
                    flow["input_source_start"] = source_start
                    flow["input_source_end"] = source_end
                    flow["input_captured_at"] = captured_at
                    flow["input_sent_at"] = sent_at
                    if flow.get("first_input_captured_at") is None:
                        flow["first_input_captured_at"] = captured_at
                        flow["first_input_sent_at"] = sent_at
            now = steady_time()
            if now - flow["last_log"] >= FLOW_LOG_INTERVAL_SECONDS:
                log(
                    "Audio flow: source=%.1fs translated=%.1fs "
                    "buffered=%.2fs catchup=%.2fs drift=%.1fs udp_drops=%d "
                    "stale_dropped=%d queue_full_dropped=%d "
                    "disconnected_dropped=%d session=%.1fs" % (
                        flow["input_bytes"] / 32000.0,
                        flow["output_bytes"] / 48000.0,
                        OUTPUT.size() / 48000.0,
                        OUTPUT.dropped_size() / 48000.0,
                        DRIFT_SECONDS[0], OUTPUT_UDP_DROPS[0],
                        INPUT_STALE_DROPS[0], INPUT_QUEUE_FULL_DROPS[0],
                        INPUT_DISCONNECTED_DROPS[0], now - flow["started"],
                    )
                )
                flow["last_log"] = now
                log("Adaptive playout: %s" % json.dumps(PLAYOUT_METRICS[0], sort_keys=True))
        if not STOP.is_set():
            if failure:
                if flow.get("go_away_seen"):
                    raise GoAwayError(
                        "planned rotation transport end: %s" % failure[0]
                    )
                raise failure[0]
            raise IOError("Connection ended")
    finally:
        ws.close()
        if 'dead' in locals():
            dead.set()
        if 'thread' in locals():
            thread.join(0.4)
        if CURRENT_WS[0] is ws:
            CURRENT_WS[0] = None


def stop_handler(signum, frame):
    STOP.set()
    ws = CURRENT_WS[0]
    if ws is not None:
        ws.close()


def main():
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        api_key = read_api_key()
    except Exception as error:
        log("Cannot read %s: %s" % (KEY_FILE, error))
        return 2

    set_state("starting")
    if not CONNECTION_PROBE_MODE:
        open_dump_dir()
    worker_threads = []
    targets = [] if CONNECTION_PROBE_MODE else [stdin_reader, pcm_writer]
    for target in targets:
        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        worker_threads.append(thread)

    if not CONNECTION_PROBE_MODE:
        set_state("waiting_input")
        while not STOP.is_set() and not INPUT_READY.wait(0.25):
            pass
        if STOP.is_set():
            set_state("stopped")
            return 0
        log("Meaningful live channel audio detected; audio Gemini may start")

    backoff = 2
    attempt = 0
    reconnect_detail = None
    resume = False
    while not STOP.is_set():
        attempt += 1
        profile = "official"
        result = {"ready": False}
        try:
            connect_and_stream(
                api_key, profile, attempt, result, reconnect_detail,
                resume=resume,
            )
            backoff = 2
            reconnect_detail = None
        except Exception as error:
            if STOP.is_set():
                break
            healthy_session = result.get("ready")
            fast_reconnect = healthy_session and should_fast_reconnect(error)
            if fast_reconnect:
                backoff = 2
            detail = sanitize_detail(error)
            error_kind = getattr(error, "error_kind", "")
            if error_kind == "edge_block":
                report_edge_block()
            reconnect_detail = detail
            resume = bool(fast_reconnect)
            if fast_reconnect:
                log("Healthy session transport ended; preserving buffered "
                    "translated audio across fast reconnect")
            else:
                TRANSLATED_OUTPUT_STARTED.clear()
                OUTPUT.clear()
                FIRST_TRANSLATED_AT[0] = None
                FIRST_TRANSLATED_SOURCE_ANCHOR[0] = None
                OUTPUT_RESET_TOKEN[0] += 1
            delay = (HEALTHY_RECONNECT_DELAY_SECONDS if fast_reconnect else backoff)
            set_state("retrying", profile=profile, attempt=attempt, detail=detail,
                      error_type=error_kind)
            log("Audio connection failed (profile=%s); retrying in %.2fs: %s" %
                (profile, delay, detail))
            STOP.wait(delay)
            if not fast_reconnect:
                backoff = min(backoff * 2, 30)
    STOP.set()
    for thread in worker_threads:
        try:
            thread.join(0.4)
        except Exception:
            pass
    if not CONNECTION_PROBE_MODE:
        set_input_state("stopped")
    set_state("stopped")
    log("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
