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
"""Import Stalker portals from a list, and see which of them still answer.

The reference plugin's StalkerLoaderScreen: it reads a portal list already
on the receiver, can pull a fresh one over the network, checks whether a
portal is alive, and imports the chosen one into the saved servers.

Reached with INFO from the saved-servers picker, which is itself MENU from
the Stalker setup screen.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from ..plugin import config
from ..utils import portalconf, servers, skin as sk
from ..utils.backdrop import backdrop
from ..utils.compat import native
from ..utils.uisafe import safe_actions, BackgroundTask

_c = config.plugins.piip


def build_skin():
    return sk.list_screen(
        'FarsiPortalLoader', 'STALKER - IMPORT PORTALS', 'PIIP',
        buttons=[('IMPORT', sk.BTN_IMPORT),
                 ('LOAD ONLINE', sk.ACCENT_WARM),
                 ('CHECK', sk.BTN_DELETE)],
        hint='OK - Select    EXIT - Back',
        header_widget='status', info=('detail', 'note'), item_height=56,
        backdrop='bg_stalker.png')


class FarsiPortalLoader(Screen):
    """close() returns the imported entry, or None."""

    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.portals = []
        self.task = None

        self['bg'] = Pixmap()
        self['list'] = MenuList([])
        self['status'] = Label('')
        self['detail'] = Label('')
        self['note'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions'],
            safe_actions(self, {
                'ok': self.keyImport,
                'cancel': self.close,
                'green': self.keyImport,
                'yellow': self.keyGetOnline,
                'red': self.keyCheck,
                'up': self.up,
                'down': self.down,
            }), -1)
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.loadLocal)
        self.onClose.append(self.stopTask)

    def stopTask(self):
        """A check or a download outlives this screen otherwise."""
        if self.task is not None:
            self.task.stop()
            self.task = None

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, 'bg_stalker.png')

    # -------------------------------------------------------------- drawing

    def row(self, index, entry):
        return native('Server %02d  %s  |  %s'
                      % (index + 1, portalconf.hostname(entry['portal']),
                         entry['mac']))

    def refresh(self, note=''):
        if self.portals:
            rows = [self.row(i, e) for i, e in enumerate(self.portals)]
        else:
            rows = [native('No portals found')]
        index = self['list'].getSelectedIndex() or 0
        self['list'].setList(rows)
        try:
            self['list'].moveToIndex(min(index, len(rows) - 1))
        except Exception:
            pass
        self['status'].setText(native('%d portal(s)' % len(self.portals)))
        if note:
            self['note'].setText(native(note))
        self.showDetail()

    def showDetail(self):
        entry = self.selected()
        self['detail'].setText(native(entry['portal'] if entry else ''))

    def up(self):
        self['list'].up()
        self.showDetail()

    def down(self):
        self['list'].down()
        self.showDetail()

    def selected(self):
        index = self['list'].getSelectedIndex()
        if index is None or index >= len(self.portals):
            return None
        return self.portals[index]

    # -------------------------------------------------------------- loading

    def loadLocal(self):
        self['note'].setText(native('Checking local file'))
        entries, path = portalconf.load_local()
        self.portals = entries
        if entries:
            self.refresh('Found %d local portals in %s' % (len(entries), path))
        else:
            self.refresh('No local list%s. YELLOW fetches one from %s'
                         % (' in %s' % path if path else '',
                            _c.portal_list_url.value or '(no address set)'))

    def keyGetOnline(self):
        if self.task is not None:
            return
        url = _c.portal_list_url.value
        self['note'].setText(native('Reloading from %s'
                                    % portalconf.hostname(url) or url))
        # Off the UI thread: this is a network fetch on a slow receiver, and
        # an eTimer started from a worker aborts Enigma2 outright.
        self.task = BackgroundTask(self, lambda: portalconf.fetch(url),
                                   self.onDownloaded)
        self.task.start()

    def onDownloaded(self, result, error):
        self.task = None
        if error or result is None:
            self['note'].setText(native('Download error - %s'
                                        % (error or 'no answer')))
            return
        entries, why = result
        if not entries:
            self['note'].setText(native('No portals found - %s' % why))
            return
        self.portals = entries
        self.refresh('Found %d portals online' % len(entries))

    # ------------------------------------------------------------- checking

    def keyCheck(self):
        entry = self.selected()
        if entry is None or self.task is not None:
            return
        self['note'].setText(native('Checking %s...'
                                    % portalconf.hostname(entry['portal'])))
        self.task = BackgroundTask(self, lambda: self.handshake(entry),
                                   self.onChecked)
        self.task.start()

    def handshake(self, entry):
        """True when the portal issues a token for this MAC."""
        from ..providers import stalker
        provider = stalker.Stalker(entry['portal'], entry['mac'],
                                   timeout=12)
        return bool(provider.connect())

    def onChecked(self, result, error):
        self.task = None
        if error:
            self['note'].setText(native('DEAD (ERROR) - %s' % error))
            return
        self['note'].setText(native('WORKING (OK)' if result
                                    else 'DEAD (ERROR)'))

    # ------------------------------------------------------------ importing

    def keyImport(self):
        entry = self.selected()
        if entry is None:
            return
        host = portalconf.hostname(entry['portal'])
        record = {'type': 'stalker', 'name': host,
                  'portal': entry['portal'], 'mac': entry['mac']}
        failure = servers.upsert('stalker', record)
        if failure:
            self['note'].setText(native('Import failed - %s' % failure))
            return
        self['note'].setText(native("Imported '%s'" % host))
        self['status'].setText(native("Imported '%s'" % host))
