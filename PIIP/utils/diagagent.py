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
"""What the decoder is really doing, sampled from inside Enigma2.

The engine can report that it sent a healthy stream while the television
shows a frozen picture. The only witness of the picture and sound is the
service Enigma2 is playing, so once a second, while a PIIP playback or a
diagnostic watch is running, this records the decoder's play position,
the picture size, GStreamer's buffer and every service event.

A play position that stops advancing while the wall clock runs is a
freeze the viewer sees, whatever any other log says.

It also takes simple commands from /tmp/piip_diag.cmd so a test can open
the real player on a known stream without anyone holding the remote.
Runs on the main loop via eTimer; all work is a few attribute reads.
"""

import json
import os
import time

from enigma import eTimer, iPlayableService, iServiceInformation

from . import diaglog
from .compat import native
from ..translate import redact

COMMAND_FILE = '/tmp/piip_diag.cmd'
INTERVAL_MS = 1000

_agent = [None]

EVENT_NAMES = dict((getattr(iPlayableService, n), n)
                   for n in dir(iPlayableService)
                   if n.startswith('ev') and
                   isinstance(getattr(iPlayableService, n), int))


def agent():
    return _agent[0]


def start(session):
    if _agent[0] is None:
        try:
            _agent[0] = Agent(session)
        except Exception as exc:
            diaglog.append_text('/tmp/piip_diag_agent.log',
                                'agent failed to start: %s' % exc)
    return _agent[0]


def attach(folder, label=''):
    """Called by the player: sample into `folder` until detach()."""
    a = _agent[0]
    if a is not None and folder:
        a.attach(folder, label)


def detach(folder=None):
    a = _agent[0]
    if a is not None:
        a.detach(folder)


class Agent(object):
    def __init__(self, session):
        self.session = session
        self.folder = None
        self.label = ''
        self.writer = None
        self.last_pos = None
        self.last_wall = None
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.tick)
        except AttributeError:
            self._conn = self.timer.timeout.connect(self.tick)
        try:
            session.nav.event.append(self.onEvent)
        except Exception:
            pass
        self.timer.start(INTERVAL_MS, False)

    # ------------------------------------------------------------ targets

    def attach(self, folder, label=''):
        if folder == self.folder:
            return
        self._close()
        self.folder, self.label = folder, label
        self.writer = diaglog.JsonLines(os.path.join(folder, 'player.jsonl'))
        self.last_pos = self.last_wall = None
        self.event('attach %s' % label)

    def detach(self, folder=None):
        if folder and folder != self.folder:
            return
        self.event('detach %s' % self.label)
        self._close()

    def _close(self):
        if self.writer is not None:
            self.writer.close()
        self.writer = None
        self.folder = None

    def target(self):
        if self.folder:
            return self.folder
        watch = diaglog.active_watch()
        if watch:
            self.attach(watch['dir'], 'watch')
            return self.folder
        return None

    def event(self, text):
        folder = self.folder or (diaglog.active_watch() or {}).get('dir')
        if folder:
            diaglog.append_text(os.path.join(folder, 'events.log'), text)

    # ------------------------------------------------------------ sampling

    def onEvent(self, ev):
        try:
            name = EVENT_NAMES.get(ev, 'ev%d' % ev)
            self.event('service %s' % name)
        except Exception:
            pass

    def tick(self):
        try:
            self.commands()
        except Exception as exc:
            diaglog.append_text('/tmp/piip_diag_agent.log', 'command: %s' % exc)
        if self.target() is None:
            return
        try:
            self.writer.write(self.sample())
        except Exception as exc:
            self.event('sample failed: %s' % exc)
        watch = diaglog.active_watch()
        if self.label == 'watch' and not watch:
            self.detach()

    def sample(self):
        now = time.time()
        rec = {'t': round(now, 2)}
        nav = self.session.nav
        try:
            ref = nav.getCurrentlyPlayingServiceReference()
            rec['ref'] = redact.text(native(ref.toString()))[:160] if ref else ''
        except Exception:
            rec['ref'] = ''
        service = nav.getCurrentService()
        rec['service'] = service is not None
        try:
            rec['screen'] = self.session.current_dialog.__class__.__name__
        except Exception:
            pass
        if service is None:
            self.last_pos = self.last_wall = None
            return rec
        try:
            seek = service.seek()
            if seek is not None:
                result = seek.getPlayPosition()
                if not result[0]:
                    pos = result[1] / 90000.0
                    rec['pos'] = round(pos, 3)
                    if self.last_pos is not None:
                        wall = now - self.last_wall
                        rec['pos_delta'] = round(pos - self.last_pos, 3)
                        rec['wall_delta'] = round(wall, 3)
                    self.last_pos, self.last_wall = pos, now
                else:
                    rec['pos_err'] = result[0]
        except Exception as exc:
            rec['pos_exc'] = str(exc)[:80]
        try:
            info = service.info()
            if info is not None:
                rec['vw'] = info.getInfo(iServiceInformation.sVideoWidth)
                rec['vh'] = info.getInfo(iServiceInformation.sVideoHeight)
        except Exception:
            pass
        try:
            streamed = service.streamed()
            if streamed is not None:
                charge = streamed.getBufferCharge()
                if charge:
                    rec['buffer'] = list(charge)[:5]
        except Exception:
            pass
        try:
            tracks = service.audioTracks()
            if tracks is not None:
                rec['atracks'] = tracks.getNumberOfTracks()
        except Exception:
            pass
        return rec

    # ------------------------------------------------------------ commands

    def commands(self):
        if not os.path.exists(COMMAND_FILE):
            return
        try:
            with open(COMMAND_FILE) as fh:
                req = json.load(fh)
        finally:
            try:
                os.remove(COMMAND_FILE)
            except Exception:
                pass
        cmd = req.get('cmd')
        self.event('command %s' % cmd)
        if cmd == 'play':
            self.play(req)
        elif cmd == 'stop':
            self.stopPlayer()
        elif cmd == 'open':
            self.open(req.get('screen', 'main'))

    def play(self, req):
        from ..plugin import config
        from ..providers.models import MediaItem
        from ..screens.player import FarsiPlayer
        c = config.plugins.piip
        saved = c.translate.value
        if 'translate' in req:
            # For this playback only; the saved setting comes back on close.
            c.translate.value = bool(req['translate'])
        item = MediaItem(native(req.get('name') or 'diag'),
                         native(req['url']), kind='live')

        try:
            previous = self.session.nav.getCurrentlyPlayingServiceReference()
        except Exception:
            previous = None

        def restore(*_args):
            c.translate.value = saved
            # A test must hand the television back as it found it.
            if previous is not None:
                try:
                    self.session.nav.playService(previous)
                    self.event('restored the previous service')
                except Exception as exc:
                    self.event('could not restore the previous service: %s' % exc)
        self.session.openWithCallback(restore, FarsiPlayer, item)

    def stopPlayer(self):
        dialog = getattr(self.session, 'current_dialog', None)
        if dialog is not None and dialog.__class__.__name__ == 'FarsiPlayer':
            dialog.stop()

    def open(self, name):
        if name == 'main':
            from ..main import FarsiMain
            self.session.open(FarsiMain)
        elif name == 'iptvorg':
            from ..screens.iptvorg import FarsiIPTVOrg
            self.session.open(FarsiIPTVOrg)
        elif name in ('m3u', 'xtream', 'stalker'):
            from ..screens.serversetup import FarsiServerSetup
            self.session.open(FarsiServerSetup, name)
