# -*- coding: utf-8 -*-
"""Source browser for the public IPTV-org playlists.

Laid out as HybridIPTV's IPTVOrgBrowserScreen: the M3U wallpaper, the M3U
emblem centred at the top, a centred six-row list with 40px text over a
dark pane, the title at the left of the header and the item count or the
last message in its right-hand corner.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config
from ..providers import iptvorg
from ..utils import servers, skin as sk, textlist
from ..utils.backdrop import backdrop, load as load_icon
from ..utils.compat import native
from ..utils.uisafe import BackgroundTask, safe_actions
from ..utils import image as image_cache

_c = config.plugins.piip

TITLE = 'IPTV-ORG - SOURCES'
PAGE = 6

ROOT = [('All Channels', 'all'), ('By Country', 'countries'),
        ('By Language', 'languages'), ('By Category', 'categories'),
        ('By Region', 'regions')]


def build_skin():
    q = lambda value: int(round(value * sk.skin_factor()))
    flag = ('<widget name="flag" position="%d,%d" size="%d,%d" '
            'alphatest="blend" transparent="1" scale="stretch" zPosition="5"/>'
            % (q(320), q(550), q(120), q(80)))
    xml = sk.list_screen(
        'FarsiIPTVOrg', TITLE, buttons=[('SEARCH', '#2a1a5a'),
                                        ('ADD SERVER', sk.BTN_GREEN)],
        hint='OK - Select    BLUE - Search    GREEN - Add    EXIT - Back',
        hint_x=1120, hint_width=760, header_widget='head', item_height=70,
        layout='sources', backdrop='bg_m3u.png', logo_widget='logo',
        extra=(flag,))
    return textlist.listbox(xml, font=40, align='center')


class FarsiIPTVOrg(Screen):
    def __init__(self, session, picker=False):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.picker = picker
        self.mode = 'root'
        self.query = ''
        self.entries, self.error = [], ''
        self.visible_entries = []
        self['bg'] = Pixmap()
        self['logo'] = Pixmap()
        self['flag'] = Pixmap()
        self['list'] = textlist.make()
        self['head'] = Label('Select source')
        self['actions'] = ActionMap(['OkCancelActions', 'ColorActions',
                                     'DirectionActions', 'MenuActions'],
            safe_actions(self, {'cancel': self.back, 'red': self.back,
                                'ok': self.select, 'green': self.add,
                                'blue': self.search, 'yellow': self.search,
                                'menu': self.search, 'up': self.up,
                                'down': self.down, 'left': self.pageUp,
                                'right': self.pageDown}), -1)
        self.task = BackgroundTask(self, self.fetch, self.loaded, 'iptv-org')
        self.flag_task = BackgroundTask(self, self.fetchFlag,
                                        self.flagReady, 'iptv-org-flag')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.showRoot)
        self.onClose.append(self.task.stop)
        self.onClose.append(self.flag_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, 'bg_m3u.png')
        load_icon(self, 'logo', 'emblem_m3u.png')

    def back(self):
        if self.mode != 'root':
            self.showRoot()
        else:
            self.close(None)

    def fetch(self):
        try:
            self.entries = iptvorg.catalogue(self.mode)
        except Exception as exc:
            self.error = '%s: %s' % (type(exc).__name__, exc)

    def loaded(self, _result, error):
        self.error = self.error or error
        if self.error:
            self['head'].setText(native('Loading failed'))
            self.session.open(MessageBox, native(self.error), MessageBox.TYPE_ERROR,
                              timeout=10)
            self.error = ''
            self.mode = 'root'
            return
        self.showEntries()

    def rows(self):
        return ROOT if self.mode == 'root' else self.visible_entries

    def showRoot(self):
        self.mode = 'root'
        self.entries = []
        self.visible_entries = []
        textlist.set_rows(self['list'], [x[0] for x in ROOT])
        textlist.select(self['list'], 0)
        self['head'].setText('Select source')
        self['flag'].hide()

    def showEntries(self):
        values = self.entries
        if self.query:
            values = [x for x in values if self.query.lower() in x[0].lower()]
        self.visible_entries = values
        textlist.set_rows(self['list'], [x[0] for x in values])
        textlist.select(self['list'], 0)
        self['head'].setText(native('%d results' % len(values) if self.query
                                    else '%d items' % len(values)))
        self.updateFlag()

    def moveBy(self, delta):
        textlist.move(self['list'], delta, len(self.rows()))
        self.updateFlag()

    def up(self):
        self.moveBy(-1)

    def down(self):
        self.moveBy(1)

    def pageUp(self):
        self.moveBy(-PAGE)

    def pageDown(self):
        self.moveBy(PAGE)

    def selected(self):
        values = self.rows()
        idx = textlist.index(self['list'])
        return values[idx] if values and 0 <= idx < len(values) else None

    def updateFlag(self):
        try:
            self['flag'].hide()
        except Exception:
            pass
        row = self.selected() if self.mode == 'countries' else None
        self.flag_code = row[1] if row else ''
        # A download already running re-checks the code when it finishes,
        # so the flag always ends on the row that is selected now.
        if self.flag_code and not self.flag_task.running():
            self.flag_task.start()

    def fetchFlag(self):
        code = self.flag_code
        path = image_cache.download(
            'https://flagcdn.com/w160/%s.png' % code,
            native(_c.picon_cache_dir.value or '/tmp/piip-cache'), timeout=10)
        return code, path

    def flagReady(self, result, error):
        if error or not result:
            return
        if result[0] != getattr(self, 'flag_code', ''):
            if self.flag_code and not self.flag_task.running():
                self.flag_task.start()
            return
        from ..utils.backdrop import load_path
        load_path(self, 'flag', result[1])

    def activate(self, name, url):
        if self.picker:
            self.close((native(name), native(url)))
            return
        entry = {'type': 'm3u', 'name': native(name), 'url': native(url)}
        error = servers.upsert('m3u', entry)
        if error:
            self.session.open(MessageBox, native(error), MessageBox.TYPE_ERROR,
                              timeout=10)
            return
        self['head'].setText(native('Added "%s"' % name))

    def select(self):
        row = self.selected()
        if row is None:
            return
        if self.mode == 'root':
            _name, mode = row
            if mode == 'all':
                self.activate('IPTV-org All', iptvorg.all_url())
                return
            self.mode, self.query = mode, ''
            self['head'].setText(native('Loading...'))
            self.task.start()
            return
        self.add()

    def add(self):
        if self.mode == 'root':
            row = self.selected()
            if row is not None and row[1] == 'all':
                self.activate('IPTV-org All', iptvorg.all_url())
            return
        row = self.selected()
        if row is not None:
            name, code, _extra = row
            self.activate('IPTV-org %s' % name,
                          iptvorg.playlist_url(self.mode, code))

    def search(self):
        if self.mode == 'root':
            return
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
            self.session.openWithCallback(self.searched, VirtualKeyBoard,
                                          title='Search IPTV-org',
                                          text=self.query)
        except ImportError:
            pass

    def searched(self, text=None):
        if text is None:
            return
        self.query = native(text).strip()
        self.showEntries()

    def selectAll(self):
        self.activate('IPTV-org All', iptvorg.all_url())
