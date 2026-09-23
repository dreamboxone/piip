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
"""Browsing screens for movies and series.

Playback itself is the same FarsiPlayer used for live channels — recorded
content only differs in how ffmpeg reads it, which the engine handles.
"""

import os

from enigma import eTimer

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
try:
    from Components.Sources.List import List as E2ListSource
except ImportError:                                  # test/development stub
    E2ListSource = None
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config, api_key, make_stalker
from ..providers import m3u
from ..providers.models import MediaItem, MOVIE, EPISODE, SERIES, human_duration
from ..providers.xtream import Xtream, XtreamError
from ..utils import resume as resume_store
from ..utils.backdrop import backdrop
from .player import FarsiPlayer
from ..utils.uisafe import safe_actions, BackgroundTask
from ..utils import skin as sk
from ..utils.compat import native
from ..utils.content import allowed
from ..utils import downloads
from ..utils import tmdb
from ..utils import image as image_cache
from ..utils import sqldb

_c = config.plugins.piip

def build_skin(title='PIIP'):
    style = _c.skin_style.value
    if style in ('cover', 'cover2d'):
        return build_grid_skin(title)
    layout = 'cover' if style in ('cover', 'cover2d') else 'split'
    return sk.list_screen(
        'FarsiVOD', title, 'PIIP',
        buttons=[('BACK', sk.BTN_RED), ('PLAY', sk.BTN_GREEN),
                 ('DOWNLOAD', sk.ACCENT_WARM), ('DOWNLOADS', sk.BTN_BLUE)],
        hint='MENU - Search    CH+/- - Page',
        header_widget='head', info=('plot', 'status'), item_height=60,
        layout=layout, artwork=True)


def build_grid_skin(title='PIIP'):
    """Hybrid's native multi-column poster grid, with a safe stretch lookup.

    DreamOS exposes SCALE_STRETCH from ``enigma`` but its old
    TemplatedMultiContent converter forgets to import it into the eval scope.
    Resolving it explicitly preserves the original renderer without patching
    the receiver's system files.
    """
    width = sk.desktop_width()
    W, H = ((2560, 1440) if width >= 2560 else
            ((1920, 1080) if width >= 1920 else (1280, 720)))
    f = W / 1920.0
    q = lambda value: int(round(value * f))
    item_w, item_h = q(266), q(435)
    poster_x, poster_y = q(7), q(20)
    poster_w, poster_h = q(242), q(357)
    title_y, title_h = q(395), q(30)
    badge_x, badge_y, badge_w, badge_h = q(181), q(20), q(58), q(48)
    template = '''{
      "templates": {"default": (%d, [
        MultiContentEntryText(pos=(%d,%d), size=(%d,%d), flags=RT_HALIGN_CENTER|RT_VALIGN_CENTER|RT_WRAP, text=0%s),
        MultiContentEntryPixmapAlphaTest(pos=(%d,%d), size=(%d,%d), png=8%s),
        MultiContentEntryPixmapAlphaTest(pos=(%d,%d), size=(%d,%d), png=9%s)
      ])},
      "fonts": [gFont("Regular",%d)], "itemHeight": %d, "itemWidth": %d
    }''' % (item_h, q(3), title_y, q(240), title_h,
             sk.template_color('white'),
             poster_x, poster_y, poster_w, poster_h, sk.template_scale(),
             badge_x, badge_y, badge_w, badge_h, sk.template_scale(),
             q(22), item_h, item_w)
    body = [
        '<widget name="bg" scale="stretch" position="0,0" size="%d,%d" zPosition="0"/>' % (W, H),
        '<eLabel position="0,0" size="%d,%d" backgroundColor="#95000000" zPosition="-1"/>' % (W, H),
        '<widget name="head" position="%d,%d" size="%d,%d" font="Regular;%d" halign="left" foregroundColor="%s" transparent="1" zPosition="1"/>' % (q(40), q(15), q(1100), q(40), q(32), sk.ACCENT),
        '<widget name="status" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" foregroundColor="%s" transparent="1" zPosition="1"/>' % (q(1140), q(15), q(740), q(40), q(28), sk.TEXT),
        '<eLabel position="0,%d" size="%d,%d" backgroundColor="%s"/>' % (q(65), W, q(3), sk.ACCENT),
        '<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showNever" backgroundColor="#00000000" selectionEnabled="1" mode="grid" enableWrapAround="1" selectionZoom="1.05" selectionRadius="20" margin="%d,%d" transparent="1">\n<convert type="TemplatedMultiContent">%s</convert>\n</widget>' % (q(10), q(80), q(1884), q(890), q(7), q(7), template),
        # Components retained invisibly so the shared behaviour stays valid.
        '<widget name="plot" position="0,0" size="1,1" transparent="1"/>',
        '<widget name="rating" position="0,0" size="1,1" transparent="1"/>',
        '<widget name="poster" position="0,0" size="1,1" transparent="1"/>',
        '<widget name="art" position="0,0" size="1,1" transparent="1"/>',
        '<eLabel position="0,%d" size="%d,%d" backgroundColor="#1e5799"/>' % (q(980), W, q(2)),
        sk.chip('Download', q(40), q(1006), sk.BTN_RED, q(260), q(56), font=q(24), wide=True),
        sk.chip('Next Page', q(320), q(1006), sk.BTN_GREEN, q(260), q(56), font=q(24), wide=True),
        sk.chip('Prev Page', q(600), q(1006), sk.ACCENT_WARM, q(260), q(56), font=q(24), wide=True, fg='#1a1a1a'),
        sk.chip('Downloads', q(880), q(1006), sk.BTN_BLUE, q(260), q(56), font=q(24), wide=True, fg='#1a1a1a'),
        sk.pill('OK - Play    EXIT - Back', q(1540), q(1010), q(340), q(50), font=q(24), wide=True),
    ]
    return sk.dialog('FarsiVOD', '\n  '.join(body), width=W, height=H,
                     wide=True, ground=sk.OPAQUE)


