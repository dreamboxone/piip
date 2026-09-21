#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function

import collections
import errno
import gc
import json
import os
import select
import signal
import socket
import sys
import time

try:
    import fcntl
except ImportError:  # Imported by Windows unit tests; runtime is Linux.
    fcntl = None

try:
    from urlparse import urlsplit
except ImportError:
    from urllib.parse import urlsplit



try:
    from .e2dub_dvb_audio_tap import open_service_ts, close_service_ts
except (ImportError, ValueError):
    try:
        from e2dub_dvb_audio_tap import open_service_ts, close_service_ts
    except ImportError:
        open_service_ts = None
        close_service_ts = None

TS_DATAGRAM_BYTES = 1316       # seven 188-byte MPEG-TS packets
# Eight datagrams keep receiver syscall/scheduler load low while remaining a
# small 10.5 KiB read.  The former two-datagram reads did not reduce any drops
# on the receiver (all counters stayed at zero), but raised pipeline CPU from
# roughly 50% to 60% and made hardware-decoder delivery less regular.
READ_BYTES = TS_DATAGRAM_BYTES * 8
MAX_READ_BYTES = TS_DATAGRAM_BYTES * 8
MAX_DELAY_BYTES = 64 * 1024 * 1024
# Allows FFmpeg to probe PAT/PMT and codec headers without dropping delayed TS.
MAX_PENDING_BYTES = 8 * 1024 * 1024
LOG_INTERVAL_SECONDS = 30
STOP = [False]

# DreamOS ships Python 2.7.13 with a known-fragile cyclic collector. This
# standalone relay is single-threaded and holds no application object cycles;
# reference counting is sufficient and avoids gcmodule update_refs aborts seen
# under sustained 15+ Mbit/s bytearray churn on Dreambox Two.
if sys.version_info[0] < 3:
    try:
        gc.disable()
    except Exception:
        pass


def steady_time():
    """Monotonic clock for delay and pacing; wall time is logging only."""
    callback = getattr(time, "monotonic", None)
    if callback is not None:
        return float(callback())
    return float(os.times()[4])


def error_number(error):
    """Return an errno from either an OSError or a Python 2 socket.error."""
    number = getattr(error, "errno", None)
    if number is None:
        # Python 2 socket.error carried (errno, message) in args.  Anything
        # else - a ValueError's message, say - must not be read as an errno.
        try:
            candidate = error.args[0]
        except Exception:
            candidate = None
        number = candidate if isinstance(candidate, int) else None
    return number


def eintr_retry(function, *arguments):
    """Repeat a blocking call that a signal interrupted.

    The receivers run Python 2.7, which predates PEP 475, so every blocking
    syscall surfaces EINTR to the caller instead of resuming by itself.  A
    signal - a spawned worker exiting, a timer firing - is not a failure, but
    left unhandled it killed the relay outright and took the whole pipeline
    down: a receiver log showed three consecutive failed starts, each ending
    with "Relay failed: [Errno 4] Interrupted system call".
    """
    while True:
        try:
            return function(*arguments)
        except (OSError, IOError, socket.error) as error:
            if error_number(error) != errno.EINTR:
                raise


def to_bytes(value):
    if isinstance(value, bytearray):
        if sys.version_info[0] >= 3:
            return bytes(value)
        return value.decode("latin-1").encode("latin-1")
    return value


def log(message):
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        sys.stderr.write("%s [relay] %s\n" % (stamp, message))
        sys.stderr.flush()
    except Exception:
        pass


