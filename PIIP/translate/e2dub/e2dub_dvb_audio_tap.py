#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function

"""Passive DVB transport taps for E2Dub.

Subtitle capture uses PAT + PMT + selected audio. OE-Alliance Audio mode can
also request an ordered PAT/PMT/video/audio/PCR service TS from the DVB DVR
node, avoiding Enigma2 streamproxy authentication entirely. All filters are
read-only copies from the already tuned frontend; playback and Timeshift are
never touched.
"""

import argparse
import errno
import fcntl
import glob
import os
import select
import signal
import struct
import sys
import time


DMX_IN_FRONTEND = 0
DMX_OUT_TS_TAP = 2
DMX_OUT_TSDEMUX_TAP = 3
DMX_PES_OTHER = 20
DMX_IMMEDIATE_START = 4
DMX_SET_PES_FILTER = 0x40146F2C
TS_PACKET = 188
READ_PACKETS = 128
PROBE_SECONDS = 1.50
STOP = [False]


def _stderr(message):
    try:
        sys.stderr.write("[dvb-tap] %s\n" % message)
        sys.stderr.flush()
    except Exception:
        pass


def _stop(_signum, _frame):
    STOP[0] = True


def _demux_order(path):
    """Sort /dev/dvb/adapterA/demuxB numerically, not lexicographically."""
    directory, base = os.path.split(path)
    adapter = 0
    for chunk in os.path.basename(directory).split("adapter")[-1:]:
        try:
            adapter = int(chunk)
        except ValueError:
            adapter = 0
    try:
        index = int(base[len("demux"):])
    except ValueError:
        index = 1 << 30
    return (adapter, index)


def _candidate_demuxes(explicit=None):
    if explicit:
        return [explicit]
    paths = []
    preferred = "/dev/dvb/adapter0/demux0"
    if os.path.exists(preferred):
        paths.append(preferred)
    # Receivers expose demux0..demux16, so a plain lexicographic sort walks
    # demux0, demux1, demux10, demux11, ... and lands on a high, unrelated
    # demux as soon as the first two are busy.  Order numerically instead.
    for path in sorted(glob.glob("/dev/dvb/adapter*/demux*"), key=_demux_order):
        if path not in paths:
            paths.append(path)
    return paths


def _pes_params(pid, output):
    return struct.pack(
        "=H2xIIII", int(pid), DMX_IN_FRONTEND, int(output),
        DMX_PES_OTHER, DMX_IMMEDIATE_START,
    )


def _byte_value(value):
    return value if isinstance(value, int) else ord(value)


def _packet_pids(data):
    """Return DVB PIDs seen in an arbitrary MPEG-TS byte block."""
    found = set()
    if not data or len(data) < TS_PACKET:
        return found
    # FFmpeg can resynchronise, and so can this probe. Search the first packet
    # boundary then walk in exact 188-byte steps.
    start = None
    limit = min(TS_PACKET, max(0, len(data) - 2))
    for offset in range(limit):
        if _byte_value(data[offset]) != 0x47:
            continue
        if offset + TS_PACKET < len(data) and _byte_value(data[offset + TS_PACKET]) != 0x47:
            continue
        start = offset
        break
    if start is None:
        return found
    pos = start
    while pos + 3 <= len(data):
        if _byte_value(data[pos]) != 0x47:
            break
        first = _byte_value(data[pos + 1])
        second = _byte_value(data[pos + 2])
        found.add(((first & 0x1F) << 8) | second)
        pos += TS_PACKET
    return found


def _looks_like_ts(data, pid):
    return int(pid) in _packet_pids(data)


def _dvr_candidates(demux_path):
    directory = os.path.dirname(demux_path)
    base = os.path.basename(demux_path)
    suffix = base[len("demux"):] if base.startswith("demux") else "0"
    paths = [os.path.join(directory, "dvr" + suffix),
             os.path.join(directory, "dvr0")]
    result = []
    for path in paths:
        if path not in result and os.path.exists(path):
            result.append(path)
    return result


def _open_filter(path, pid, output):
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, DMX_SET_PES_FILTER, _pes_params(pid, output))
        return fd
    except Exception:
        os.close(fd)
        raise


def _probe_direct(filters, required_pids):
    deadline = time.time() + PROBE_SECONDS
    first_chunks = []
    seen = set()
    fds = list(filters.values())
    while time.time() < deadline and not STOP[0]:
        ready, _write, _error = select.select(fds, [], [], 0.15)
        for fd in ready:
            try:
                data = os.read(fd, TS_PACKET * 32)
            except OSError as error:
                if error.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise
            if not data:
                continue
            first_chunks.append(data)
            seen.update(_packet_pids(data))
        if required_pids.issubset(seen):
            return first_chunks
    return []


