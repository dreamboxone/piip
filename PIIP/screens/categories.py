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
"""The categories of a server's live TV, films or series.

The reference plugin opens this between its server menu and a list: the
categories with their counts ("LATEST ADDED" first for films and series),
0 to search everything, MENU to turn a live category into a bouquet and
the database button to refresh the offline copy. OK opens the list on that
category, and < > still move between categories inside it.
"""

import os
import re

from Components.ActionMap import ActionMap, NumberActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from . import catalogue
from .m3ugroups import folder_list_skin, E2ListSource
from ..plugin import config
from ..providers import m3u
from ..providers.xtream import LATEST
from ..utils import skin as sk
from ..utils.backdrop import backdrop, ICONS
from ..utils.compat import native
from ..utils.content import allowed
from ..utils.uisafe import safe_actions, BackgroundTask

_c = config.plugins.piip

ALL_CHANNELS = 'All channels'
TITLES = {catalogue.LIVE: 'LIVE TV', catalogue.MOVIES: 'MOVIES',
          catalogue.SERIES: 'SERIES'}
SEARCH_PROMPTS = {catalogue.LIVE: 'Search Live TV:',
                  catalogue.MOVIES: 'Search Movies:',
                  catalogue.SERIES: 'Search Series:'}


def first_row(kind):
    return ALL_CHANNELS if kind == catalogue.LIVE else LATEST


def category_rows(kind, items):
    """[(category, count)]: everything first, then each category in order."""
    counts = {}
    for item in items:
        name = item.group or 'Ungrouped'
        counts[name] = counts.get(name, 0) + 1
    return [(first_row(kind), len(items))] + [(g, counts[g])
                                              for g in m3u.groups(items)]


def build_skin(kind, source):
    title = '%s %s CATEGORIES' % (native(source).upper(), TITLES[kind])
    # Only an Xtream catalogue is kept offline; elsewhere blue reloads.
    blue = 'SYNC DB' if source == 'xtream' else 'RELOAD'
    return folder_list_skin(
        'FarsiCategories', title,
        buttons=[('BACK', sk.BTN_RED), ('OPEN', sk.BTN_GREEN),
                 (blue, sk.BTN_BLUE)],
        # The reference's "0 - Search  OK - Select  MENU - Bouquet  EXIT -
        # Back" does not fit the key-hint tab; OK and EXIT are on every
        # screen and the chips already name them.
        hint=('0 - Search    MENU - Bouquet' if kind == catalogue.LIVE
              else '0 - Search    OK - Open'),
        backdrop='bg_%s.png' % source)


