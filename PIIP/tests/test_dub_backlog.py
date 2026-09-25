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
"""The dub helper's defences against translating the past.

Live Translate renders dense speech slower than real time, so anything that
lets it work through history becomes a permanent offset between the Persian
and the picture: a startup backlog, a full input queue, or simply feeding it
for minutes without letting it catch up.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, 'translate', 'e2dub'))

import e2dub_audio_helper as helper                          # noqa: E402

FAIL = []
RUN = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name +
          (' :: ' + extra if extra else ''))
    RUN.append(name)
    if not cond:
        FAIL.append(name)


def pcm(level, samples=1200):
    return struct.pack('<%dh' % samples, *([level, -level] * (samples // 2)))


# ------------------------------------------------------------------ silence
check('silence is not mistaken for speech',
      not helper.pcm_has_meaningful_signal(pcm(4)))
check('ordinary speech level is speech',
      helper.pcm_has_meaningful_signal(pcm(2000)))
check('returned silence scores below the speech threshold',
      helper.pcm_speech_level(pcm(3)) < helper.INPUT_SIGNAL_PEAK_THRESHOLD * 4)
check('returned speech scores above the speech threshold',
      helper.pcm_speech_level(pcm(6000)) >=
      helper.INPUT_SIGNAL_PEAK_THRESHOLD * 4)
check('the strided scan still finds a short burst',
      helper.pcm_speech_level(pcm(1) + pcm(9000, 64)) >= 8000)

# ------------------------------------------------------- the input gate
check('nothing is queued before a session exists',
      not helper.STREAM_ACCEPTING_INPUT.is_set())

for _ in range(7):
    helper.INPUT_QUEUE.put_nowait(('frame', 0.0, 0.1, 0.0))
check('setup discards everything captured while it negotiated',
      helper.discard_queued_input() == 7 and helper.INPUT_QUEUE.empty())
check('discarding an empty queue is not an error',
      helper.discard_queued_input() == 0)

# ------------------------------------------------------ the backlog probe
check('the feed is released long before the drain window closes',
      helper.MODEL_QUIET_SECONDS < helper.DRAIN_MAX_SECONDS)
check('live healthy 8.5s queue within 8s sync reserve keeps feeding',
      not helper.should_probe_backlog(61, 0,
                                      {'queued_ms': 8500,
                                       'sync_reserve_ms': 7976}))
check('substantial excess translation can trigger a probe',
      helper.should_probe_backlog(61, 0,
                                  {'queued_ms': 11000,
                                   'sync_reserve_ms': 7976}))
check('pressure before the probe interval does not interrupt speech',
      not helper.should_probe_backlog(30, 0,
                                      {'queued_ms': 11000,
                                       'sync_reserve_ms': 7976}))
check('backlog probes are spaced by at least a minute',
      helper.FEED_WINDOW_SECONDS >= 60.0)
check('a drain is bounded so translation is never starved',
      helper.DRAIN_MAX_SECONDS <= helper.FEED_WINDOW_SECONDS)
check('quiet must last longer than a phrasing pause to count as caught up',
      helper.MODEL_QUIET_SECONDS >= 2.0)
check('a resync is a session rebuild, not a fast transport retry',
      not helper.should_fast_reconnect(helper.DriftResync('behind')))

# ------------------------------------------------------------- reconnects
check('a fresh session asks for a resumption handle',
      helper.setup_message('official')['setup']['sessionResumption'] ==
      {'handle': None})
check('a rotation reuses the handle the server issued',
      helper.setup_message('official', session_handle='token')['setup']
      ['sessionResumption'] == {'handle': 'token'})
check('transport loss reconnects immediately',
      helper.should_fast_reconnect(helper.GoAwayError('rotation')))
check('an announced rotation is used to its safe end',
      helper.goaway_reconnect_delay('50s') == 42.0 and
      helper.goaway_reconnect_delay('5s') == 0.0)

# --------------------------------------------------------------- the tap
check('the diagnostics tap is off unless a marker names a folder',
      helper.DUMP_DIR[0] is None)
helper.dump_pcm('src16', b'\0\0')                            # must not raise

print('\n%d checks, %d failed' % (len(RUN), len(FAIL)))
sys.exit(1 if FAIL else 0)
