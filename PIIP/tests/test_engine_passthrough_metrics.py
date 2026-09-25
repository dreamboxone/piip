# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
#
"""The metrics worker must remain healthy when passthrough has no mixer."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate.engine import Engine

FAIL = []


def check(name, condition):
    print(('  PASS  ' if condition else '  FAIL  ') + name)
    if not condition:
        FAIL.append(name)


class StopAfterOneTick(object):
    def __init__(self):
        self.calls = 0

    def wait(self, _seconds):
        self.calls += 1
        return self.calls > 1


class EmptyMeter(object):
    def take(self):
        return {}, {}


class Metrics(object):
    fh = object()

    def __init__(self):
        self.records = []
        self.closed = False

    def write(self, record):
        self.records.append(record)

    def close(self):
        self.closed = True


class Video(object):
    bytes_held = 0


engine = Engine.__new__(Engine)
engine.metrics = Metrics()
engine.stopping = StopAfterOneTick()
engine.started_at = time.time()
engine.meter = EmptyMeter()
engine.cfg = {'passthrough': True}
engine.mixer = None
engine.audio_started = False
engine.video_started = False
engine.client = None
engine.stats = {}
engine.video = Video()
engine.clock_late_max_ms = 0
engine.gemini = None
engine.ff_in = None
engine.ff_out = None
engine._metrics_loop()

check('passthrough metrics complete without a mixer',
      engine.metrics.closed and len(engine.metrics.records) == 1)
check('passthrough record identifies its mode',
      engine.metrics.records[0].get('mode') == 'passthrough')

if FAIL:
    sys.exit(1)
print('all checks passed')
