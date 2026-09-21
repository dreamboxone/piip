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
"""Export the current source into an Enigma2 bouquet, and into EPGImport."""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config, api_key, make_stalker
from ..providers import m3u
from ..providers.models import LIVE
from ..providers.xtream import Xtream, XtreamError
from ..translate import resolver
from ..utils import bouquet
from ..utils.backdrop import backdrop
from ..utils import epgexport
from ..utils.uisafe import safe_actions, BackgroundTask
from ..utils import skin as sk
from ..utils.compat import native

_c = config.plugins.piip

def build_skin():
    return sk.list_screen(
        'FarsiBouquets', 'Bouquets', 'PIIP',
        buttons=[('RUN', sk.BTN_GREEN)],
        hint='OK - Run    EXIT - Back',
        header_widget='head', info=('info', 'status'), item_height=54,
        layout='summary')

ACTIONS = [
    ('Export current source to a bouquet', 'export'),
    ('Export guide data to EPGImport', 'epg'),
    ('Toggle translated audio in bouquets', 'toggle'),
    ('Reload Enigma2 channel list', 'reload'),
    ('Remove exported bouquets', 'remove'),
]


class FarsiBouquets(Screen):

    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.busy = False
        self.result = None
        self.error = None

        self['bg'] = Pixmap()
        self['head'] = Label('Bouquets')
        self['list'] = MenuList([label for label, _ in ACTIONS])
        self['info'] = Label('')
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions'],
            safe_actions(self, {'ok': self.select, 'cancel': self.close, 'red': self.close}), -1)

        self.task = BackgroundTask(self, self._worker, self._finished,
                                   'bouquet-export')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.refresh)
        self.onClose.append(self.task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self)

    # -------------------------------------------------------------- display

    def refresh(self):
        exported = bouquet.list_exported()
        entries = len(bouquet.load_map())
        self['info'].setText(native(
            'Source: %s\n'
            'Translated audio in bouquets: %s\n'
            'Resolver: %s on port %d\n'
            'Exported bouquets: %s\n'
            'Mapped channels: %d\n'
            'EPGImport: %s'
            % (_c.source.value,
               'yes' if _c.bouquet_translate.value else 'no',
               'running' if resolver.running() else 'NOT RUNNING',
               int(_c.resolver_port.value),
               ', '.join(exported) if exported else 'none',
               entries,
               'available' if epgexport.available() else 'not installed')))
        if _c.bouquet_translate.value and not api_key():
            self['status'].setText(native(
                'Translated bouquets need an API key — none found.'))
        else:
            self['status'].setText(native(''))

    def select(self):
        if self.busy:
            return
        idx = self['list'].getSelectedIndex()
        if idx is None:
            return
        action = ACTIONS[idx][1]
        if action == 'export':
            self.startExport()
        elif action == 'epg':
            self.exportEPG()
        elif action == 'toggle':
            _c.bouquet_translate.value = not _c.bouquet_translate.value
            _c.bouquet_translate.save()
            self.refresh()
        elif action == 'reload':
            how = bouquet.reload_services()
            self.session.open(MessageBox, native('Channel list reload: %s' % how),
                              MessageBox.TYPE_INFO, timeout=8)
        elif action == 'remove':
            self.removeAll()

    # -------------------------------------------------------------- loading

    def _load(self):
        src = _c.source.value
        if src == 'stalker':
            s = make_stalker()
            s.connect()
            return s.channels(), 'stalker'
        if src == 'xtream':
            x = Xtream(_c.xtream_host.value, _c.xtream_user.value,
                       _c.xtream_pass.value, user_agent=_c.user_agent.value)
            x.login()
            return x.all_live(), 'xtream'
        found, _errors = m3u.load_all(_c.m3u_url.value,
                                      user_agent=_c.user_agent.value,
                                      kinds=(LIVE,))
        return m3u.of_kind(found, LIVE), 'm3u'

    # --------------------------------------------------------------- export

    def startExport(self):
        if _c.bouquet_translate.value and not resolver.running():
            self.session.open(
                MessageBox,
                native('The resolver is not running, so bouquet entries would not '
                'play.\n\nRestart Enigma2 and try again.'),
                MessageBox.TYPE_ERROR, timeout=12)
            return
        self.busy = True
        self.result = self.error = None
        self['status'].setText(native('Loading channels...'))
        self.task.start()

    def _worker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            items, provider = self._load()
            if not items:
                self.error = 'No channels found to export.'
            else:
                self.result = bouquet.export(
                    items,
                    title='PIIP — %s' % provider.title(),
                    provider=provider,
                    resolver_port=int(_c.resolver_port.value),
                    translate=bool(_c.bouquet_translate.value),
                    service_type=int(_c.service_type.value),
                    slug=provider)
        except XtreamError as e:
            self.error = 'Xtream error: %s' % e
        except Exception as e:
            self.error = '%s: %s' % (type(e).__name__, e)

    def _finished(self, _result, error):
        if error and not self.error:
            self.error = error
        self.done()

    def done(self):
        self.busy = False
        if self.error:
            self['status'].setText(native(self.error))
            self.session.open(MessageBox, native(self.error), MessageBox.TYPE_ERROR,
                              timeout=12)
            return
        r = self.result or {}
        how = bouquet.reload_services()
        self.refresh()
        self.session.open(
            MessageBox,
            native('Exported %d channels to %s\n'
            'Added to bouquets.tv: %s\n'
            'Translated audio: %s\n'
            'Channel list reload: %s'
            % (r.get('count', 0), r.get('filename', '?'),
               'yes' if r.get('registered') else 'already there',
               'yes' if r.get('translated') else 'no', how)),
            MessageBox.TYPE_INFO, timeout=15)

    # ------------------------------------------------------------ epgimport

    def exportEPG(self):
        if not epgexport.available():
            self.session.open(
                MessageBox,
                native('EPGImport is not installed on this receiver.\n\n'
                'Install the EPGImport plugin first. The guide inside '
                'PIIP works without it.'),
                MessageBox.TYPE_ERROR, timeout=12)
            return
        try:
            items, provider = self._load()
        except Exception as e:
            self.session.open(MessageBox, native('Could not load channels: %s' % e),
                              MessageBox.TYPE_ERROR, timeout=12)
            return

        _data, keys = bouquet.build_map(items, provider,
                                        bool(_c.bouquet_translate.value))
        res = epgexport.export(items, int(_c.resolver_port.value),
                               xmltv_url=_c.xmltv_url.value.strip(),
                               service_type=int(_c.service_type.value),
                               keys=keys)
        if not res.get('ok'):
            self.session.open(MessageBox, native(res.get('error', 'Export failed.')),
                              MessageBox.TYPE_ERROR, timeout=12)
            return
        self.refresh()
        self.session.open(
            MessageBox,
            native('Guide export written.\n'
            'Channels mapped: %d\n'
            'Skipped (no XMLTV id): %d\n'
            'Sources file: %s\n\n'
            'Now run EPGImport to pull the data in.'
            % (res['mapped'], res['skipped'],
               res['sources'] or 'not written (no XMLTV URL set)')),
            MessageBox.TYPE_INFO, timeout=20)

    # --------------------------------------------------------------- remove

    def removeAll(self):
        self.session.openWithCallback(
            self.removeConfirmed, MessageBox,
            native('Remove every bouquet this plugin created?'),
            MessageBox.TYPE_YESNO, default=False)

    def removeConfirmed(self, answer):
        if not answer:
            return
        removed = 0
        for filename in bouquet.list_exported():
            if bouquet.unregister(filename):
                removed += 1
        bouquet.save_map({})
        epgexport.remove()
        how = bouquet.reload_services()
        self.refresh()
        self.session.open(MessageBox,
                          native('Removed %d bouquets.\nChannel list reload: %s'
                          % (removed, how)),
                          MessageBox.TYPE_INFO, timeout=10)