def make_xtream():
    return Xtream(_c.xtream_host.value, _c.xtream_user.value,
                  _c.xtream_pass.value, user_agent=_c.user_agent.value)


class LoadingScreen(Screen):
    """Common shell: loads something in a thread, then renders a list."""

    title_text = 'PIIP'
    # Films and series from a server open on the reference's first
    # category, the whole catalogue newest first.
    LATEST_FIRST = False

    # 'movies' or 'series': what a paged Stalker category holds.
    CATALOGUE_KIND = None

    def __init__(self, session, preloaded=None, group=None, query='',
                 providers=None, category_id=None):
        self.skin = build_skin(getattr(self, 'title_text', 'PIIP'))
        Screen.__init__(self, session)
        self.session = session
        self.error = None
        self.cache_notice = ''
        # Handed over by the category screen: the catalogue it loaded, the
        # category to start on and the client it connected with.
        self.catalogue_items = (list(preloaded) if preloaded is not None
                                else None)
        self.start_group = native(group) if group else None
        providers = providers or {}
        self.stalker = providers.get('stalker')
        self.xtream = providers.get('xtream')
        self._vod_names = providers.get('vod_names') or {}
        # A paged Stalker category: its items arrive a server page at a
        # time, the next pages only when the list reaches them.
        self.providers = providers
        self.category_id = category_id
        self.paged = category_id is not None and self.stalker is not None
        self.remote_total = 0
        self.remote_next = 1
        self.remote_done = False
        self._pending_page = None
        # Not self.items: Screen subclasses dict, and Enigma2 skins a screen
        # by iterating self.items(). Shadowing that method crashes the box.
        self.entries = []
        self.groups = []
        self.group_index = 0
        self.page = 0
        self.query = native(query or '').strip()
        # ids the portal itself matched for self.query (Stalker search);
        # they are shown even when the name alone would not match.
        self.search_hits = set()
        self._search_query = ''
        self.grid_mode = _c.skin_style.value in ('cover', 'cover2d')

        self['bg'] = Pixmap()
        self['list'] = (E2ListSource([], enableWrapAround=True)
                        if self.grid_mode and E2ListSource is not None
                        else MenuList([]))
        self['head'] = Label(self.title_text)
        self['plot'] = Label('')
        self['rating'] = Label('')
        self['poster'] = Pixmap()
        self['art'] = Pixmap()
        self['status'] = Label('Loading...')
        actions = {
                'ok': self.select,
                'cancel': self.close,
                'menu': self.openSearch,
                'info': self.openCategories,
                'showEventInfo': self.openCategories,
                'nextBouquet': self.nextPage,
                'prevBouquet': self.prevPage,
        }
        if self.grid_mode:
            actions.update({
                'left': self.moveLeft,
                'right': self.moveRight,
                'up': self.moveGridUp,
                'down': self.moveGridDown,
                'red': self.downloadSelected,
                'green': self.nextPage,
                'yellow': self.prevPage,
                'blue': self.openDownloads,
            })
        else:
            actions.update({
                'left': self.prevGroup,
                'right': self.nextGroup,
                'up': self.moveUp,
                'down': self.moveDown,
                'red': self.close,
                'yellow': self.downloadSelected,
                'blue': self.openDownloads,
            })
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions', 'ChannelSelectBaseActions', 'InfobarEPGActions'],
            safe_actions(self, actions), -1)

        # See BackgroundTask: an eTimer may only be started by the thread
        # that created it, which is the Enigma2 main loop.
        self.task = BackgroundTask(self, self._worker, self._loaded, 'vod')
        self.art_task = BackgroundTask(self, self._art_worker,
                                       self._art_ready, 'vod-art')
        self.page_art_task = BackgroundTask(self, self._pageArtWorker,
                                            self._pageArtReady,
                                            'vod-grid-art')
        self._page_art_token = 0
        self._art_token = 0
        self._pending_art = (0, None, {})
        try:
            self['list'].onSelectionChanged.append(self.updateDetails)
        except Exception:
            pass
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.load)
        self.onClose.append(self.task.stop)
        self.onClose.append(self.art_task.stop)
        self.onClose.append(self.page_art_task.stop)
        self.search_task = BackgroundTask(self, self._searchWorker,
                                          self._searchReady, 'vod-search')
        self.onClose.append(self.search_task.stop)
        self.more_task = BackgroundTask(self, self._moreWorker,
                                        self._moreReady, 'vod-more')
        self.onClose.append(self.more_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        source = native(_c.source.value or '')
        backdrop(self, ('bg_%s.png' % source
                        if source in ('m3u', 'xtream', 'stalker')
                        else 'bg_list.png'))

    # ------------------------------------------------------------- loading

    def load(self):
        self.task.start()

    def _worker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            self.entries = allowed(self.fetch(), _c.show_adult.value)
            if _c.tmdb_key.value.strip():
                limit = int(_c.poster_count.value or 20)
                for item in self.entries[:limit]:
                    if item.kind in (MOVIE, SERIES):
                        try:
                            tmdb.enrich(item, _c.tmdb_key.value.strip())
                        except Exception:
                            pass
            if self.catalogue_items is None:
                # The category screen already saved what it hands over.
                self._save_catalogue()
        except XtreamError as e:
            if not self._load_catalogue():
                self.error = 'Xtream error: %s' % e
            else:
                self.cache_notice = 'Offline catalogue'
        except Exception as e:
            if not self._load_catalogue():
                self.error = '%s: %s' % (type(e).__name__, e)
            else:
                self.cache_notice = 'Offline catalogue'

    def _db_identity(self):
        return '%s|%s' % (_c.xtream_host.value, _c.xtream_user.value)

    def _save_catalogue(self):
        """Mirror Hybrid's category database after a successful Xtream load."""
        if _c.source.value != 'xtream' or not self.entries:
            return
        try:
            db = sqldb.connect(self._db_identity(), self.title_text.lower())
            groups = sorted(set(item.group or 'Ungrouped' for item in self.entries))
            sqldb.sync_categories(db, [(name, name) for name in groups])
            sqldb.sync_streams(db, self.entries)
            db.close()
        except Exception:
            pass

    def _load_catalogue(self):
        if _c.source.value != 'xtream':
            return False
        try:
            db = sqldb.connect(self._db_identity(), self.title_text.lower())
            rows = sqldb.streams(db, None, 0, 100000)
            db.close()
            self.entries = [MediaItem(**row) for row in rows]
            self.entries = allowed(self.entries, _c.show_adult.value)
            return bool(self.entries)
        except Exception:
            return False

    def _loaded(self, _result, error):
        if error and not self.error:
            self.error = error
        self.loaded()

    def fetch(self):
        raise NotImplementedError

    def _page_size(self):
        return max(1, int(_c.poster_count.value or 20))

    def _fetch_remote(self, wanted):
        """Read server pages until `wanted` items are in. Worker thread."""
        from . import catalogue
        out = []
        known = set(i.item_id for i in self.entries)
        while not self.remote_done and len(out) < wanted:
            batch, total = catalogue.fetch_page(
                self.providers, self.CATALOGUE_KIND, self.category_id,
                self.remote_next)
            self.remote_total = max(self.remote_total, total)
            self.remote_next += 1
            fresh = [i for i in batch if i.item_id not in known]
            known.update(i.item_id for i in fresh)
            out.extend(fresh)
            loaded = len(self.entries) + len(out)
            if not fresh or (self.remote_total and loaded >= self.remote_total):
                self.remote_done = True
        return out

    def _moreWorker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        wanted = (self._pending_page + 1) * self._page_size() - len(self.entries)
        return allowed(self._fetch_remote(max(1, wanted)), _c.show_adult.value)

    def _moreReady(self, result, error):
        page, self._pending_page = self._pending_page, None
        if error:
            self['status'].setText(native('Error: %s' % error))
            return
        self.entries.extend(result or [])
        if page is not None and page * self._page_size() < len(self.entries):
            self.page = page
        self.showGroup()

    def _fetch_catalogue(self, kind):
        """A server's films or series, keeping the client for later."""
        from . import catalogue
        items, providers = catalogue.fetch(kind)
        self.stalker = providers.get('stalker')
        self.xtream = providers.get('xtream')
        self._vod_names = providers.get('vod_names') or {}
        return items

    def loaded(self):
        if self.error:
            self['status'].setText(native(self.error))
            self.session.open(MessageBox, native(self.error), MessageBox.TYPE_ERROR,
                              timeout=12)
            return
        if not self.entries:
            self['status'].setText(native('Nothing found.'))
            return
        if self.paged:
            # One category, read from the server as the list moves on.
            self.groups = [self.start_group or self.all_label()]
        else:
            self.groups = [self.all_label()] + m3u.groups(self.entries)
        if self.start_group in self.groups:
            self.group_index = self.groups.index(self.start_group)
        self.start_group = None
        self.showGroup()
        if self.query and self.stalker is not None and self.REMOTE_SEARCH:
            # A search typed on the category screen reaches the portal too.
            self._search_query = self.query
            if not self.search_task.running():
                self.search_task.start()

    # -------------------------------------------------------------- display

    def all_label(self):
        if self.LATEST_FIRST and _c.source.value in ('xtream', 'stalker'):
            from ..providers.xtream import LATEST
            return LATEST
        return 'All'

    def current_group(self):
        return self.groups[self.group_index] if self.groups else self.all_label()

    def count_text(self, total):
        return '%d items' % total

    def _filtered(self):
        g = self.current_group()
        values = (self.entries if g == self.all_label() or self.paged else
                  [i for i in self.entries if (i.group or 'Ungrouped') == g])
        if self.query:
            needle = self.query.lower()
            values = [i for i in values if needle in i.name.lower()
                      or (i.item_id and i.item_id in self.search_hits)]
        return values

    def visible(self):
        values = self._filtered()
        size = max(1, int(_c.poster_count.value or 20))
        start = self.page * size
        return values[start:start + size]

    def filteredCount(self):
        if self.paged and not self.query:
            return max(len(self.entries), self.remote_total)
        return len(self._filtered())

    def label_for(self, item):
        return item.label()

    def showGroup(self):
        shown = self.visible()
        self._setList(self._gridRows(shown) if self.grid_mode else
                      [self.label_for(i) for i in shown])
        if self.grid_mode:
            self._page_art_token += 1
            if self._pageArtNeeded(shown) and not self.page_art_task.running():
                self.page_art_task.start()
        self['head'].setText(native('%s  —  %s  (%d/%d)' % (
            self.title_text, self.current_group(),
            self.group_index + 1, max(1, len(self.groups)))))
        size = max(1, int(_c.poster_count.value or 20))
        total = self.filteredCount()
        pages = max(1, (total + size - 1) // size)
        self['status'].setText(native(
            '%s   |   page %d/%d%s   |   MENU search   CH± page' %
            (self.count_text(total), self.page + 1, pages,
             ('   |   ' + self.cache_notice) if self.cache_notice else '')))
        self.updateDetails()

    def nextGroup(self):
        if self.groups:
            self.group_index = (self.group_index + 1) % len(self.groups)
            self.page = 0
            self.showGroup()

    def moveUp(self):
        self._moveList(-1)
        self.updateDetails()

    def moveDown(self):
        self._moveList(1)
        self.updateDetails()

    def moveLeft(self):
        self._moveList(-1)
        self.updateDetails()

    def moveRight(self):
        self._moveList(1)
        self.updateDetails()

    def moveGridUp(self):
        self._moveList(-7)
        self.updateDetails()

    def moveGridDown(self):
        self._moveList(7)
        self.updateDetails()

    def _listIndex(self):
        widget = self['list']
        try:
            return int(widget.index)
        except Exception:
            try:
                return int(widget.getSelectedIndex())
            except Exception:
                return 0

    def _setList(self, rows):
        self['list'].setList(rows)

    def _moveList(self, delta):
        count = len(self.visible())
        if not count:
            return
        target = (self._listIndex() + int(delta)) % count
        try:
            self['list'].selectIndex(target)
        except Exception:
            try:
                self['list'].moveToIndex(target)
            except Exception:
                self['list'].index = target

    def _cachedPoster(self, url):
        if not url:
            return ''
        if os.path.isfile(url):
            return url
        directory = native(_c.picon_cache_dir.value or '/tmp/piip-cache')
        for ext in (image_cache.suffix(url), '.png', '.jpg'):
            # The download names the file after what arrived, so a .jpg
            # address that served a PNG is cached as .png.
            path = image_cache.cache_path(url, directory, ext)
            if os.path.isfile(path):
                return path
        return ''

    def _pageArtNeeded(self, shown):
        return any(getattr(item, 'logo', '') and
                   not self._cachedPoster(item.logo) for item in shown)

    def _pageArtWorker(self):
        token = self._page_art_token
        directory = native(_c.picon_cache_dir.value or '/tmp/piip-cache')
        loaded = []
        for item in list(self.visible()):
            url = native(getattr(item, 'logo', '') or '')
            if not url or self._cachedPoster(url):
                continue
            try:
                loaded.append((item, image_cache.download(url, directory,
                                                          timeout=12)))
            except Exception:
                pass
        return token, loaded

    def _pageArtReady(self, result, error):
        if error or not result:
            return
        token, loaded = result
        for item, path in loaded:
            if path:
                item.logo = native(path)
        if token == self._page_art_token:
            self._setList(self._gridRows(self.visible()))
        elif self._pageArtNeeded(self.visible()) and not self.page_art_task.running():
            self.page_art_task.start()

    def _gridRows(self, shown):
        """Rows use Hybrid's tuple indexes: title=0, poster=8, resume=9."""
        try:
            from Tools.LoadPixmap import LoadPixmap
        except ImportError:
            LoadPixmap = None
        directory = native(_c.picon_cache_dir.value or '/tmp/piip-cache')
        rows = []
        for item in shown:
            poster = None
            path = self._cachedPoster(native(getattr(item, 'logo', '') or ''))
            if not path:
                path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'icons', 'nocover.jpg')
            if LoadPixmap is not None and path and os.path.isfile(path):
                try:
                    poster = LoadPixmap(path)
                except Exception:
                    poster = None
            pct = resume_store.percent(item)
            badge = None
            badge_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                      'icons', 'eye.png')
            if pct and LoadPixmap is not None:
                try:
                    badge = LoadPixmap(badge_path)
                except Exception:
                    pass
            rows.append((native(self.label_for(item)), None, None, None,
                         None, None, None, None, poster, badge))
        return rows

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
        target = (self.page + 1) % pages
        if (self.paged and not self.query and target and
                (target + 1) * size > len(self.entries) and not self.remote_done):
            if not self.more_task.running():
                self._pending_page = target
                self['status'].setText(native('Loading page %d...' % (target + 1)))
                self.more_task.start()
            return
        self.page = target
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
        self.search_hits = set()
        self.page = 0
        self.showGroup()
        if self.query and self.stalker is not None and self.REMOTE_SEARCH:
            # The local filter answers at once; the portal's own search
            # follows, for titles the catalogue here does not hold.
            self._search_query = self.query
            if not self.search_task.running():
                self['status'].setText(native('Searching the portal...'))
                self.search_task.start()

    # Whether remote_search() asks the portal; Stalker films and series do.
    REMOTE_SEARCH = False

    def remote_search(self, query):
        """Items the server matches for `query`; None when unsupported."""
        return None

    def _searchWorker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        query = self._search_query
        try:
            found = self.remote_search(query) or []
        except Exception:
            found = []
        return query, allowed(found, _c.show_adult.value)

    def _searchReady(self, result, error):
        if error or not result:
            self.showGroup()
            return
        query, found = result
        if query != self.query:
            # Typed again while the portal was answering.
            if self.query and self.stalker is not None and self.REMOTE_SEARCH:
                self._search_query = self.query
                self.search_task.start()
            return
        known = dict((i.item_id, i) for i in self.entries if i.item_id)
        added = 0
        for item in found:
            if not item.item_id:
                continue
            self.search_hits.add(item.item_id)
            if item.item_id not in known:
                self.entries.append(item)
                known[item.item_id] = item
                added += 1
        if added:
            current = self.current_group()
            self.groups = [self.all_label()] + m3u.groups(self.entries)
            self.group_index = (self.groups.index(current)
                                if current in self.groups else 0)
        self.showGroup()
        if found:
            self['status'].setText(native(
                '%d found on the portal (%d new)   |   %s' %
                (len(found), added, self['status'].getText())))

    def currentItem(self):
        shown = self.visible()
        idx = self._listIndex()
        if not shown or idx is None or idx >= len(shown):
            return None
        return shown[idx]

    def updatePlot(self):
        self.updateDetails()

    def updateDetails(self):
        item = self.currentItem()
        self['plot'].setText(native((item.plot or '')[:300] if item else ''))
        rating = native(getattr(item, 'rating', '') or '') if item else ''
        self['rating'].setText(native(('Rating: %s' % rating) if rating else ''))
        self._art_token += 1
        item = self._art_item()
        self._pending_art = (self._art_token, item, {
            'poster': native(getattr(item, 'logo', '') or '') if item else '',
            'art': native(getattr(item, 'backdrop', '') or '') if item else '',
        })
        for name in ('poster', 'art'):
            try:
                self[name].hide()
            except Exception:
                pass
        if item and not self.art_task.running():
            self.art_task.start()

    def _art_item(self):
        item = self.currentItem()
        if item is None:
            return None
        # Episode APIs often put the artwork on the parent series only.
        parent = getattr(self, 'series', None)
        if parent is not None:
            item.logo = item.logo or parent.logo
            item.backdrop = item.backdrop or parent.backdrop
            item.plot = item.plot or parent.plot
            item.rating = item.rating or parent.rating
        return item

    def _art_worker(self):
        token, item, urls = self._pending_art
        directory = native(_c.picon_cache_dir.value or '/tmp/piip-cache')
        metadata = {}
        if (item is not None and _c.source.value == 'xtream' and
                item.kind == MOVIE and item.item_id and
                (not item.plot or not item.backdrop)):
            try:
                api = self.xtream
                if api is None:
                    api = make_xtream()
                    api.login()
                metadata = api.movie_info(item.item_id)
                item.plot = item.plot or native(metadata.get('plot', ''))
                item.rating = item.rating or native(metadata.get('rating', ''))
                item.duration = item.duration or metadata.get('duration', 0)
                item.logo = item.logo or native(metadata.get('cover', ''))
                item.backdrop = item.backdrop or native(metadata.get('backdrop', ''))
                urls['poster'] = item.logo
                urls['art'] = item.backdrop
            except Exception:
                metadata = {}
        result = {}
        for name, url in urls.items():
            if not url:
                continue
            try:
                result[name] = (url if os.path.isfile(url) else
                                image_cache.download(url, directory,
                                                     timeout=12))
            except Exception:
                pass
        return token, item, result, metadata

    def _art_ready(self, result, error):
        if error or not result:
            return
        token, item, paths, metadata = result
        if token != self._art_token:
            # A fast key press changed selection while the image downloaded.
            if not self.art_task.running():
                self.art_task.start()
            return
        if item is self.currentItem() and metadata:
            self['plot'].setText(native((item.plot or '')[:300]))
            self['rating'].setText(native(
                ('Rating: %s' % item.rating) if item.rating else ''))
        from Tools.LoadPixmap import LoadPixmap
        for name, path in paths.items():
            if not path:
                continue
            try:
                instance = self[name].instance
                pixmap = LoadPixmap(path, size=instance.size())
                if pixmap is not None:
                    instance.setPixmap(pixmap)
                    self[name].show()
            except Exception:
                pass

    def select(self):
        raise NotImplementedError

    def openDownloads(self):
        from .downloadmanager import FarsiDownloads
        self.session.open(FarsiDownloads)

    def downloadSelected(self):
        item = self.currentItem()
        if not item:
            return
        if item.kind == SERIES:
            self.session.open(
                MessageBox,
                native('Please open the series and download specific episodes.'),
                MessageBox.TYPE_INFO, timeout=6)
            return
        if self.stalker is not None and not item.url:
            try:
                self.stalker.resolve(item)
            except Exception as exc:
                self.session.open(MessageBox, native('Could not resolve download:\n%s' % exc),
                                  MessageBox.TYPE_ERROR, timeout=10)
                return
        if not item.url:
            self.session.open(MessageBox, native('This item has no download URL.'),
                              MessageBox.TYPE_ERROR, timeout=8)
            return
        entry = downloads.enqueue(item.url, item.name, _c.download_dir.value)
        downloads.start(entry['id'])
        self['status'].setText(native('Download started: %s' % item.name))
        self.session.open(
            MessageBox,
            native('Episode added to Download Manager.' if item.kind == EPISODE
                   else 'Movie added to Download Manager.'),
            MessageBox.TYPE_INFO, timeout=4)


