# -*- coding: utf-8 -*-
"""The player red key changes translation mode without stopping live TV first."""

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import enigma_stub
enigma_stub.install()

from PIIP.providers.models import LIVE, MediaItem
from PIIP.screens import player as player_mod
from PIIP.translate import dub


failures = []


def check(label, condition):
    print(('  PASS  ' if condition else '  FAIL  ') + label)
    if not condition:
        failures.append(label)


class Pipeline(object):
    url = 'http://127.0.0.1:8899/live.ts'
    entered = None
    release = None
    instances = []

    def __init__(self, *args):
        self.starts = 0
        self.stops = 0
        self.args = args
        self.instances.append(self)

    def start(self):
        self.starts += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(3)
        return True

    def stop(self):
        self.stops += 1

    def alive(self):
        return self.stops == 0

    def helper_state(self):
        return {'state': 'audio'}


def settled(player):
    deadline = time.time() + 3
    while time.time() < deadline:
        task = player._translation_task
        if task is not None and not task.running():
            task._timer.fire()
            if not player._translation_phase:
                return True
        time.sleep(0.01)
    return False


old_key = player_mod.api_key
old_pipeline = dub.DubPipeline
old_read_state = dub.read_state
old_image = dub.is_oe_alliance
setting = player_mod._c.translate
volume = player_mod._c.vol_translated
old_setting = setting.value
old_volume = volume.value
try:
    player_mod.api_key = lambda: 'test-key'
    dub.DubPipeline = Pipeline
    dub.is_oe_alliance = lambda: True
    setting.value = False
    volume.value = 65
    item = MediaItem('Test channel', 'http://example.invalid/live.ts',
                     kind=LIVE)
    session = enigma_stub.Session()
    player = player_mod.FarsiPlayer(session, item)
    player.playDirect()
    player.started_at = time.time()
    original = session.nav.playing

    Pipeline.entered = threading.Event()
    Pipeline.release = threading.Event()
    player['actions'].action('ColorActions', 'red')
    check('red starts the translation pipeline', Pipeline.entered.wait(1))
    check('original channel stays on during translation startup',
          session.nav.playing is original)
    check('the red key saves translation as enabled', setting.value is True)
    check('red does not change translation volume', volume.value == 65)
    player['actions'].action('ColorActions', 'red')
    check('duplicate red event does not cancel startup',
          setting.value is True and not player._translation_cancelled)
    Pipeline.release.set()
    check('startup completion reaches the player', settled(player))
    check('the translated service waits for its relay',
          player.engine is Pipeline.instances[-1] and
          player._dub_waiting and session.nav.playing is original)

    dub.read_state = lambda path: {'state': 'ready'}
    player.refresh()
    check('relay readiness schedules a deferred service change',
          player._dub_handoff_pending and session.nav.playing is original)
    player.defer_timer.fire()
    check('ready translation opens the local service',
          session.nav.playing is not original and
          session.nav.playing.path == Pipeline.url and
          session.nav.playing.type == player.serviceType())
    check('service handoff does not explicitly stop the active service',
          session.nav.stop_calls == 0)

    translated = player.engine
    player._last_translation_key_at = 0
    player['actions'].action('ColorActions', 'red')
    check('red returns to the original channel',
          session.nav.playing.path == original.path and player.direct)
    check('red saves translation as disabled without muting it',
          setting.value is False and volume.value == 65)
    check('the previous pipeline stops in the background', settled(player))
    check('the previous pipeline stopped once', translated.stops == 1)
    check('returning to direct playback avoids a separate stop call',
          session.nav.stop_calls == 0)

    player_mod.api_key = lambda: ''
    player._last_translation_key_at = 0
    player['actions'].action('ColorActions', 'red')
    check('missing API key leaves the original service playing',
          player.direct and session.nav.playing.path == original.path and
          setting.value is False)

    player_mod.api_key = lambda: 'test-key'
    Pipeline.entered = threading.Event()
    Pipeline.release = threading.Event()
    player._last_translation_key_at = 0
    player['actions'].action('ColorActions', 'red')
    check('second startup entered its worker', Pipeline.entered.wait(1))
    pending = Pipeline.instances[-1]
    player._last_translation_key_at = 0
    player['actions'].action('ColorActions', 'red')
    check('red cancels startup without leaving original service',
          setting.value is False and session.nav.playing.path == original.path)
    Pipeline.release.set()
    check('cancelled startup completes', settled(player))
    check('cancelled pipeline is stopped', pending.stops == 1 and player.direct)

    Pipeline.entered = threading.Event()
    Pipeline.release = threading.Event()
    player._last_translation_key_at = 0
    player['actions'].action('ColorActions', 'red')
    check('close test entered startup worker', Pipeline.entered.wait(1))
    closing = Pipeline.instances[-1]
    player.cleanup()
    Pipeline.release.set()
    deadline = time.time() + 3
    while closing.stops == 0 and time.time() < deadline:
        time.sleep(0.01)
    check('closing the player releases a starting pipeline',
          closing.stops == 1)

    dub.is_oe_alliance = lambda: False
    dream_session = enigma_stub.Session()
    dream_player = player_mod.FarsiPlayer(dream_session, item)
    dream_player.engine = Pipeline()
    dream_player.direct = False
    dream_player.playLocal()
    check('DreamOS retains the native DVB transport service',
          dream_session.nav.playing.type == 1 and
          dream_session.nav.playing.path == Pipeline.url)
    check('DreamOS handoff also avoids a separate stop call',
          dream_session.nav.stop_calls == 0)
    dream_player._service_transition_until = 0
    dream_player.doEofInternal()
    check('DreamOS EOF forces restart of the same local service',
          dream_session.nav.force_restarts == 1 and
          dream_session.nav.playing.path == Pipeline.url)
    dream_player.cleanup()
finally:
    player_mod.api_key = old_key
    dub.DubPipeline = old_pipeline
    dub.read_state = old_read_state
    dub.is_oe_alliance = old_image
    setting.value = old_setting
    volume.value = old_volume
    Pipeline.entered = None
    Pipeline.release = None

print('%d failed' % len(failures))
sys.exit(1 if failures else 0)