def _open_direct_bundle(audio_pid, pmt_pid, path):
    pids = []
    for pid in (0, int(pmt_pid), int(audio_pid)):
        if pid not in pids:
            pids.append(pid)
    filters = {}
    try:
        for pid in pids:
            filters[pid] = _open_filter(path, pid, DMX_OUT_TSDEMUX_TAP)
        first = _probe_direct(filters, set(pids))
        if first:
            return filters, None, first, "tsdemux-mini-ts"
    except Exception:
        # Same leak as _open_dvr_pids had: a bare re-raise skipped the cleanup
        # below, leaving demux filters open and that node busy for every later
        # attempt.
        for fd in filters.values():
            try:
                os.close(fd)
            except Exception:
                pass
        raise
    for fd in filters.values():
        try:
            os.close(fd)
        except Exception:
            pass
    return None


def _probe_dvr(read_fd, required_pids):
    deadline = time.time() + PROBE_SECONDS
    chunks = []
    seen = set()
    while time.time() < deadline and not STOP[0]:
        ready, _write, _error = select.select([read_fd], [], [], 0.15)
        if not ready:
            continue
        try:
            data = os.read(read_fd, TS_PACKET * 64)
        except OSError as error:
            if error.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                continue
            raise
        if not data:
            continue
        chunks.append(data)
        seen.update(_packet_pids(data))
        if required_pids.issubset(seen):
            return chunks
    return []


def _unique_pids(values):
    result = []
    for value in values:
        if value is None:
            continue
        pid = int(value)
        if 0 <= pid < 8192 and pid not in result:
            result.append(pid)
    return result


def _open_dvr_pids(pids, path, label):
    """Open one ordered DVR stream containing only selected service PIDs.

    Unlike TSDEMUX_TAP, DMX_OUT_TS_TAP feeds one /dev/dvb/.../dvr device, so
    packet order is preserved across PAT/PMT/video/audio/PCR.  This is required
    for smooth A/V playback and is the transport used by OE-Alliance Audio mode.
    """
    pids = _unique_pids(pids)
    filters = {}
    read_fd = None
    try:
        for pid in pids:
            filters[pid] = _open_filter(path, pid, DMX_OUT_TS_TAP)
        for dvr_path in _dvr_candidates(path):
            try:
                read_fd = os.open(dvr_path, os.O_RDONLY | os.O_NONBLOCK)
                first = _probe_dvr(read_fd, set(pids))
                if first:
                    return filters, read_fd, first, "%s:%s" % (label, dvr_path)
            except Exception:
                pass
            if read_fd is not None:
                try:
                    os.close(read_fd)
                except Exception:
                    pass
                read_fd = None
    except Exception:
        # Never leak demux fds. A leaked filter keeps that demux node busy, so
        # the next attempt silently lands on an unrelated demux (demux11, ...)
        # instead of the adapter's real service demux.
        for fd in filters.values():
            try:
                os.close(fd)
            except Exception:
                pass
        raise
    for fd in filters.values():
        try:
            os.close(fd)
        except Exception:
            pass
    return None


def _open_dvr_bundle(audio_pid, pmt_pid, path):
    return _open_dvr_pids(
        (0, int(pmt_pid), int(audio_pid)), path, "ts-tap-mini-ts"
    )


def open_service_ts(audio_pid, pmt_pid, video_pid, pcr_pid=None, explicit=None):
    """Open a direct, ordered DVB service TS for OE-Alliance playback.

    The returned DVR stream contains only the active service's PAT, PMT, video,
    selected audio and PCR PID.  It never opens Enigma2 streamproxy and never
    changes tuner, playback, Timeshift or CAM state.
    """
    required = _unique_pids((0, pmt_pid, video_pid, audio_pid, pcr_pid))
    if not (0 in required and int(pmt_pid) in required and
            int(video_pid) in required and int(audio_pid) in required):
        raise RuntimeError("invalid DVB service PID set")
    errors = []
    for path in _candidate_demuxes(explicit):
        try:
            result = _open_dvr_pids(required, path, "ts-tap-service")
            if result is not None:
                filters, read_fd, first, mode = result
                _stderr(
                    "direct service TS attached to %s via %s "
                    "(PAT=0x0 PMT=0x%X VIDEO=0x%X AUDIO=0x%X PCR=0x%X)" %
                    (path, mode, int(pmt_pid), int(video_pid), int(audio_pid),
                     int(pcr_pid if pcr_pid is not None else video_pid))
                )
                return filters, read_fd, path, first, mode
            errors.append("%s:no-data" % path)
        except Exception as error:
            errors.append("%s:%s" % (path, error))
    raise RuntimeError(
        "no readable direct DVB service TS for PMT 0x%X video 0x%X audio 0x%X (%s)" %
        (int(pmt_pid), int(video_pid), int(audio_pid),
         "; ".join(errors[-8:]) or "no demux devices")
    )


def close_service_ts(filters, read_fd):
    if read_fd is not None:
        try:
            os.close(read_fd)
        except Exception:
            pass
    for fd in (filters or {}).values():
        try:
            os.close(fd)
        except Exception:
            pass