class FarsiMovies(LoadingScreen):
    title_text = 'Movies'
    REMOTE_SEARCH = True
    LATEST_FIRST = True
    CATALOGUE_KIND = 'movies'

    def fetch(self):
        if self.paged:
            return self._fetch_remote(self._page_size())
        if self.catalogue_items is not None:
            return list(self.catalogue_items)
        if _c.source.value in ('stalker', 'xtream'):
            return self._fetch_catalogue('movies')
        found, _errors = m3u.load_all(_c.m3u_url.value,
                                      user_agent=_c.user_agent.value)
        return m3u.of_kind(found, MOVIE)

    def remote_search(self, query):
        if self.stalker is None:
            return None
        names = getattr(self, '_vod_names', {}) or {}
        items = self.stalker.search_vod(query)
        for m in items:
            m.group = names.get(m.group, m.group or 'Ungrouped')
        return items

    def label_for(self, item):
        text = item.label()
        pct = resume_store.percent(item)
        if pct:
            text = '%s   [%d%%]' % (text, pct)
        if item.duration:
            text = '%s   (%s)' % (text, human_duration(item.duration))
        return text

    def select(self):
        item = self.currentItem()
        if not item:
            return
        if self.stalker is not None and not item.url:
            self['status'].setText(native('Resolving link...'))
            try:
                self.stalker.resolve(item)
            except Exception as e:
                self.session.open(MessageBox,
                                  native('Could not get a playable link:\n%s' % e),
                                  MessageBox.TYPE_ERROR, timeout=10)
                self.showGroup()
                return
        shown = self.visible()
        idx = shown.index(item) if item in shown else 0
        self.session.open(FarsiPlayer, item, channels=shown, index=idx)


