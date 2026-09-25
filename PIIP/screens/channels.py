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
"""Channel list: loads the configured source, then plays with translation."""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config, api_key, make_stalker
from ..providers import m3u
from ..providers import epg as epgmod
from ..providers.models import LIVE
from ..providers.xtream import Xtream, XtreamError
from ..providers.stalker import StalkerError
from .player import FarsiPlayer
from .epgscreen import loader_for, catchup_for
from ..utils.uisafe import safe_actions, BackgroundTask
from ..utils import skin as sk
from ..utils import image as image_cache
from ..utils.backdrop import backdrop
from ..utils.compat import native
from ..utils.content import allowed

_c = config.plugins.piip

def build_skin():
    return sk.list_screen(
        'FarsiChannels', 'Live channels', 'PIIP',
        buttons=[('WATCH', sk.BTN_GREEN),
                 ('CATCH-UP', sk.ACCENT_WARM),
                 ('CATEGORY', sk.BTN_BLUE)],
        hint='< > - Category    MENU - Search',
        header_widget='group', info=('now', 'next', 'description', 'status'),
        progress='progress', item_height=60, layout='split',
        detail_logo_widget='logo')


def epg_line(programme):
    """'14:00 - 16:30 (150 min)  Title', as the reference writes it."""
    minutes = int(programme.duration // 60) if programme.duration else 0
    return '%s%s  %s' % (programme.span(),
                         ' (%d min)' % minutes if minutes else '',
                         programme.title)


class FarsiChannels(Screen):

    def __init__(self, session, preloaded=None, group=None, query='',
                 providers=None):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.channels = list(preloaded or [])
        self.preloaded = bool(preloaded)
        self.load_warnings = []
        # The connected client the category screen already made: a list it
        # hands over still needs it to resolve links and read guides.
        providers = providers or {}
        self.stalker = providers.get('stalker')
        self.xtream = providers.get('xtream')
        self.epg_index = None
        self.groups = []
        self.group_index = 0
        # Where the groups screen asked to start.
        self.start_group = native(group) if group else None
        self.page = 0
        self.query = native(query or '').strip()
        self.error = None

        self['bg'] = Pixmap()
        self['list'] = MenuList([])
        self['group'] = Label('')
        self['logo'] = Pixmap()
        self['now'] = Label('')
        self['next'] = Label('')
        self['description'] = Label('')
        from Components.ProgressBar import ProgressBar
        self['progress'] = ProgressBar()
        self['status'] = Label('Loading...')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions', 'ChannelSelectBaseActions'],
            safe_actions(self, {
                'ok': self.play,
                'cancel': self.close,
                'left': self.prevGroup,
                'right': self.nextGroup,
                'up': self.up,
                'down': self.down,
                'red': self.close,
                'yellow': self.openCatchup,
                'blue': self.openCategories,
                'menu': self.openSearch,
                'nextBouquet': self.nextPage,
                'prevBouquet': self.prevPage,
            }), -1)

        # The timer inside BackgroundTask is created and started on the
        # main loop; starting one from the worker aborts Enigma2.
        self.task = BackgroundTask(self, self._load_worker, self._loaded,
                                   'channels')
        self.detail_task = BackgroundTask(self, self._detailWorker,
                                          self._detailReady,
                                          'channel-detail')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.load)
        self.onClose.append(self.task.stop)
        self.onClose.append(self.detail_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self)

    # ------------------------------------------------------------- loading

    def load(self):
        self.task.start()

    def _load_worker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            if self.preloaded:
                self.preloaded = False
            elif _c.source.value in ('stalker', 'xtream'):
                from . import catalogue
                self.channels, providers = catalogue.fetch(catalogue.LIVE)
                self.stalker = providers.get('stalker')
                self.xtream = providers.get('xtream')
            else:
                found, errors = m3u.load_all(_c.m3u_url.value,
                                             user_agent=_c.user_agent.value,
                                             kinds=(LIVE,))
                self.channels = m3u.of_kind(found, LIVE)
                if errors and not found:
                    self.error = 'No playlist loaded: %s' % '; '.join(errors)
                self.load_warnings = errors
            if _c.source.value == 'm3u' and _c.epg_enabled.value:
                self._load_epg()
            self.channels = allowed(self.channels, _c.show_adult.value)
        except XtreamError as e:
            self.error = 'Xtream login failed: %s' % e
        except StalkerError as e:
            detail = str(e)
            if ('Name or service not known' in detail or
                    'Temporary failure in name resolution' in detail):
                self.error = ('Stalker portal error: the portal hostname '
                              'does not exist or DNS cannot resolve it.')
            else:
                self.error = 'Stalker portal error: %s' % e
        except Exception as e:
            self.error = '%s: %s' % (type(e).__name__, e)

    def _loaded(self, _result, error):
        if error and not self.error:
            self.error = error
        self.loaded()

    def _load_epg(self):
        """M3U guides come from an XMLTV file, which is big: cache it."""
        try:
            self.epg_index = epgmod.EPGIndex.load()
            if self.epg_index is not None:
                return
            url = _c.xmltv_url.value.strip()
            if not url:
                return
            wanted = set(c.tvg_id for c in self.channels if c.tvg_id)
            data, _names = epgmod.fetch_xmltv(url, wanted or None,
                                              user_agent=_c.user_agent.value)
            self.epg_index = epgmod.EPGIndex(data)
            self.epg_index.save()
        except Exception:
            self.epg_index = None

    def loaded(self):
        if self.error:
            self['status'].setText(native(self.error))
            self.session.open(MessageBox, native(self.error), MessageBox.TYPE_ERROR,
                              timeout=12)
            return
        if not self.channels:
            self['status'].setText(native('No channels found.'))
            return
        self.groups = ['All'] + m3u.groups(self.channels)
        if _c.source.value == 'm3u' and _c.epg_enabled.value:
            # Walks the bouquets, which only the main loop may do; the
            # guide lookups that use it then run on the detail worker.
            from ..utils import e2epg
            e2epg.prepare()
        if self.start_group in self.groups:
            self.group_index = self.groups.index(self.start_group)
        self.start_group = None
        self.showGroup()

    # -------------------------------------------------------------- display

    def current_group(self):
        return self.groups[self.group_index] if self.groups else 'All'

    def visible(self):
        g = self.current_group()
        values = (self.channels if g == 'All' else
                  [c for c in self.channels if (c.group or 'Ungrouped') == g])
        if self.query:
            values = [c for c in values if self.query.lower() in c.name.lower()]
        size = max(1, int(_c.poster_count.value or 20))
        start = self.page * size
        return values[start:start + size]

    def filteredCount(self):
        g = self.current_group()
        values = (self.channels if g == 'All' else
                  [c for c in self.channels if (c.group or 'Ungrouped') == g])
        if self.query:
            values = [c for c in values if self.query.lower() in c.name.lower()]
        return len(values)

    def showGroup(self):
        chans = self.visible()
        self['list'].setList([c.label() for c in chans])
        self['group'].setText(native('%s  (%d/%d)' % (
            self.current_group(), self.group_index + 1, len(self.groups))))
        key_available = bool(api_key())
        translating = bool(_c.translate.value and key_available)
        size = max(1, int(_c.poster_count.value or 20))
        total = self.filteredCount()
        pages = max(1, (total + size - 1) // size)
        self['status'].setText(native(
            '%d channels   |   page %d/%d   |   translation: %s'
            % (total, self.page + 1, pages, 'on (%s)' % _c.language.value
               if translating else ('off' if key_available else
                                    'off — no API key found'))))
        self.updateDetails()

    def up(self):
        self['list'].up()
        self.updateDetails()

    def down(self):
        self['list'].down()
        self.updateDetails()

    def currentItem(self):
        shown = self.visible()
        idx = self['list'].getSelectedIndex()
        return shown[idx] if shown and idx is not None and idx < len(shown) else None

    def updateDetails(self):
        item = self.currentItem()
        self.detail_item = item
        self['now'].setText('')
        self['next'].setText('')
        self['description'].setText('')
        self['progress'].setValue(0)
        try:
            self['logo'].hide()
        except Exception:
            pass
        if item and not self.detail_task.running():
            self.detail_task.start()

    def _detailWorker(self):
        import time
        item = self.detail_item
        programmes = []
        if item:
            loader = loader_for(item, _c.source.value, stalker=self.stalker,
                                xtream=self.xtream, index=self.epg_index)
            try:
                programmes = list(loader())
            except Exception:
                programmes = []
        logo = ''
        if item and item.logo:
            try:
                logo = image_cache.download(item.logo,
                    native(_c.picon_cache_dir.value or '/tmp/piip-cache'),
                    timeout=10)
            except Exception:
                logo = ''
        return item, programmes, logo, int(time.time())

    def _detailReady(self, result, error):
        if error or not result:
            return
        item, programmes, logo, now = result
        if item is not self.currentItem():
            self.updateDetails()
            return
        current = upcoming = None
        for programme in programmes:
            if programme.running_at(now):
                current = programme
            elif programme.start > now and upcoming is None:
                upcoming = programme
        if not programmes:
            self['now'].setText(native('No EPG available'))
        if current:
            self['now'].setText(native('NOW: %s' % epg_line(current)))
            # One line of room beside the list: a longer text is clipped
            # half-way through its second line, over the status.
            desc = ' '.join((current.desc or '').split())
            if len(desc) > 95:
                desc = desc[:92].rstrip() + '...'
            self['description'].setText(native(desc))
            self['progress'].setValue(current.progress_at(now))
        if upcoming:
            self['next'].setText(native('NEXT: %s' % epg_line(upcoming)))
        if logo:
            from ..utils.backdrop import load_path
            load_path(self, 'logo', logo)

    def nextGroup(self):
        if self.groups:
            self.group_index = (self.group_index + 1) % len(self.groups)
            self.page = 0
            self.showGroup()

    def prevGroup(self):
        if self.groups:
            self.group_index = (self.group_index - 1) % len(self.groups)
            self.page = 0
            self.showGroup()

    def openCategories(self):
        if not self.groups:
            return
        try:
            from Screens.ChoiceBox import ChoiceBox
            choices = [(native(name), index)
                       for index, name in enumerate(self.groups)]
            self.session.openWithCallback(self.categoryPicked, ChoiceBox,
                                          title='Categories', list=choices)
        except ImportError:
            pass

    def categoryPicked(self, choice=None):
        if not choice:
            return
        try:
            self.group_index = int(choice[1])
        except (TypeError, ValueError, IndexError):
            return
        self.page = 0
        self.showGroup()

    def nextPage(self):
        size = max(1, int(_c.poster_count.value or 20))
        pages = max(1, (self.filteredCount() + size - 1) // size)
        self.page = (self.page + 1) % pages
        self.showGroup()

    def prevPage(self):
        size = max(1, int(_c.poster_count.value or 20))
        pages = max(1, (self.filteredCount() + size - 1) // size)
        self.page = (self.page - 1) % pages
        self.showGroup()

    def openSearch(self):
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
            self.session.openWithCallback(self.searchDone, VirtualKeyBoard,
                                          title='Search', text=self.query)
        except ImportError:
            return

    def searchDone(self, text=None):
        if text is None:
            return
        self.query = native(text).strip()
        self.page = 0
        self.showGroup()

    # ----------------------------------------------------------------- play

    def play(self):
        chans = self.visible()
        idx = self['list'].getSelectedIndex()
        if not chans or idx is None or idx >= len(chans):
            return
        item = chans[idx]
        if self.stalker is not None and not item.url:
            # Stalker links are created on demand and expire quickly, so this
            # has to happen now rather than at load time.
            self['status'].setText(native('Resolving link...'))
            try:
                self.stalker.resolve(item)
            except Exception as e:
                self.session.open(MessageBox,
                                  native('Could not get a playable link:\n%s' % e),
                                  MessageBox.TYPE_ERROR, timeout=10)
                self.showGroup()
                return
        loader, guide, catcher = self.guideFor(item)
        # The player gets the visible list so channels can be changed
        # without coming back here, and the factory so each channel it
        # moves to gets its own guide.
        resolver = self.stalker.resolve if self.stalker is not None else None
        self.session.open(FarsiPlayer, item, epg_loader=loader,
                          channels=chans, index=idx, resolver=resolver,
                          catchup=catcher, guide_loader=guide,
                          epg_factory=self.guideFor)

    def guideFor(self, item):
        """(now/next loader, full guide loader, catch-up) for one channel."""
        if not _c.epg_enabled.value:
            return None, None, None
        source = _c.source.value
        loader = loader_for(item, source, stalker=self.stalker,
                            xtream=self.xtream, index=self.epg_index)
        guide = loader_for(item, source, stalker=self.stalker,
                           xtream=self.xtream, index=self.epg_index,
                           full=True)
        catcher = catchup_for(item, source, stalker=self.stalker,
                              xtream=self.xtream)
        return loader, guide, catcher

    # -------------------------------------------------------------- catch-up

    def openCatchup(self):
        """The channel's guide, past programmes included, straight from the list.

        OK on a finished programme there plays the portal's recording.
        """
        item = self.currentItem()
        if item is None:
            return
        catcher = catchup_for(item, _c.source.value, stalker=self.stalker,
                              xtream=self.xtream)
        # Stalker and Xtream say per channel whether they keep recordings;
        # asking for an archive that does not exist only ends in an error.
        if catcher is None or not item.archive:
            self.session.open(MessageBox,
                              native('Catchup is not available for this channel.'),
                              MessageBox.TYPE_INFO, timeout=6)
            return
        loader = loader_for(item, _c.source.value, stalker=self.stalker,
                            xtream=self.xtream, index=self.epg_index,
                            full=True)
        from .epgscreen import FarsiEPG
        self.session.open(FarsiEPG, item, loader, catcher, catchup_mode=True)
