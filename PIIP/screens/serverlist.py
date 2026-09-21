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
"""Saved servers.

Two screens over the same list, as in the reference plugin: the list you
reach from the main menu, which connects to a server and can delete one,
and the picker a setup screen opens on MENU, which only hands an entry
back so its fields can be filled in.

The picker is per-type and says so - "STALKER SAVED SERVERS" over the
Stalker wallpaper - and an empty one says "No saved servers" in the list
itself. Without that, opening an empty picker over a setup screen that
looks the same is indistinguishable from the key doing nothing at all.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..utils import servers, skin as sk
from ..utils.backdrop import backdrop
from ..utils.compat import native
from ..utils.uisafe import safe_actions, BackgroundTask

EMPTY = 'No saved servers'

WALLPAPER = {
    'xtream': 'bg_xtream.png',
    'm3u': 'bg_m3u.png',
    'stalker': 'bg_stalker.png',
}


def title_for(kind):
    return ('%s SAVED SERVERS' % kind.upper()) if kind else 'SAVED SERVERS'


def build_skin(kind=None, picker=False):
    buttons = ([('IMPORT', sk.BTN_GREEN)] if picker
               else [('CONNECT', sk.BTN_GREEN), ('DELETE', sk.BTN_DELETE)])
    hint = ('OK - Import    INFO - Portal list    EXIT - Back' if picker
            else 'OK - Connect    RED - Delete    EXIT - Back')
    return sk.list_screen(
        'FarsiServerPicker' if picker else 'FarsiServerList',
        title_for(kind), 'PIIP',
        buttons=buttons, hint=hint,
        header_widget='head', info=('detail', 'status'), item_height=56)


class _Base(Screen):
    """The shared list; what OK does is the only difference."""

    PICKER = False

    def __init__(self, session, kind=None):
        self.kind = kind
        self.skin = build_skin(kind, self.PICKER)
        Screen.__init__(self, session)
        self.session = session
        self.entries = []

        self['bg'] = Pixmap()
        self['list'] = MenuList([])
        self['head'] = Label('')
        self['detail'] = Label('')
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions', 'EPGSelectActions', 'InfobarActions'],
            safe_actions(self, self.keymap()), -1)
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.reload)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, WALLPAPER.get(self.kind, 'bg_list.png'))

    def keymap(self):
        return {
            'ok': self.choose,
            'cancel': self.dismiss,
            'up': self.up,
            'down': self.down,
        }

    def up(self):
        self['list'].up()
        self.showDetail()

    def down(self):
        self['list'].down()
        self.showDetail()

    def row(self, index, entry):
        """One line, numbered the way the reference numbers them.

        The second field is whatever tells two servers of the same type
        apart: the MAC for a portal, the username for an Xtream account.
        """
        if not self.kind:                # a mixed list has to name the type
            return servers.label(entry)
        where = servers.address(entry)
        if '://' in where:
            where = where.split('://', 1)[1].split('/', 1)[0]
        second = {'stalker': entry.get('mac', ''),
                  'xtream': entry.get('user', '')}.get(self.kind, '')
        name = entry.get('name', 'unnamed')
        parts = [p for p in (name, where, second) if p]
        return native('Server %02d  %s' % (index + 1, '  |  '.join(parts)))

    def reload(self):
        self.entries = (servers.load(self.kind) if self.kind
                        else servers.load_all())
        if self.entries:
            rows = [self.row(i, e) for i, e in enumerate(self.entries)]
        else:
            # In the list itself, not only in the status line: an empty
            # screen reads as "that key did nothing".
            rows = [native(EMPTY)]
        self['list'].setList(rows)
        self['head'].setText(native(
            servers.TITLES[self.kind] if self.kind else 'All types'))
        if not self.entries:
            self['status'].setText(native(
                'Nothing saved yet. Fill in the details and press GREEN to '
                'save one.'))
        else:
            self['status'].setText(native('%d server(s)' % len(self.entries)))
        self.showDetail()

    def selected(self):
        index = self['list'].getSelectedIndex()
        if index is None or index >= len(self.entries):
            return None
        return self.entries[index]

    def showDetail(self):
        entry = self.selected()
        if entry is None:
            self['detail'].setText('')
            return
        # The address in full here: this is the screen you come to when a
        # server is not working and you want to see what it actually says.
        self['detail'].setText(native(servers.address(entry)))

    def choose(self):
        raise NotImplementedError

    def dismiss(self):
        self.close(None)


class FarsiServerList(_Base):
    """Connect to a saved server. close() returns the entry, or None."""

    def __init__(self, session, kind=None):
        _Base.__init__(self, session, kind)
        self.pending_connect = None
        self.connect_task = BackgroundTask(self, self._probe,
                                           self._connected,
                                           'saved-server-connect')
        self.onClose.append(self.connect_task.stop)

    def keymap(self):
        keys = _Base.keymap(self)
        keys.update({'red': self.confirmDelete, 'green': self.dismiss})
        return keys

    def choose(self):
        entry = self.selected()
        if entry is None or self.connect_task.running():
            return
        servers.activate(entry)
        self.pending_connect = dict(entry)
        self['status'].setText(native('Checking connection...'))
        self.connect_task.start()

    def _probe(self):
        from .serversetup import probe
        from ..plugin import config
        return probe(self.pending_connect,
                     config.plugins.piip.user_agent.value)

    def _connected(self, result, error):
        if error:
            self['status'].setText(native('Connection failed: %s' % error))
            return
        if self.pending_connect.get('type') == 'm3u':
            from .m3ugroups import FarsiM3UGroups
            self['status'].setText(native('Playlist loaded successfully.'))
            self.session.open(FarsiM3UGroups, (result or {}).get('items'))
            return
        self.close(self.pending_connect)

    def confirmDelete(self):
        entry = self.selected()
        if entry is None:
            return
        self.pending = entry
        self.session.openWithCallback(
            self.doDelete, MessageBox,
            native('Delete "%s"?' % entry.get('name', '')),
            MessageBox.TYPE_YESNO, default=False)

    def doDelete(self, confirmed=False):
        if not confirmed:
            return
        error = servers.delete(self.pending.get('type'),
                               self.pending.get('name'), entry=self.pending)
        self.reload()
        if error:
            self['status'].setText(native('Could not delete - %s' % error))


class FarsiServerPicker(_Base):
    """Hand an entry back without touching the config."""

    PICKER = True

    def keymap(self):
        keys = _Base.keymap(self)
        # Where the reference hangs its portal importer: "INFO - Import".
        keys.update({'info': self.openPortals,
                     'showEventInfo': self.openPortals,
                     'menu': self.openPortals,
                     'yellow': self.openPortals})
        return keys

    def choose(self):
        entry = self.selected()
        if entry is None:
            return
        self.close(entry)

    def openPortals(self):
        """Only Stalker has shareable portal lists."""
        if self.kind != 'stalker':
            self['status'].setText(native(
                'Portal lists are a Stalker thing only.'))
            return
        from .portalloader import FarsiPortalLoader
        self.session.openWithCallback(self.imported, FarsiPortalLoader)

    def imported(self, entry=None):
        self.reload()