class FarsiSeries(LoadingScreen):
    title_text = 'Series'
    REMOTE_SEARCH = True
    LATEST_FIRST = True
    CATALOGUE_KIND = 'series'

    def fetch(self):
        if self.paged:
            return self._fetch_remote(self._page_size())
        if self.catalogue_items is not None:
            return list(self.catalogue_items)
        if _c.source.value in ('stalker', 'xtream'):
            return self._fetch_catalogue('series')
        # M3U sources have no series API: rebuild them from episode names.
        found, _errors = m3u.load_all(_c.m3u_url.value,
                                      user_agent=_c.user_agent.value)
        episodes = m3u.of_kind(found, EPISODE)
        self._m3u_series = m3u.series_from_episodes(episodes)
        from ..providers.models import MediaItem, SERIES
        return [MediaItem(name=title, kind=SERIES, item_id=title,
                          group=eps[0].group if eps else '')
                for title, eps in sorted(self._m3u_series.items())]

    def remote_search(self, query):
        if self.stalker is None:
            return None
        return self.stalker.search_series(query)

    def select(self):
        item = self.currentItem()
        if not item:
            return
        if _c.source.value in ('xtream', 'stalker'):
            self.session.open(FarsiEpisodes, item)
        else:
            eps = getattr(self, '_m3u_series', {}).get(item.name, [])
            self.session.open(FarsiEpisodes, item, preloaded=eps)