class FarsiCategories(Screen):

    def __init__(self, session, kind=catalogue.LIVE):
        self.kind = kind if kind in catalogue.KINDS else catalogue.LIVE
        self.source = native(_c.source.value or 'xtream')
        self.skin = build_skin(self.kind, self.source)
        Screen.__init__(self, session)
        self.session = session
        self.channels = []
        self.providers = {}
        self.rows = []
        self.category_ids = {}
        self.total = 0
        self.paged = catalogue.paged(self.kind, self.source)
        self.error = None
        self.notice = ''
        self.syncing = False
        self.rich = E2ListSource is not None

        self['bg'] = Pixmap()
        self['list'] = E2ListSource([]) if self.rich else MenuList([])
        self['head'] = Label('')
        self['status'] = Label('Loading categories')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions'],
            safe_actions(self, {
                'ok': self.open,
                'green': self.open,
                'cancel': self.close,
                'red': self.close,
                'blue': self.syncDatabase,
                'menu': self.openMenuOptions,
                'up': self.up,
                'down': self.down,
            }), -1)
        self['numbers'] = NumberActionMap(
            ['NumberActions'], safe_actions(self, {'0': self.openSearch}), -1)

        self.task = BackgroundTask(self, self._loadWorker, self._loaded,
                                   'categories')
        self.export_task = BackgroundTask(self, self._exportWorker,
                                          self._exported, 'category-bouquet')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.load)
        self.onClose.append(self.task.stop)
        self.onClose.append(self.export_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, 'bg_%s.png' % self.source)

    # ------------------------------------------------------------ loading

    def load(self):
        if not self.task.running():
            self.task.start()

    def _loadWorker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        self.error, self.notice = None, ''
        if self.paged:
            try:
                rows, ids, providers = catalogue.fetch_categories(self.kind)
            except Exception as exc:
                self.error = catalogue.error_text(exc)
                return [], {}, [], {}
            return [], providers, rows, ids
        try:
            items, providers = catalogue.fetch(self.kind, self.source)
            saved = catalogue.save(self.kind, items)
            if self.syncing:
                self.notice = ('Database Sync Successful!' if saved
                               else 'Sync Error: nothing to save')
        except Exception as exc:
            items, providers = catalogue.load_saved(self.kind), {}
            if items:
                self.notice = 'Offline catalogue (%s)' % catalogue.error_text(exc)
            else:
                self.error = catalogue.error_text(exc)
                if self.syncing:
                    self.error = 'Sync Error: %s' % self.error
        items = allowed(items or [], _c.show_adult.value)
        return items, providers, category_rows(self.kind, items), {}

    def _loaded(self, result, error):
        syncing, self.syncing = self.syncing, False
        if error and not self.error:
            self.error = native(error)
        if self.error:
            self['status'].setText(native(self.error))
            self.session.open(MessageBox, native(self.error),
                              MessageBox.TYPE_ERROR, timeout=12)
            return
        self.channels, self.providers, self.rows, self.category_ids = result
        self.total = self.rows[0][1] if self.rows else 0
        self.refresh()
        if syncing and self.notice:
            self.session.open(MessageBox, native(self.notice),
                              MessageBox.TYPE_INFO, timeout=6)

    # ------------------------------------------------------------ drawing

    def _folder(self):
        try:
            from Tools.LoadPixmap import LoadPixmap
            return LoadPixmap(os.path.join(ICONS, 'folder.png'))
        except Exception:
            return None

    def refresh(self):
        if self.rich:
            folder = self._folder()
            self['list'].setList([(native(name), native(str(count)), folder)
                                  for name, count in self.rows])
        else:
            self['list'].setList([native('%s   (%s)' % (name, count)
                                         if count != '' else name)
                                  for name, count in self.rows])
        found = len(self.rows) - 1
        self['head'].setText(native(
            '%d category found' % found if found == 1
            else '%d category(s) found' % found))
        self.updateFooter()

    def updateFooter(self):
        parts = ['%s %s' % (self.total,
                            'channels' if self.kind == catalogue.LIVE
                            else 'items')]
        if self.source == 'xtream':
            when = catalogue.saved_at(self.kind)
            parts.append('Offline DB: %s' % (when or 'none - BLUE saves it'))
        if self.notice and 'Offline' in self.notice:
            parts.append(self.notice)
        self['status'].setText(native('   |   '.join(parts)))

    # ------------------------------------------------------------- moving

    def index(self):
        widget = self['list']
        try:
            return int(widget.index)
        except Exception:
            try:
                return int(widget.getSelectedIndex() or 0)
            except Exception:
                return 0

    def move(self, delta):
        if not self.rows:
            return
        target = (self.index() + delta) % len(self.rows)
        widget = self['list']
        for setter in ('selectIndex', 'moveToIndex', 'setIndex'):
            fn = getattr(widget, setter, None)
            if fn is not None:
                try:
                    fn(target)
                    return
                except Exception:
                    continue
        try:
            widget.index = target
        except Exception:
            pass

    def up(self):
        self.move(-1)

    def down(self):
        self.move(1)

    def selectedCategory(self):
        idx = self.index()
        if not self.rows or not 0 <= idx < len(self.rows):
            return None
        return self.rows[idx][0]

    # ------------------------------------------------------------ opening

    def open(self, query=''):
        name = self.selectedCategory()
        if name is None or self.task.running():
            return
        group = None if name == first_row(self.kind) else name
        self.openList(group, query, self.category_ids.get(name))

    def openList(self, group=None, query='', category_id=None):
        if self.kind == catalogue.LIVE:
            from .channels import FarsiChannels
            self.session.open(FarsiChannels, self.channels, group=group,
                              query=query, providers=self.providers)
            return
        from .vod import FarsiMovies, FarsiSeries
        screen = FarsiMovies if self.kind == catalogue.MOVIES else FarsiSeries
        if self.paged:
            self.session.open(screen, group=group, query=query,
                              providers=self.providers,
                              category_id=category_id or '*')
            return
        self.session.open(screen, preloaded=self.channels, group=group,
                          query=query, providers=self.providers)

    def openSearch(self):
        if not self.rows:
            return
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
        except ImportError:
            return
        self.session.openWithCallback(self.searched, VirtualKeyBoard,
                                      title=SEARCH_PROMPTS[self.kind], text='')

    def searched(self, text=None):
        text = native(text or '').strip()
        if text:
            self.openList(None, text)

    # ------------------------------------------------------------ syncing

    def syncDatabase(self):
        if self.task.running():
            return
        self.syncing = True
        self['status'].setText(native(
            'Sync: Fetching Streams... (This may take a few minutes)'))
        self.task.start()

    # ------------------------------------------------------------ bouquet

    def openMenuOptions(self):
        name = self.selectedCategory()
        if name is None:
            return
        if self.kind != catalogue.LIVE:
            self.session.open(
                MessageBox,
                native('Bouquet export is only allowed for Live TV categories.'),
                MessageBox.TYPE_INFO, timeout=6)
            return
        self.export_name = name
        self.session.openWithCallback(
            self._onMenuConfirm, MessageBox,
            native("Do you want to add the category '%s' to Enigma2 as a "
                   "favorite bouquet?" % name), MessageBox.TYPE_YESNO)

    def _onMenuConfirm(self, confirmed=False):
        if not confirmed or self.export_task.running():
            return
        self['status'].setText(native("Exporting category '%s' to bouquets..."
                                      % self.export_name))
        self.export_task.start()

    def categoryItems(self, name):
        if name == first_row(self.kind):
            return list(self.channels)
        return [c for c in self.channels if (c.group or 'Ungrouped') == name]

    def _exportWorker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        from ..utils import bouquet
        name = self.export_name
        items = self.categoryItems(name)
        if not items:
            raise ValueError('No streams found in this category.')
        slug = '%s_%s' % (self.source, re.sub(r'\W+', '_', name.lower()).strip('_'))
        return bouquet.export(
            items, title='PIIP - %s' % name, provider=self.source,
            resolver_port=int(_c.resolver_port.value),
            translate=bool(_c.bouquet_translate.value),
            service_type=int(_c.service_type.value), slug=slug)

    def _exported(self, result, error):
        self.updateFooter()
        if error or not result:
            self.session.open(MessageBox,
                              native('Failed to export: %s' % (error or '?')),
                              MessageBox.TYPE_ERROR, timeout=10)
            return
        from ..utils import bouquet
        how = bouquet.reload_services()
        self.session.open(
            MessageBox,
            native("Category '%s' added to bouquets.\n%d channels in %s\n"
                   "Channel list reload: %s"
                   % (self.export_name, result.get('count', 0),
                      result.get('filename', '?'), how)),
            MessageBox.TYPE_INFO, timeout=10)
