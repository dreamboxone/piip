# -*- coding: utf-8 -*-
"""Download queue screen compatible with small Enigma2 images."""

from enigma import eTimer
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from ..utils import downloads, skin as sk
from ..utils.compat import native
from ..utils.uisafe import safe_actions, safe_callback


def build_skin():
    return sk.list_screen('FarsiDownloads', 'Downloads', 'PIIP',
        buttons=[('DELETE', sk.BTN_RED), ('RESUME', sk.BTN_GREEN),
                 ('STOP', sk.ACCENT_WARM), ('CLEAR FINISHED', sk.BTN_BLUE)],
        hint='RED delete   GREEN resume   YELLOW stop   BLUE clear finished   EXIT back',
        header_widget='status', info=(), item_height=60, layout='full')


class FarsiDownloads(Screen):
    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.entries = []
        self['bg'] = Pixmap()
        self['list'] = MenuList([])
        self['status'] = Label('')
        self['actions'] = ActionMap(['OkCancelActions', 'ColorActions'],
            safe_actions(self, {'cancel': self.close, 'red': self.remove,
                                'green': self.start, 'ok': self.start,
                                'yellow': self.pause,
                                'blue': self.clearFinished}), -1)
        self.timer = eTimer()
        try:
            self.timer.callback.append(safe_callback(self, self.reload))
        except AttributeError:
            self.timer_conn = self.timer.timeout.connect(safe_callback(self, self.reload))
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.timer.stop)

    def begin(self):
        self.reload()
        self.timer.start(2000, False)

    def reload(self):
        self.entries = downloads.refresh()
        rows = []
        for item in self.entries:
            mb = int(item.get('bytes', 0) / 1048576)
            rows.append('%s   [%s]   %d MB' %
                        (item.get('name', ''), item.get('status', 'queued'), mb))
        self['list'].setList([native(x) for x in rows])
        self['status'].setText(native('%d downloads' % len(rows)))

    def current(self):
        idx = self['list'].getSelectedIndex()
        return self.entries[idx] if self.entries and idx is not None and idx < len(self.entries) else None

    def start(self):
        item = self.current()
        if item:
            downloads.start(item['id'])
            self.reload()

    def pause(self):
        item = self.current()
        if item:
            downloads.cancel(item['id'])
            self.reload()

    def remove(self):
        item = self.current()
        if item:
            downloads.remove(item['id'], delete_file=False)
            self.reload()

    def clearFinished(self):
        removed = downloads.clear_finished()
        self.reload()
        self['status'].setText(native('%d finished downloads cleared' % removed))