def set_state(path, state, **values):
    temporary = "%s.%s" % (path, os.getpid())
    try:
        payload = {"state": state, "updated": int(time.time())}
        payload.update(values)
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with open(temporary, "wb") as handle:
            handle.write(raw.encode("utf-8"))
        os.rename(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except Exception:
            pass


class DelayBuffer(object):
    """Monotonic delay line with a hard RAM ceiling suitable for 4K TS."""

    def __init__(self, delay_seconds, maximum_bytes=MAX_DELAY_BYTES):
        self.delay_seconds = float(delay_seconds)
        self.maximum_bytes = int(maximum_bytes)
        self.items = collections.deque()
        self.bytes = 0
        self.dropped_bytes = 0

    def append(self, now, data):
        if not data:
            return
        self.items.append((now + self.delay_seconds, data))
        self.bytes += len(data)
        while self.bytes > self.maximum_bytes and self.items:
            _release, old = self.items.popleft()
            self.bytes -= len(old)
            self.dropped_bytes += len(old)

    def pop_due(self, now):
        due = []
        while self.items and self.items[0][0] <= now:
            _release, data = self.items.popleft()
            self.bytes -= len(data)
            due.append(data)
        return due


def signal_handler(signum, frame):
    STOP[0] = True


def set_nonblocking(fd):
    if fcntl is None:
        raise RuntimeError("fcntl is required on the receiver")
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def connect_streamproxy(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Only an HTTP streamproxy URL is supported")
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    addresses = socket.getaddrinfo(
        parsed.hostname, port, socket.AF_INET, socket.SOCK_STREAM
    )
    last_error = None
    for family, socktype, proto, _canonname, address in addresses:
        stream = socket.socket(family, socktype, proto)
        stream.settimeout(10)
        try:
            stream.connect(address)
            request = (
                "GET %s HTTP/1.0\r\nHost: %s\r\n"
                "Connection: close\r\nUser-Agent: e2dub-relay/1.2.42\r\n\r\n"
            ) % (path, parsed.hostname)
            eintr_retry(stream.sendall, request.encode("ascii"))
            header = bytearray()
            marker = b"\r\n\r\n"
            while header.find(marker) < 0:
                chunk = eintr_retry(stream.recv, 1024)
                if not chunk:
                    raise IOError("streamproxy closed during HTTP headers")
                header.extend(bytearray(chunk))
                if len(header) > 32768:
                    raise IOError("oversized streamproxy response")
            end = header.find(marker) + len(marker)
            raw_header = to_bytes(header[:end])
            text = raw_header.decode("iso-8859-1")
            status = text.split("\r\n", 1)[0]
            if " 200 " not in status:
                code = 0
                try:
                    fields = status.split()
                    code = int(fields[1]) if len(fields) > 1 else 0
                except Exception:
                    code = 0
                if code in (401, 403):
                    raise IOError(
                        "streamproxy authorization required: %s" %
                        status[:120]
                    )
                raise IOError("streamproxy returned %s" % status[:120])
            stream.settimeout(0.02)
            return stream, to_bytes(header[end:])
        except Exception as error:
            last_error = error
            try:
                stream.close()
            except Exception:
                pass
    if last_error is not None:
        raise last_error
    raise IOError("No IPv4 streamproxy address")


class HttpSource(object):
    def __init__(self, stream):
        self.stream = stream

    def read(self, size):
        try:
            data = eintr_retry(self.stream.recv, size)
        except socket.timeout:
            return None
        if not data:
            raise IOError("streamproxy connection ended")
        return data

    def close(self):
        try:
            self.stream.close()
        except Exception:
            pass


class DvbSource(object):
    def __init__(self, filters, read_fd):
        self.filters = filters
        self.read_fd = read_fd

    def read(self, size):
        ready, _write, _error = eintr_retry(
            select.select, [self.read_fd], [], [], 0.02)
        if not ready:
            return None
        try:
            data = eintr_retry(os.read, self.read_fd, size)
        except OSError as error:
            if error.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                return None
            raise
        return data or None

    def close(self):
        if close_service_ts is not None:
            close_service_ts(self.filters, self.read_fd)
        self.filters = {}
        self.read_fd = None


def connect_dvb_service(audio_pid, pmt_pid, video_pid, pcr_pid):
    if open_service_ts is None:
        raise RuntimeError("direct DVB service tap is unavailable")
    filters, read_fd, path, first, mode = open_service_ts(
        int(audio_pid), int(pmt_pid), int(video_pid), int(pcr_pid)
    )
    initial = b"".join(first)
    log(
        "Direct DVB source ready: demux=%s mode=%s "
        "PMT=0x%X VIDEO=0x%X AUDIO=0x%X PCR=0x%X; streamproxy bypassed" %
        (path, mode, int(pmt_pid), int(video_pid), int(audio_pid), int(pcr_pid))
    )
    return DvbSource(filters, read_fd), initial


def open_input_source(source_url, dvb_pids=None):
    if dvb_pids is not None:
        try:
            source, initial = connect_dvb_service(*dvb_pids)
            return source, initial, "dvb-direct"
        except Exception as error:
            log("Direct DVB source unavailable; streamproxy fallback: %s" % error)
    stream, initial = connect_streamproxy(source_url)
    return HttpSource(stream), initial, "streamproxy"


def append_capped(pending, chunks, maximum=MAX_PENDING_BYTES):
    for chunk in chunks:
        pending.extend(bytearray(chunk))
    dropped = 0
    if len(pending) > maximum:
        dropped = len(pending) - maximum
        # MPEG-TS recovery is faster when the retained byte stream begins on
        # a packet boundary. The demuxer will find the next sync byte/IDR.
        dropped += (-dropped) % 188
        del pending[:dropped]
    return dropped


def send_live(udp, destination, pending):
    sent = 0
    dropped = 0
    while len(pending) >= TS_DATAGRAM_BYTES:
        packet = to_bytes(pending[:TS_DATAGRAM_BYTES])
        del pending[:TS_DATAGRAM_BYTES]
        try:
            eintr_retry(udp.sendto, packet, destination)
            sent += len(packet)
        except socket.error:
            dropped += len(packet)
    return sent, dropped


class StartupDelay(object):
    """Select a bounded delay once; never jump the running video timeline."""
    def __init__(self, minimum, started):
        self.minimum = float(minimum)
        # Keep enough translated PCM to bridge a planned Gemini session
        # rotation.  Receiver measurements show up to 5.5 s from the last
        # old-session frame to the first resumed frame.  The extra 6.0 s over
        # measured startup latency becomes a fixed A/V-aligned reserve.
        self.maximum = max(self.minimum, 12.0)
        self.started = started
        self.selected = None

    def update(self, now, audio_state):
        if self.selected is not None:
            return self.selected
        arrived = audio_state.get('audio_arrived_monotonic')
        source = audio_state.get('source_capture_anchor')
        if (isinstance(arrived, (int, float)) and isinstance(source, (int, float))
                and source >= self.started - .5 and self.started <= arrived <= now):
            self.selected = min(
                self.maximum,
                max(self.minimum, arrived - self.started + 6.0),
            )
        elif now - self.started >= self.maximum:
            self.selected = self.maximum
        return self.selected


def run(source_url, delay_seconds, live_port, state_file, dvb_pids=None,
        audio_startup_state=None):
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    set_nonblocking(1)
    source, initial, source_kind = open_input_source(source_url, dvb_pids)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setblocking(False)
    destination = ("127.0.0.1", int(live_port))
    delay = DelayBuffer(delay_seconds)
    live_pending = bytearray()
    output_pending = bytearray()
    received = 0
    live_drops = 0
    output_drops = 0
    started = steady_time()
    startup = StartupDelay(delay_seconds, started) if audio_startup_state else None
    last_startup_read = 0.0
    selected_delay = None if startup else delay_seconds
    last_log = started
    read_bytes = READ_BYTES
    ready = False
    set_state(
        state_file, "buffering", delay_ms=int(delay_seconds * 1000),
        source=source_kind,
    )
    log(
        "Synchronized RAM delay started (delay=%.2fs cap=%dMB source=%s)" %
        (delay_seconds, MAX_DELAY_BYTES // (1024 * 1024), source_kind)
    )
    incoming = initial
    try:
        while not STOP[0]:
            now = steady_time()
            if incoming:
                received += len(incoming)
                live_pending.extend(bytearray(incoming))
                _sent, dropped = send_live(udp, destination, live_pending)
                live_drops += dropped
                delay.append(now, incoming)
                incoming = b""

            if startup is not None and selected_delay is None and now - last_startup_read >= .1:
                last_startup_read = now
                try:
                    with open(audio_startup_state, 'r') as handle:
                        audio_state = json.load(handle)
                except Exception:
                    audio_state = {}
                selected_delay = startup.update(now, audio_state)
                if selected_delay is not None:
                    set_state(state_file, 'buffering', delay_ms=int(round(selected_delay * 1000)),
                              startup_locked=True, started_monotonic=started, source=source_kind)
                    log('Adaptive startup delay selected: %.3fs (frozen for this playback)' % selected_delay)
            # Entries retain their original timestamps; shifting the query
            # clock delays all source packets equally without dropping any.
            due = ([] if selected_delay is None else
                   delay.pop_due(now - (selected_delay - delay_seconds)))
            output_drops += append_capped(output_pending, due)
            if output_pending:
                try:
                    count = eintr_retry(
                        os.write, 1, to_bytes(output_pending))
                    if count:
                        del output_pending[:count]
                        if not ready:
                            ready = True
                            set_state(
                                state_file, "ready",
                                delay_ms=int(round(selected_delay * 1000)),
                                startup_locked=True, started_monotonic=started,
                                source=source_kind,
                            )
                            log("Delayed MPEG-TS output is ready")
                except OSError as error:
                    # EINTR is not a failure: a signal simply arrived during
                    # the write, and the remaining bytes are still queued for
                    # the next pass.  Treating it as fatal killed the relay
                    # ("Relay failed: [Errno 4] Interrupted system call") and
                    # took the whole pipeline down with it.
                    if error.errno not in (errno.EINTR, errno.EAGAIN,
                                           errno.EWOULDBLOCK):
                        raise

            if now - last_log >= LOG_INTERVAL_SECONDS:
                elapsed = max(0.001, now - started)
                mbps = received * 8.0 / elapsed / 1000000.0
                log(
                    "Delay health: bitrate=%.1fMbps ring=%.1fMB "
                    "pending=%.1fMB live_drops=%dKB output_drops=%dKB "
                    "cap_drops=%dKB read_packets=%d" % (
                        mbps, delay.bytes / 1048576.0,
                        len(output_pending) / 1048576.0,
                        live_drops // 1024, output_drops // 1024,
                        delay.dropped_bytes // 1024,
                        read_bytes // TS_DATAGRAM_BYTES,
                    )
                )
                set_state(
                    state_file, "ready" if ready else "buffering",
                    delay_ms=int(round((selected_delay or delay_seconds) * 1000)),
                    startup_locked=selected_delay is not None, started_monotonic=started,
                    bitrate_mbps=round(mbps, 1),
                    ring_kb=delay.bytes // 1024,
                    live_drops_kb=live_drops // 1024,
                    output_drops_kb=output_drops // 1024,
                    cap_drops_kb=delay.dropped_bytes // 1024,
                    source=source_kind,
                )
                last_log = now

            incoming = source.read(read_bytes)
            if incoming is None:
                incoming = b""
    finally:
        try:
            source.close()
        except Exception:
            pass
        try:
            udp.close()
        except Exception:
            pass
        set_state(state_file, "stopped")
    return 0


def main():
    arguments = list(sys.argv)
    audio_startup_state = None
    if '--audio-startup-state' in arguments:
        index = arguments.index('--audio-startup-state')
        if index + 1 >= len(arguments):
            return 2
        audio_startup_state = arguments[index + 1]
        del arguments[index:index + 2]
    if len(arguments) not in (5, 9):
        log(
            "usage: e2dub_relay.py SOURCE_URL DELAY_SECONDS LIVE_PORT STATE "
            "[AUDIO_PID PMT_PID VIDEO_PID PCR_PID]"
        )
        return 2
    dvb_pids = None
    if len(arguments) == 9:
        try:
            dvb_pids = tuple(int(value, 0) for value in arguments[5:9])
        except Exception:
            log("invalid direct DVB PID arguments")
            return 2
    try:
        return run(
            arguments[1], float(arguments[2]), int(arguments[3]), arguments[4],
            dvb_pids=dvb_pids, audio_startup_state=audio_startup_state,
        )
    except Exception as error:
        detail = str(error)[:240]
        lowered = detail.lower()
        error_type = (
            "stream_auth" if ("authorization required" in lowered or
                              " 401 " in lowered or " 403 " in lowered or
                              "forbidden" in lowered)
            else "stream_error"
        )
        try:
            if len(sys.argv) >= 5:
                set_state(
                    sys.argv[4], "error", error_type=error_type, detail=detail
                )
        except Exception:
            pass
        log("Relay failed: %s" % detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
