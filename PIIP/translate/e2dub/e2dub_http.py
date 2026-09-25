#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function

import collections
import errno
import json
import os
import select
import signal
import socket
import sys
import time

try:
    import fcntl
except ImportError:
    fcntl = None


TS_PACKET_BYTES = 188
# Bound each pipe read and socket write without changing the media clock.
# A 48 KiB application chunk and 256 KiB kernel buffer absorb normal FFmpeg
# scheduling variation without delaying media timestamps.  The old 11 KiB /
# 32 KiB combination repeatedly left DreamOS' hardware video queue empty.
HTTP_IO_BYTES = TS_PACKET_BYTES * 256
READ_BYTES = HTTP_IO_BYTES
MAX_PENDING_BYTES = 8 * 1024 * 1024
LOG_INTERVAL_SECONDS = 30
PACE_SELECT_SECONDS = 0.01
RATE_WINDOW_SECONDS = 0.50
MIN_RATE_BYTES_PER_SECOND = 32 * 1024
MAX_RATE_BYTES_PER_SECOND = 16 * 1024 * 1024
STOP = [False]


def steady_time():
    """Monotonic clock for transport pacing; wall time is logging only."""
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

    The receivers run Python 2.7, which predates PEP 475, so a signal makes a
    blocking syscall raise instead of resuming.  Unhandled, that killed this
    relay during startup and the plugin logged three failed attempts in a row.
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
        sys.stderr.write("%s [http] %s\n" % (stamp, message))
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


def signal_handler(signum, frame):
    STOP[0] = True


def set_nonblocking_fd(fd):
    if fcntl is None:
        raise RuntimeError("fcntl is required on the receiver")
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def close_client(client):
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def trim_pending(pending):
    if len(pending) <= MAX_PENDING_BYTES:
        return 0
    dropped = len(pending) - MAX_PENDING_BYTES
    dropped += (-dropped) % TS_PACKET_BYTES
    del pending[:dropped]
    return dropped


class InputRateEstimator(object):
    """Low-cost wall-clock estimator for the final remuxed TS bitrate."""

    def __init__(self):
        self.window_started = None
        self.window_bytes = 0
        self.rate = None

    def feed(self, now, count):
        if count <= 0:
            return self.rate
        if self.window_started is None:
            self.window_started = float(now)
        self.window_bytes += int(count)
        elapsed = float(now) - self.window_started
        if elapsed < RATE_WINDOW_SECONDS:
            return self.rate
        sample = self.window_bytes / max(0.001, elapsed)
        if (MIN_RATE_BYTES_PER_SECOND <= sample <=
                MAX_RATE_BYTES_PER_SECOND):
            if self.rate is None:
                self.rate = sample
            else:
                # Smooth half-second streamproxy/FFmpeg bursts without making
                # the pacer slow to follow a real channel bitrate change.
                self.rate = self.rate * 0.75 + sample * 0.25
        self.window_started = float(now)
        self.window_bytes = 0
        return self.rate


class TokenPacer(object):
    """Deliver TS at its measured source rate instead of in pipe bursts."""

    def __init__(self):
        self.rate = None
        self.tokens = 0.0
        self.updated = None

    def set_rate(self, now, rate):
        self._refill(now)
        if rate is not None:
            self.rate = float(rate)

    def reset_client(self, now):
        # One normal HTTP chunk is safe inside the dedicated 250 ms native
        # subtitle reservoir and helps PAT/PMT discovery start immediately.
        self.updated = float(now)
        self.tokens = float(HTTP_IO_BYTES)

    def _refill(self, now):
        now = float(now)
        if self.updated is None:
            self.updated = now
            return
        elapsed = max(0.0, min(0.25, now - self.updated))
        self.updated = now
        if self.rate is None:
            return
        capacity = max(
            float(HTTP_IO_BYTES * 2), self.rate * 0.025
        )
        self.tokens = min(capacity, self.tokens + elapsed * self.rate)

    def budget(self, now, pending_bytes):
        pending_bytes = int(pending_bytes)
        if pending_bytes <= 0:
            return 0
        if self.rate is None:
            return min(pending_bytes, HTTP_IO_BYTES)
        self._refill(now)
        available = int(self.tokens)
        if available < TS_PACKET_BYTES:
            return 0
        return min(pending_bytes, HTTP_IO_BYTES, available)

    def consume(self, count):
        if self.rate is not None and count > 0:
            self.tokens = max(0.0, self.tokens - int(count))


