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
"""Enter one server's details, save it, connect to it.

One screen for all three provider types: the fields come from the store,
which is the only thing that differs between an Xtream account, an M3U
playlist and a Stalker portal.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from ..utils import servers, skin as sk, textlist
from ..utils.backdrop import backdrop
from ..utils.compat import native
from ..utils.uisafe import safe_actions
from ..utils.uisafe import BackgroundTask


def probe(entry, user_agent=None):
    """Validate a setup entry and return enough data for the next screen."""
    kind = entry.get('type')
    if kind == 'xtream':
        from ..providers.xtream import Xtream
        api = Xtream(entry.get('host', ''), entry.get('user', ''),
                     entry.get('password', ''),
                     user_agent=user_agent or
                     'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3')
        return {'kind': kind, 'info': api.login()}
    if kind == 'stalker':
        from ..providers.stalker import Stalker
        api = Stalker(entry.get('portal', ''), entry.get('mac', ''),
                      user_agent=user_agent or
                      'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3')
        return {'kind': kind, 'token': api.connect()}
    from ..providers import m3u
    from ..providers.models import LIVE
    items = m3u.fetch(entry.get('url', ''), user_agent=user_agent or m3u.UA,
                      kinds=(LIVE,))
    if not items:
        raise ValueError('playlist contains no playable entries')
    live = m3u.of_kind(items, 'live')
    return {'kind': kind, 'count': len(items), 'items': live}


def build_skin(kind='m3u'):
    titles = {
        'm3u': 'M3U PLAYLIST - SETUP',
        'stalker': 'STALKER PORTAL - SETUP',
        'xtream': 'XTREAM CODES-LOGIN',
    }
    buttons = {
        'm3u': [('LOAD', sk.BTN_GREEN), ('SAVE', sk.ACCENT_WARM),
                ('SERVERS LOCAL', sk.BTN_PURPLE),
                ('SERVERS Online', sk.BTN_TEAL)],
        'stalker': [('CONNECT', sk.BTN_GREEN), ('SAVE', sk.ACCENT_WARM),
                    ('SERVERS', sk.BTN_PURPLE)],
        'xtream': [('CONNECT', sk.BTN_GREEN), ('SAVE', sk.ACCENT_WARM),
                   ('SERVERS', sk.BTN_PURPLE)],
    }
    hints = {
        'm3u': 'OK - Edit   GREEN - Load   YELLOW - Save   BLUE - Local   INFO - Online',
        'stalker': 'OK - Edit   GREEN - Connect   YELLOW - Save   BLUE - Servers',
        'xtream': 'OK - Edit   GREEN - Connect   YELLOW - Save   BLUE - Servers',
    }
    # HybridIPTV's setup menus: the emblem centred above a pane exactly as
    # tall as the fields, 70px rows in a 40px face.
    xml = sk.list_screen(
        'FarsiServerSetup', titles.get(kind, 'SERVER SETUP'), '',
        buttons=buttons.get(kind, buttons['m3u']),
        hint=hints.get(kind, hints['m3u']), hint_x=1160, hint_width=720,
        info=('hint', 'status'), item_height=70,
        layout='setup' if kind == 'stalker' else 'lower',
        rows=len(servers.FIELDS.get(kind, servers.FIELDS['m3u'])),
        backdrop='bg_%s.png' % kind, logo_widget='logo')
    return textlist.listbox(xml, font=40, align='left')


class FarsiServerSetup(Screen):
    """close() returns the entry that was connected to, or None."""

    def __init__(self, session, kind='m3u', entry=None):
        self.kind = kind if kind in servers.TYPES else 'm3u'
        self.skin = build_skin(self.kind)
        Screen.__init__(self, session)
        self.session = session
        self.entry = dict(entry) if entry else servers.blank(self.kind)
        # The saved server this form edits, so a changed address replaces
        # it instead of adding a second copy.
        self.original = dict(entry) if entry else None
        self.entry['type'] = self.kind

        self['bg'] = Pixmap()
        self['logo'] = Pixmap()
        self['list'] = textlist.make()
        self['hint'] = Label('')
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions', 'InfobarEPGActions'],
            safe_actions(self, {
                'ok': self.edit,
                'cancel': self.close,
                'red': self.close,
                'green': self.connect,
                'yellow': self.saveEntry,
                'blue': self.importSaved,
                'menu': self.importSaved,
                'info': self.openOnline,
                'showEventInfo': self.openOnline,
                'up': self.up,
                'down': self.down,
            }), -1)
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.refresh)
        self.connect_task = BackgroundTask(self, self._probe,
                                           self._probeDone, 'server-connect')
        self.onClose.append(self.connect_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, 'bg_%s.png' % self.kind)
        from ..utils.backdrop import load
        load(self, 'logo', 'emblem_%s.png' % self.kind)

    # ------------------------------------------------------------- drawing

    def fields(self):
        return servers.FIELDS[self.kind]

    def refresh(self):
        rows = []
        for key, prompt, _default, secret in self.fields():
            value = self.entry.get(key, '')
            if secret and value:
                value = '*' * len(value)
            rows.append(native('%s :  %s' % (prompt, value)))
        index = textlist.index(self['list'])
        textlist.set_rows(self['list'], rows)
        textlist.select(self['list'], max(0, min(index, len(rows) - 1)))
        saved = len(servers.load(self.kind))
        self['hint'].setText(native(
            'OK edits the selected line.   MENU shows the %d saved %s '
            'server(s).' % (saved, self.kind)))
        empty = servers.missing(self.kind, self.entry)
        self['status'].setText(native(
            'Still to fill in: %s' % ', '.join(empty) if empty
            else 'Ready - GREEN connects, YELLOW saves it.'))

    def up(self):
        textlist.move(self['list'], -1, len(self.fields()))

    def down(self):
        textlist.move(self['list'], 1, len(self.fields()))

    # ------------------------------------------------------------- editing

    def current(self):
        index = textlist.index(self['list'])
        if index < 0 or index >= len(self.fields()):
            return None
        return self.fields()[index]

    def edit(self):
        field = self.current()
        if field is None:
            return
        key, prompt, _default, _secret = field
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
        except ImportError:
            self['status'].setText(native('No on-screen keyboard on this '
                                          'image; edit in Settings instead.'))
            return
        self.editing = key
        self.session.openWithCallback(
            self.edited, VirtualKeyBoard,
            title=native(prompt),
            text=native(self.entry.get(key, '')))

    def edited(self, text=None):
        if text is None:
            return
        self.entry[self.editing] = native(text)
        self.refresh()

    # -------------------------------------------------------------- saving

    def saveEntry(self, quiet=False):
        empty = servers.missing(self.kind, self.entry)
        if empty:
            # The reference's wording, plus which fields it means.
            name_prompt = servers.FIELDS[self.kind][0][1]
            lead = ('Please enter Server Name.' if empty == [name_prompt]
                    else 'Please fill in all fields.')
            self['status'].setText(native('%s   Still empty: %s'
                                          % (lead, ', '.join(empty))))
            return False
        error = servers.upsert(self.kind, self.entry, replaces=self.original)
        if not error:
            self.original = dict(self.entry)
        if error:
            self['status'].setText(native('Could not save - %s' % error))
            return False
        self.refresh()
        if not quiet:
            self['status'].setText(native('Saved as "%s".'
                                          % self.entry.get('name')))
        return True

    def connect(self):
        if self.connect_task.running():
            return
        if not self.saveEntry(quiet=True):
            return
        servers.activate(self.entry)
        self['status'].setText(native('Checking connection...'))
        self.connect_task.start()

    def _probe(self):
        from ..plugin import config
        return probe(dict(self.entry), config.plugins.piip.user_agent.value)

    def _probeDone(self, result, error):
        if error:
            self['status'].setText(native('Connection failed: %s' % error))
            return
        kind = (result or {}).get('kind', self.kind)
        self['status'].setText(native(
            'Connected successfully%s.' %
            (' - %d entries' % result.get('count', 0)
             if kind == 'm3u' else '')))
        if kind == 'm3u':
            # As the reference does: the playlist's groups first.
            from .m3ugroups import FarsiM3UGroups
            self.session.open(FarsiM3UGroups, result.get('items'))
        else:
            from .home import FarsiHome
            self.session.open(FarsiHome)

    # ------------------------------------------------------------ importing

    def importSaved(self):
        # Always opens, even with nothing saved: the picker says so itself,
        # and a key that sometimes does nothing reads as a broken key.
        from .serverlist import FarsiServerPicker
        self.session.openWithCallback(self.imported, FarsiServerPicker,
                                      self.kind)

    def imported(self, entry=None):
        if not entry:
            return
        self.entry = dict(entry)
        self.entry['type'] = self.kind
        self.original = dict(self.entry)
        self['status'].setText(native('Filled in from "%s".'
                                      % entry.get('name', '')))
        self.refresh()

    def openOnline(self):
        """The fourth M3U action opens the public online playlist list."""
        if self.kind != 'm3u':
            self.importSaved()
            return
        from .iptvorg import FarsiIPTVOrg
        self.session.openWithCallback(self.onlinePicked, FarsiIPTVOrg, True)

    def onlinePicked(self, picked=None):
        if not picked:
            return
        name, url = picked
        self.entry['name'] = native(name)
        self.entry['url'] = native(url)
        self.refresh()
