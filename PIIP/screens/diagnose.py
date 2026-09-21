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
"""Test each configured playlist and say exactly what happened.

"No playlist loaded" is not actionable. This screen shows, per playlist,
the URL that was requested with the password masked, the HTTP status, and
whatever the provider wrote in the error body - which is usually where the
real reason lives.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config
from ..providers import m3u
from ..utils import playlists
from ..utils.backdrop import backdrop
from ..utils import skin as sk
from ..utils.compat import native
from ..utils.uisafe import safe_actions, BackgroundTask

_c = config.plugins.piip

def build_skin():
    return sk.list_screen(
        'FarsiDiagnose', 'Test playlists', 'PIIP',
        buttons=[('RETEST', sk.BTN_GREEN),
                 ('FULL URL', sk.BTN_BLUE)],
        hint='GREEN - Retest    OK - Full URL    EXIT - Back',
        header_widget='head', info=('detail', 'status'), item_height=48)


class FarsiDiagnose(Screen):

    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.entries = []
        self.results = []

        self['bg'] = Pixmap()
        self['head'] = Label('Testing playlists...')
        self['list'] = MenuList([])
        self['detail'] = Label('')
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions'],
            safe_actions(self, {
                'ok': self.showDetail,
                'cancel': self.close,
                'up': self.up,
                'down': self.down,
                'red': self.close,
                'green': self.retest,
            }), -1)

        self.task = BackgroundTask(self, self._probe, self._probed, 'diagnose')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self)

    # ------------------------------------------------------------- running

    def begin(self):
        self.entries = self._sources()
        if not self.entries:
            self['head'].setText(native('Nothing to test'))
            self['status'].setText(native(
                'No playlist configured. Add one in Settings or put it in %s'
                % playlists.STORE))
            return
        self['head'].setText(native('Testing %d playlist(s)...'
                                    % len(self.entries)))
        self['list'].setList([native('%s  ...' % e.name) for e in self.entries])
        self.task.start()

    def retest(self):
        if not self.task.running():
            self.begin()

    def _sources(self):
        out = []
        url = (_c.m3u_url.value or '').strip()
        if url and url not in ('http://', 'https://'):
            out.append(playlists.Entry('Settings', url))
        out.extend(playlists.load())
        return out

    def _probe(self):
        """Worker thread: no widget may be touched from here."""
        found = []
        for entry in self.entries:
            found.append((entry, m3u.probe(entry.url,
                                           user_agent=_c.user_agent.value)))
        return found

    def _probed(self, result, error):
        if error:
            self['head'].setText(native('Test failed'))
            self['status'].setText(native(error))
            return
        self.results = result or []
        rows = []
        good = 0
        for entry, note in self.results:
            ok = note.startswith('OK')
            if ok:
                good += 1
            rows.append(native('%s  %s  %s'
                               % ('OK ' if ok else 'BAD', entry.name, note)))
        self['list'].setList(rows)
        self['head'].setText(native('%d of %d playlists working'
                                    % (good, len(self.results))))
        self['status'].setText(native(
            'OK: show the full URL   |   GREEN: test again   |   EXIT: back'))
        self.showDetail()

    # ------------------------------------------------------------- display

    def _current(self):
        idx = self['list'].getSelectedIndex()
        if idx is None or idx >= len(self.results):
            return None, ''
        return self.results[idx]

    def showDetail(self):
        entry, note = self._current()
        if entry is None:
            self['detail'].setText('')
            return
        self['detail'].setText(native(
            '%s\n%s\n\n%s' % (entry.name, m3u.mask_url(entry.url), note)))

    def up(self):
        self['list'].up()
        self.showDetail()

    def down(self):
        self['list'].down()
        self.showDetail()
