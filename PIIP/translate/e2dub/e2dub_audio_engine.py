#!/usr/bin/python
# -*- coding: utf-8 -*-
# E2Dub - live AI dubbing and subtitle translation for Enigma2.
# Copyright (c) 2026 Routekernel. All rights reserved.
# Proprietary software. Redistribution, modification or republication
# under another name is prohibited. See LICENSE. https://t.me/Routekernel1
from __future__ import print_function

import os
import subprocess


FFMPEG_DEBUG_MARKER = "/tmp/e2dub-ffmpeg-debug"


def ffmpeg_diagnostic_loglevel():
    """Return the playback FFmpeg log level for this session."""
    try:
        if os.path.exists(FFMPEG_DEBUG_MARKER):
            return "warning"
    except Exception:
        pass
    return "fatal"

try:
    from .e2dub_engine_common import EngineProcesses, build_capture_plan
except (ImportError, ValueError):
    from e2dub_engine_common import EngineProcesses, build_capture_plan


class AudioEngine(EngineProcesses):
    """Translated audio with a startup-selected, then fixed RAM A/V delay."""

    def __init__(self, runtime):
        EngineProcesses.__init__(self)
        self.runtime = runtime
        self.fixed_delay = 0.0

    def _playback_args(self, context):
        ffmpeg = context["ffmpeg_path"]
        is_oe = bool(context["is_oe_alliance"])
        audio_stream = context["audio_stream"]
        original_volume = int(context["original_volume"])
        # Playback stays silent by default: the 1 MB capped log must not
        # be flooded by routine FFmpeg chatter.  Creating the marker file
        # raises it for one diagnostic session -- it lives in tmpfs, so a
        # reboot always restores the quiet default.
        loglevel = ffmpeg_diagnostic_loglevel()
        args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", loglevel]
        if is_oe:
            args.extend([
                "-fflags", "+genpts+discardcorrupt",
                "-dts_delta_threshold", "1",
            ])
            # Restore the receiver-facing OE-Alliance graph that was used
            # before the dual-track redesign: delayed MPEG-TS is input 0 and
            # translated PCM is input 1.  This shape was proven on real Vu+
            # hardware and avoids asking Enigma2 to switch between two local
            # AAC tracks.
            source_audio_stream = audio_stream
            dub_audio_stream = "1:a:0"
            args.extend([
                "-thread_queue_size", "1024",
                "-probesize", "1000000", "-analyzeduration", "1000000",
                "-scan_all_pmts", "1", "-f", "mpegts", "-i", "pipe:0",
                "-thread_queue_size", "256", "-f", "s16le", "-ar", "24000",
                "-ac", "1", "-channel_layout", "mono", "-i",
                "udp://127.0.0.1:%d?fifo_size=128&overrun_nonfatal=1&buffer_size=32768" %
                int(context["dub_udp_port"]),
            ])
        else:
            # DreamOS keeps the redesigned socket-first graph so translated
            # PCM is already listening before the delayed source TS arrives.
            source_audio_stream = (
                "1:" + audio_stream[2:] if audio_stream.startswith("0:")
                else audio_stream
            )
            dub_audio_stream = "0:a:0"
            args.extend([
                "-copyts", "-start_at_zero", "-copytb", "1",
                "-fflags", "+discardcorrupt",
                "-thread_queue_size", "256", "-f", "s16le", "-ar", "24000",
                "-ac", "1", "-channel_layout", "mono", "-i",
                "udp://127.0.0.1:%d?fifo_size=512&overrun_nonfatal=1&buffer_size=262144" %
                int(context["dub_udp_port"]),
                # The relay follows source arrival time, but FFmpeg can still
                # drain each demux batch and emit a short MPEG-TS burst. The
                # DreamOS decoder visibly slows and races while absorbing
                # those bursts even when no packet is lost. -re uses the
                # source DTS/PCR timeline to prevent FFmpeg running ahead.
                "-re",
                "-thread_queue_size", "1024",
                "-probesize", "1000000", "-analyzeduration", "1000000",
                "-scan_all_pmts", "1", "-f", "mpegts", "-i", "pipe:0",
            ])

        original_level = original_volume / 100.0
        # The dub used to carry a fixed 1.35 gain.  amix halves both inputs and
        # the trailing volume=2.0 undoes that, so the dub reached 1.35x full
        # scale on its own: measured on a Dreambox One, 40% of output samples
        # clipped with programme-loud audio, which is heard as the dub
        # crackling.  It also meant the original could never match the dub no
        # matter what the viewer chose, so the volume setting felt dead.  Unity
        # gain keeps the viewer's chosen level meaningful; the limiter is a
        # safety net for the sum, not a loudness stage.
        mix_tail = "aresample=48000:async=1:first_pts=0,asetpts=N/SR/TB," \
                   "volume=2.0"
        if context.get("has_mix_limiter", False):
            mix_tail += ",alimiter=limit=0.95:attack=5:release=50"
        if is_oe:
            # One AAC track contains the configured original-audio level plus
            # the translated PCM.  When Gemini pauses after startup, amix can
            # continue with the original component without any Enigma2 track
            # selection or a second decoder track.
            audio_filter = (
                "[%s]aformat=sample_fmts=fltp:sample_rates=48000:"
                "channel_layouts=stereo,aresample=48000:async=1:first_pts=0,"
                "asetpts=N/SR/TB,volume=%.2f[original];"
                "[%s]aresample=48000:async=1:first_pts=0,"
                "asetpts=N/SR/TB,pan=stereo|c0=c0|c1=c0,volume=1.00[dub];"
                "[original][dub]amix=inputs=2:duration=first:"
                "dropout_transition=0,%s[mixed]"
            ) % (source_audio_stream, original_level, dub_audio_stream,
                 mix_tail)
            args.extend(["-filter_complex", audio_filter])
            args.extend(["-map", "0:v:0", "-map", "[mixed]"])
            args.extend(["-fps_mode", "passthrough"])
        else:
            # DreamOS keeps the dual-track fixed-timeline fallback: track 0 is
            # translated/mixed audio and track 1 is delayed 100% original.
            audio_filter = (
                "[%s]aformat=sample_fmts=fltp:sample_rates=48000:"
                "channel_layouts=stereo,aresample=48000:async=1:first_pts=0,"
                "asetpts=N/SR/TB,asplit=2[original_base][original_full];"
                "[original_base]volume=%.2f[original];"
                "[original_full]anull[fallback];"
                "[%s]aresample=48000:async=1:first_pts=0,"
                "asetpts=N/SR/TB,pan=stereo|c0=c0|c1=c0,volume=1.00[dub];"
                "[original][dub]amix=inputs=2:duration=first:"
                "dropout_transition=0,%s[mixed]"
            ) % (source_audio_stream, original_level, dub_audio_stream,
                 mix_tail)
            args.extend(["-filter_complex", audio_filter])
            args.extend([
                "-map", "1:v:0", "-map", "[mixed]", "-map", "[fallback]"
            ])
            args.extend(["-vsync", "0"])

        args.extend([
            "-c:v", "copy", "-bsf:v", "dump_extra",
            "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "2",
            "-streamid", "1:%d" % int(context["translated_audio_pid"]),
            "-metadata:s:a:0", "title=E2Dub Translation",
            "-metadata:s:a:0", "language=%s" %
            ("fas" if context.get("target_language") == "fa" else "ara"),
        ])
        if not is_oe:
            args.extend([
                "-streamid", "2:%d" % int(context["original_audio_pid"]),
                "-metadata:s:a:1", "title=Original Audio",
                "-metadata:s:a:1", "language=und",
            ])
        args.extend(["-threads", "1"])
        # FFmpeg 3.0, still shipped by some DreamOS images, has no
        # -max_muxing_queue_size and refuses the whole command line because of
        # it.  The option only raises a buffering ceiling, so omitting it is
        # safe; failing to start is not.
        if context.get("supports_max_muxing_queue", True):
            args.extend(["-max_muxing_queue_size", "256"])
        args.extend([
            "-max_interleave_delta", "200000", "-flush_packets", "1",
            "-muxdelay", "0",
        ])
        if is_oe:
            args.extend(["-mpegts_copyts", "0", "-avoid_negative_ts", "make_zero"])
        else:
            args.extend(["-mpegts_copyts", "1", "-avoid_negative_ts", "disabled"])
        args.extend([
            "-mpegts_flags", "+resend_headers",
            "-mpegts_service_id", str(context["local_service_id"]),
            "-mpegts_transport_stream_id", str(context["local_tsid"]),
            "-mpegts_original_network_id", str(context["local_onid"]),
            "-pat_period", "0.1", "-sdt_period", "0.5",
            "-f", "mpegts", "pipe:1",
        ])
        return args

    def start(self, context):
        r = self.runtime
        self.fixed_delay = float(context["fixed_delay"])
        # The relay simultaneously feeds a non-delayed UDP tap for Gemini and
        # a delayed stdout path for the viewer. Capture therefore never waits
        # for the A/V delay.
        live_capture = (
            "udp://127.0.0.1:%d?fifo_size=4096&overrun_nonfatal=1&buffer_size=524288" %
            int(context["live_ts_udp_port"])
        )
        plan = build_capture_plan(
            context["ffmpeg_path"], live_capture,
            context["audio_stream"], context["capture_backend"],
        )
        playback_args = self._playback_args(context)
        relay_args = [
            context["worker_python"], "-u", context["relay"],
            context["source_url"], "%.2f" % self.fixed_delay,
            str(context["live_ts_udp_port"]), context["relay_state_file"],
        ]
        direct_dvb = False
        if context["is_oe_alliance"]:
            audio_pid = context.get("audio_pid")
            pmt_pid = context.get("pmt_pid")
            video_pid = context.get("video_pid")
            pcr_pid = context.get("pcr_pid") or video_pid
            if None not in (audio_pid, pmt_pid, video_pid, pcr_pid):
                relay_args.extend([
                    str(int(audio_pid)), str(int(pmt_pid)),
                    str(int(video_pid)), str(int(pcr_pid)),
                ])
                direct_dvb = True
                r["log"](
                    "OE-Alliance Audio source: direct DVB demux/DVR requested "
                    "PMT=0x%X VIDEO=0x%X AUDIO=0x%X PCR=0x%X; "
                    "streamproxy is fallback-only" %
                    (int(pmt_pid), int(video_pid), int(audio_pid), int(pcr_pid))
                )
            else:
                r["log"](
                    "OE-Alliance Audio source: direct DVB PID discovery incomplete; "
                    "streamproxy fallback retained"
                )
        # Start the UDP listener/capture first. It blocks safely until the
        # relay begins feeding the live tap, so the first channel audio is not
        # lost during process startup.
        self.capture_process = r["spawn"](
            plan.capture_args, stdout=subprocess.PIPE
        )
        helper_input = self.capture_process.stdout
        if plan.bridge_args is not None:
            self.capture_decode_process = r["spawn"](
                plan.bridge_args, stdin=self.capture_process.stdout,
                stdout=subprocess.PIPE,
            )
            self.capture_process.stdout.close()
            helper_input = self.capture_decode_process.stdout
        helper_args = [
            context["worker_python"], "-u", context["audio_helper"],
        ]
        if plan.helper_matroska:
            helper_args.append("--matroska-pcm")
        helper_args.extend([
            "--language", context["target_language"],
            "--key-file", context["key_file"],
            "--playback-delay", "%.2f" % self.fixed_delay,
            "--sync-correction", "%.2f" % float(context["audio_sync_correction"]),
            "--adaptive-startup", "--relay-state-file", context["relay_state_file"],
        ])
        # Choose the source A/V delay once, before releasing any TS. Both
        # relay and PCM writer use the relay's selected delay thereafter.
        relay_args.extend(["--audio-startup-state", "/tmp/e2dub-audio-helper-state"])
        self.helper_process = r["spawn"](helper_args, stdin=helper_input)
        helper_input.close()
        self.relay_process = r["spawn"](
            relay_args, stdout=subprocess.PIPE, latency_sensitive=True,
        )
        self.playback_process = r["spawn"](
            playback_args, stdin=self.relay_process.stdout,
            stdout=subprocess.PIPE, latency_sensitive=True,
        )
        self.relay_process.stdout.close()
        # Source TS is already paced by the timestamped relay. Applying a
        # smoothed byte-rate clock again starves VBR pictures/AAC together.
        http_args = [
            context["worker_python"], "-u", context["http_relay"],
            str(context["http_port"]), context["http_state_file"],
        ]
        self.http_process = r["spawn"](
            http_args, stdin=self.playback_process.stdout,
            latency_sensitive=True,
        )
        self.playback_process.stdout.close()
        # The command itself, because when FFmpeg refuses one of these
        # options the message alone -- "Error initializing the muxer" --
        # does not say which, and the graph differs per image.
        r["log"]("playback: %s" % " ".join(playback_args))
        r["log"](
            "AudioEngine started: base RAM delay=%.2fs (adaptive startup), dub correction=%+.2fs, "
            "receiver_audio=%s http_pacing=%s source=%s" %
            (self.fixed_delay, float(context["audio_sync_correction"]),
             "single-mixed-aac" if context["is_oe_alliance"]
             else "dual-track-aac",
             "off",
             "dvb-direct" if direct_dvb else "streamproxy")
        )
        return True