class FarsiEpisodes(LoadingScreen):
    """Episodes of one series, grouped by season."""

    def __init__(self, session, series, preloaded=None):
        self.series = series
        self.preloaded = preloaded
        self.title_text = series.name
        LoadingScreen.__init__(self, session)

    def fetch(self):
        if self.preloaded is not None:
            return list(self.preloaded)
        if _c.source.value == 'stalker':
            self.stalker = make_stalker()
            self.stalker.connect()
            return self.stalker.series_episodes(self.series.item_id)
        x = make_xtream()
        x.login()
        info, seasons = x.series_episodes(self.series.item_id)
        out = []
        for season_no in sorted(seasons):
            out.extend(seasons[season_no])
        return out

    def loaded(self):
        # Seasons replace categories for this screen.
        if self.error:
            self['status'].setText(native(self.error))
            self.session.open(MessageBox, native(self.error), MessageBox.TYPE_ERROR,
                              timeout=12)
            return
        if not self.entries:
            self['status'].setText(native('0 episode(s)'))
            return
        for e in self.entries:
            e.group = 'Season %d' % e.season if e.season else 'Episodes'
        self.groups = ['All'] + m3u.groups(self.entries)
        self.showGroup()

    def count_text(self, total):
        return '%d episode(s)' % total

    def label_for(self, item):
        text = item.label()
        pct = resume_store.percent(item)
        if pct:
            text = '%s   [%d%%]' % (text, pct)
        if item.duration:
            text = '%s   (%s)' % (text, human_duration(item.duration))
        return text

    def select(self):
        item = self.currentItem()
        if not item:
            return
        if self.stalker is not None and not item.url:
            try:
                self.stalker.resolve(item)
            except Exception as exc:
                self.session.open(MessageBox,
                                  native('Could not get episode link:\n%s' % exc),
                                  MessageBox.TYPE_ERROR, timeout=10)
                return
        shown = self.visible()
        idx = shown.index(item) if item in shown else 0
        self.session.open(FarsiPlayer, item, channels=shown, index=idx)