def _open_working_demux(audio_pid, pmt_pid, explicit=None):
    errors = []
    started = time.time()
    # Receivers expose ~17 demux nodes and each opener probes for PROBE_SECONDS,
    # so an exhaustive scan can outlast the source-PCM watchdog and be killed
    # before it ever reports success or failure.  Announce liveness up front and
    # try the ordered DVR/TS_TAP transport first: that is the mechanism the
    # audio path already attaches with on real VU+ hardware, while TSDEMUX_TAP
    # is the fallback.
    _stderr("passive mini-TS attach starting (PMT=0x%X AUDIO=0x%X)" %
            (int(pmt_pid), int(audio_pid)))
    for path in _candidate_demuxes(explicit):
        for opener in (_open_dvr_bundle, _open_direct_bundle):
            try:
                result = opener(audio_pid, pmt_pid, path)
                if result is not None:
                    filters, read_fd, first, mode = result
                    _stderr(
                        "passive mini-TS attached to %s via %s in %.1fs "
                        "(PAT=0x0 PMT=0x%X AUDIO=0x%X)" %
                        (path, mode, time.time() - started, pmt_pid, audio_pid)
                    )
                    return filters, read_fd, path, first, mode
                errors.append("%s:%s:no-data" % (path, opener.__name__))
            except Exception as error:
                errors.append("%s:%s:%s" % (path, opener.__name__, error))
    raise RuntimeError(
        "no readable DVB mini-TS for PMT 0x%X audio 0x%X after %.1fs (%s)" %
        (pmt_pid, audio_pid, time.time() - started,
         "; ".join(errors[-8:]) or "no demux devices")
    )


def _write_all(data):
    view = data
    while view and not STOP[0]:
        try:
            written = os.write(1, view)
        except OSError as error:
            if error.errno == errno.EINTR:
                continue
            if error.errno == errno.EPIPE:
                STOP[0] = True
                return False
            raise
        if written <= 0:
            return False
        view = view[written:]
    return True


def _run_direct(filters):
    fds = list(filters.values())
    while not STOP[0]:
        ready, _write, _error = select.select(fds, [], [], 0.5)
        for fd in ready:
            try:
                data = os.read(fd, TS_PACKET * READ_PACKETS)
            except OSError as error:
                if error.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise
            if data and not _write_all(data):
                return


def _run_dvr(read_fd):
    while not STOP[0]:
        ready, _write, _error = select.select([read_fd], [], [], 0.5)
        if not ready:
            continue
        try:
            data = os.read(read_fd, TS_PACKET * READ_PACKETS)
        except OSError as error:
            if error.errno in (errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                continue
            raise
        if data and not _write_all(data):
            return


def run(audio_pid, pmt_pid, demux=None, video_pid=None, pcr_pid=None):
    filters = {}
    read_fd = None
    try:
        if video_pid is not None:
            # Prefer the ordered service TS that OE-Alliance Audio mode already
            # attaches with on real hardware: same demux node, same transport,
            # sub-second attach.  The audio-only mini-TS scan can outlast the
            # source-PCM watchdog, which leaves subtitles with no PCM at all.
            filters, read_fd, path, first, mode = open_service_ts(
                audio_pid, pmt_pid, video_pid, pcr_pid, demux
            )
        else:
            filters, read_fd, path, first, mode = _open_working_demux(
                audio_pid, pmt_pid, demux
            )
        for chunk in first:
            if chunk and not _write_all(chunk):
                return 0
        if read_fd is None:
            _run_direct(filters)
        else:
            _run_dvr(read_fd)
        _stderr("passive mini-TS capture stopped: %s (%s)" % (path, mode))
        return 0
    finally:
        if read_fd is not None:
            try:
                os.close(read_fd)
            except Exception:
                pass
        for fd in filters.values():
            try:
                os.close(fd)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--pmt-pid", required=True,
                        type=lambda value: int(value, 0))
    parser.add_argument("--demux")
    parser.add_argument("--video-pid", type=lambda value: int(value, 0))
    parser.add_argument("--pcr-pid", type=lambda value: int(value, 0))
    args = parser.parse_args()
    for label, pid in (("audio", args.pid), ("PMT", args.pmt_pid)):
        if pid <= 0 or pid >= 8192:
            raise SystemExit("invalid DVB %s PID" % label)
    if args.pid == args.pmt_pid:
        raise SystemExit("audio PID and PMT PID cannot be identical")
    for name in ("SIGTERM", "SIGINT"):
        try:
            signal.signal(getattr(signal, name), _stop)
        except Exception:
            pass
    try:
        video_pid = args.video_pid
        if video_pid is not None and not (0 < video_pid < 8192):
            video_pid = None
        pcr_pid = args.pcr_pid
        if pcr_pid is not None and not (0 <= pcr_pid < 8192):
            pcr_pid = None
        return run(args.pid, args.pmt_pid, args.demux, video_pid, pcr_pid)
    except Exception as error:
        _stderr("ERROR: %s" % error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
