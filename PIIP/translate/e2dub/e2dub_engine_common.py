#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function


class CapturePlan(object):
    def __init__(self, capture_args, bridge_args=None, helper_matroska=False):
        self.capture_args = capture_args
        self.bridge_args = bridge_args
        self.helper_matroska = bool(helper_matroska)


def build_capture_plan(ffmpeg_path, capture_input, audio_stream, backend,
                       mini_ts=False):
    """Build the platform-specific source-audio capture chain.

    Both engines read the same active DVB audio PID, but they own independent
    capture processes. This function contains no Enigma2 or mode state.

    Set ``mini_ts`` when the input is the passive DVB tap rather than a full
    service transport stream.
    """
    mode = backend.get("mode")
    if mini_ts:
        # The tap forwards PAT, PMT and one audio PID only, but that PAT still
        # advertises every other service on the transponder.  -scan_all_pmts
        # would therefore block waiting for PMTs this filtered stream never
        # carries, and a 1 MB probe needs roughly a minute to fill at
        # audio-only bitrates.  Both outlast the source-PCM watchdog, so probe
        # small and skip the scan, matching the proven DreamOS passive path.
        probe = ["-probesize", "262144", "-analyzeduration", "500000"]
    else:
        probe = ["-probesize", "1000000", "-analyzeduration", "1000000",
                 "-scan_all_pmts", "1"]
    args = [
        ffmpeg_path, "-nostdin", "-hide_banner",
        "-loglevel", "fatal", "-thread_queue_size", "128",
    ]
    args.extend(probe)
    args.extend([
        "-f", "mpegts", "-i", capture_input,
        "-map", audio_stream, "-vn", "-sn", "-dn",
    ])
    bridge = None
    matroska = False
    if mode == "ffmpeg-matroska-pcm":
        args.extend([
            "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
            "-cluster_time_limit", "100", "-cluster_size_limit", "32768",
            "-flush_packets", "1", "-f", "matroska", "pipe:1",
        ])
        matroska = True
    elif mode in ("ffmpeg-raw-pcm", "dreamos-raw-pcm"):
        args.extend([
            "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
            "-f", "s16le", "pipe:1",
        ])
    elif mode == "ffmpeg-aac-gstreamer-pcm":
        args.extend([
            "-c:a", "aac", "-b:a", "64k", "-ar", "48000", "-ac", "1",
            "-flush_packets", "1", "-f", "adts", "pipe:1",
        ])
        bridge = [
            backend["gst_launch"], "-q",
            "fdsrc", "fd=0", "!", "aacparse", "!",
            backend["gst_decoder"], "!", "audioconvert", "!",
            "audioresample", "!",
            "audio/x-raw,format=S16LE,rate=16000,channels=1,layout=interleaved",
            "!", "fdsink", "fd=1", "sync=false",
        ]
    else:
        raise RuntimeError("Unsupported audio capture backend: %s" % mode)
    return CapturePlan(args, bridge, matroska)


class EngineProcesses(object):
    """Process ownership shared structurally, never behaviorally."""
    def __init__(self):
        self.capture_process = None
        # Optional passive DVB tap feeding capture_process, used where
        # streamproxy would otherwise demand HTTP authentication.
        self.capture_tap_process = None
        self.capture_decode_process = None
        self.helper_process = None
        self.relay_process = None
        self.playback_process = None
        self.http_process = None

    def values(self):
        return (
            self.capture_process, self.capture_tap_process,
            self.capture_decode_process,
            self.helper_process, self.relay_process,
            self.playback_process, self.http_process,
        )

    def clear(self):
        self.capture_process = None
        self.capture_tap_process = None
        self.capture_decode_process = None
        self.helper_process = None
        self.relay_process = None
        self.playback_process = None
        self.http_process = None