class PcrPacer(object):
    """Release complete TS packets against the muxed stream's PCR clock."""

    PCR_WRAP = (1 << 33) * 300
    DECODER_LEAD_SECONDS = 0.35
    STARTUP_BUFFER_SECONDS = 4.0

    def __init__(self):
        self.seen = 0
        self.tail = bytearray()
        self.anchors = collections.deque()
        self.last_pcr = None
        self.last_pcr_wall = None
        self.last_pcr_offset = None
        self.media_seconds = 0.0
        self.wall_start = None

    def feed(self, now, chunk):
        data = self.tail + bytearray(chunk)
        base = self.seen - len(self.tail)
        index = 0
        while index + TS_PACKET_BYTES <= len(data):
            if data[index] != 0x47:
                index += 1
                continue
            if (index + TS_PACKET_BYTES < len(data) and
                    data[index + TS_PACKET_BYTES] != 0x47):
                index += 1
                continue
            control = (data[index + 3] >> 4) & 3
            if control in (2, 3) and data[index + 4] >= 7:
                flags = data[index + 5]
                if flags & 0x10:
                    p = data[index + 6:index + 12]
                    base_ticks = ((p[0] << 25) | (p[1] << 17) |
                                  (p[2] << 9) | (p[3] << 1) | (p[4] >> 7))
                    ticks = base_ticks * 300 + ((p[4] & 1) << 8) + p[5]
                    if self.last_pcr is not None:
                        delta = (ticks - self.last_pcr) % self.PCR_WRAP
                        if 0 < delta < 27000000:
                            self.media_seconds += delta / 27000000.0
                    else:
                        # HLS arrives in multi-second bursts. Keep four
                        # seconds of complete TS ahead of the decoder so the
                        # next segment can arrive before its frames are due.
                        self.wall_start = float(now) + self.STARTUP_BUFFER_SECONDS
                    self.last_pcr = ticks
                    self.last_pcr_wall = float(now)
                    self.last_pcr_offset = base + index
                    self.anchors.append((base + index,
                                         self.media_seconds))
            index += TS_PACKET_BYTES
        self.seen += len(chunk)
        self.tail = data[index:]

    def budget(self, now, pending_bytes):
        if not pending_bytes:
            return 0
        if (self.last_pcr_offset is not None and
                self.seen - self.last_pcr_offset > HTTP_IO_BYTES * 4):
            # Fall back only if data keeps arriving without PCR. HLS pauses
            # between segments are not evidence of a missing PCR clock.
            return min(pending_bytes, HTTP_IO_BYTES)
        pending_start = self.seen - pending_bytes
        while len(self.anchors) > 2 and self.anchors[1][0] <= pending_start:
            self.anchors.popleft()
        if len(self.anchors) < 2:
            # The first PAT/PMT and PCR must reach the decoder promptly.
            if (self.anchors and self.seen > HTTP_IO_BYTES * 4):
                return min(pending_bytes, HTTP_IO_BYTES)
            allowed = ((self.anchors[0][0] + TS_PACKET_BYTES)
                       if self.anchors else HTTP_IO_BYTES)
            return min(pending_bytes, HTTP_IO_BYTES,
                       max(0, allowed - pending_start))
        target = max(0.0, float(now) - self.wall_start +
                     self.DECODER_LEAD_SECONDS)
        previous = self.anchors[0]
        allowed = previous[0]
        for following in list(self.anchors)[1:]:
            if following[1] <= target:
                allowed = following[0]
                previous = following
                continue
            span = following[1] - previous[1]
            if span > 0:
                fraction = max(0.0, min(1.0,
                                        (target - previous[1]) / span))
                allowed = previous[0] + int(
                    (following[0] - previous[0]) * fraction)
            break
        available = max(0, allowed - pending_start)
        return min(pending_bytes, HTTP_IO_BYTES,
                   (available // TS_PACKET_BYTES) * TS_PACKET_BYTES)


def run(port, state_file, pacing=False, pcr_pacing=False):
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    set_nonblocking_fd(0)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", int(port)))
    server.listen(2)
    server.setblocking(False)

    client = None
    request = bytearray()
    client_ready = False
    response = bytearray()
    pending = bytearray()
    media_ready = False
    total_input = 0
    total_sent = 0
    total_dropped = 0
    last_log = steady_time()
    estimator = InputRateEstimator()
    pacer = TokenPacer()
    pcr_pacer = PcrPacer() if pcr_pacing else None
    set_state(
        state_file, "listening", port=int(port), paced=bool(pacing or pcr_pacing)
    )
    log(
        "Bounded local MPEG-TS HTTP server is listening on port %d "
        "(paced=%s)" % (port, "pcr" if pcr_pacing else
                         "rate" if pacing else "no")
    )

    try:
        while not STOP[0]:
            readers = [0, server]
            if client is not None:
                readers.append(client)
            writers = []
            send_budget = (pcr_pacer.budget(steady_time(), len(pending))
                           if pcr_pacing else
                           pacer.budget(steady_time(), len(pending))
                           if pacing else len(pending))
            if client is not None and (response or send_budget > 0):
                writers.append(client)
            readable, writable, _exceptional = eintr_retry(
                select.select, readers, writers, [],
                PACE_SELECT_SECONDS if (pacing or pcr_pacing) else 0.05
            )

            if server in readable:
                new_client, _address = eintr_retry(server.accept)
                new_client.setblocking(False)
                try:
                    new_client.setsockopt(
                        socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024
                    )
                    new_client.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
                    )
                except Exception:
                    pass
                close_client(client)
                client = new_client
                request = bytearray()
                client_ready = False
                response = bytearray()
                pending = bytearray()
                if pcr_pacing:
                    pcr_pacer = PcrPacer()
                if pacing:
                    pacer.reset_client(steady_time())
                log("Native Enigma2 HTTP/TS client connected")

            if 0 in readable:
                try:
                    chunk = eintr_retry(os.read, 0, READ_BYTES)
                except OSError as error:
                    # A signal interrupting the read is not end of stream; the
                    # data is still there on the next pass.
                    if error.errno in (errno.EINTR, errno.EAGAIN,
                                       errno.EWOULDBLOCK):
                        chunk = None
                    else:
                        raise
                if chunk == b"":
                    raise IOError("MPEG-TS input pipe ended")
                if chunk:
                    measured_rate = estimator.feed(steady_time(), len(chunk))
                    if pacing:
                        pacer.set_rate(steady_time(), measured_rate)
                    total_input += len(chunk)
                    if not media_ready:
                        media_ready = True
                        set_state(
                            state_file, "ready", port=int(port),
                            paced=bool(pacing or pcr_pacing),
                        )
                        log("MPEG-TS media is ready")
                    # Before the HTTP request is complete, deliberately drain
                    # the producer instead of retaining stale startup media.
                    if client is not None and client_ready:
                        pending.extend(bytearray(chunk))
                        if pcr_pacing:
                            pcr_pacer.feed(steady_time(), chunk)
                        total_dropped += trim_pending(pending)

            if client is not None and client in readable:
                try:
                    incoming = eintr_retry(client.recv, 4096)
                    if not incoming:
                        raise IOError("local HTTP client disconnected")
                    if not client_ready:
                        request.extend(bytearray(incoming))
                        if request.find(b"\r\n\r\n") >= 0:
                            client_ready = True
                            response = bytearray(
                                b"HTTP/1.0 200 OK\r\n"
                                b"Content-Type: video/MP2T\r\n"
                                b"Cache-Control: no-cache\r\n"
                                b"Connection: close\r\n\r\n"
                            )
                            pending = bytearray()
                            set_state(
                                state_file, "ready", port=int(port),
                                client=True, pending_kb=0,
                                dropped_kb=total_dropped // 1024,
                                paced=bool(pacing or pcr_pacing),
                            )
                except (IOError, socket.error) as error:
                    if error_number(error) not in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                        close_client(client)
                        client = None
                        request = bytearray()
                        client_ready = False
                        response = bytearray()
                        pending = bytearray()
                        set_state(
                            state_file, "ready" if media_ready else "listening",
                            port=int(port), dropped_kb=total_dropped // 1024,
                            client=False, paced=bool(pacing or pcr_pacing),
                        )

            if client is not None and client in writable:
                try:
                    if response:
                        count = client.send(to_bytes(response))
                        if count:
                            del response[:count]
                    elif pending:
                        send_bytes = (pcr_pacer.budget(steady_time(), len(pending))
                                      if pcr_pacing else
                                      pacer.budget(steady_time(), len(pending))
                                      if pacing else min(len(pending), HTTP_IO_BYTES))
                        if send_bytes <= 0:
                            continue
                        count = client.send(to_bytes(pending[:send_bytes]))
                        if count:
                            del pending[:count]
                            total_sent += count
                            if pacing:
                                pacer.consume(count)
                except socket.error as error:
                    # EINTR only means the send was interrupted mid-syscall.
                    # Dropping the viewer's connection for that would stall
                    # playback for no reason; the bytes are still queued.
                    if error_number(error) not in (
                            errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                        close_client(client)
                        client = None
                        request = bytearray()
                        client_ready = False
                        response = bytearray()
                        pending = bytearray()
                        set_state(
                            state_file,
                            "ready" if media_ready else "listening",
                            port=int(port),
                            dropped_kb=total_dropped // 1024,
                            client=False, paced=bool(pacing or pcr_pacing),
                        )

            now = steady_time()
            if now - last_log >= LOG_INTERVAL_SECONDS:
                log(
                    "HTTP health: input=%.1fMB sent=%.1fMB pending=%.1fMB "
                    "dropped=%dKB client=%s paced=%s rate=%.1fMbps" %
                    (total_input / 1048576.0, total_sent / 1048576.0,
                     len(pending) / 1048576.0, total_dropped // 1024,
                     "yes" if client is not None else "no",
                    "pcr" if pcr_pacing else "rate" if pacing else "no",
                     (estimator.rate or 0.0) * 8.0 / 1000000.0)
                )
                set_state(
                    state_file, "ready" if media_ready else "listening",
                    port=int(port), pending_kb=len(pending) // 1024,
                    dropped_kb=total_dropped // 1024,
                    client=bool(client),
                    paced=bool(pacing or pcr_pacing),
                    pacing_mbps=round(
                        (estimator.rate or 0.0) * 8.0 / 1000000.0, 1
                    ),
                )
                last_log = now
    finally:
        close_client(client)
        try:
            server.close()
        except Exception:
            pass
        set_state(
            state_file, "stopped", port=int(port), paced=bool(pacing or pcr_pacing)
        )
    return 0


def main():
    if len(sys.argv) not in (3, 4):
        log("usage: e2dub_http.py PORT STATE_FILE [paced|pcr]")
        return 2
    try:
        pacing = len(sys.argv) == 4 and sys.argv[3] == "paced"
        pcr_pacing = len(sys.argv) == 4 and sys.argv[3] == "pcr"
        return run(int(sys.argv[1]), sys.argv[2], pacing=pacing,
                   pcr_pacing=pcr_pacing)
    except Exception as error:
        log("HTTP relay failed: %s" % str(error)[:240])
        return 1


if __name__ == "__main__":
    sys.exit(main())
