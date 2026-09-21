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
"""The groups of a loaded playlist, each behind a folder.

The reference plugin puts this between loading an M3U and its channels:
a list of the playlist's groups with a folder icon and a channel count,
and OK opens the channels of that group. The channel list keeps < > for
moving between groups once inside.
"""

import os
import re

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
try:
    from Components.Sources.List import List as E2ListSource
except ImportError:                                  # test/development stub
    E2ListSource = None
from Screens.Screen import Screen

from ..providers import m3u
from ..utils import skin as sk
from ..utils.backdrop import backdrop, ICONS
from ..utils.compat import native
from ..utils.uisafe import safe_actions

ALL = 'All channels'


def build_skin():
    return folder_list_skin(
        'FarsiM3UGroups', 'M3U playlist - groups',
        buttons=[('BACK', sk.BTN_RED), ('OPEN', sk.BTN_GREEN),
                 ('SEARCH', sk.ACCENT_WARM)],
        hint='OK - Open group    EXIT - Back', backdrop='bg_m3u.png')


def folder_list_skin(name, title, buttons, hint, backdrop):
    """A centred list of folders with a count at the right of each row.

    Shared by the M3U groups and the Xtream/Stalker category screens; the
    screen builds `bg`, `list`, `head` and `status`.
    """
    xml = sk.list_screen(
        name, title, '', buttons=buttons, hint=hint,
        header_widget='head', info=('status',), item_height=70,
        # Centred with its status line above the footer rule, not on it.
        layout='center', backdrop=backdrop)
    if E2ListSource is None:
        return xml
    width = sk.desktop_width()
    f = (2560 if width >= 2560 else (1920 if width >= 1920 else 1280)) / 1920.0
    q = lambda value: int(round(value * f))
    row_h, list_w = q(70), q(1100)          # the 'center' list width
    # The same template shape and pixmap entry the poster grid already
    # runs on the receiver, so no converter feature beyond it is assumed.
    template = (
        '{"templates": {"default": (%d, [\n'
        '  MultiContentEntryPixmapAlphaTest(pos=(%d,%d), size=(%d,%d), png=2, '
        'scale_flags=__import__("enigma").SCALE_STRETCH),\n'
        '  MultiContentEntryText(pos=(%d,0), size=(%d,%d), font=0, '
        'flags=RT_HALIGN_LEFT|RT_VALIGN_CENTER, text=0),\n'
        '  MultiContentEntryText(pos=(%d,0), size=(%d,%d), font=1, '
        'flags=RT_HALIGN_RIGHT|RT_VALIGN_CENTER, text=1, '
        'color=MultiContentTemplateColor("%s"))\n'
        '])}, "fonts": [gFont("Regular",%d), gFont("Regular",%d)], '
        '"itemHeight": %d}'
        % (row_h, q(14), q(11), q(48), q(48),
           q(80), list_w - q(260), row_h,
           list_w - q(180), q(160), row_h, sk.TEXT_DIM,
           q(28), q(24), row_h))

    def listbox(match):
        return ('<widget source="list" render="Listbox" position="%s" '
                'size="%s" scrollbarMode="showOnDemand" %s transparent="1" '
                'zPosition="4"><convert type="TemplatedMultiContent">%s'
                '</convert></widget>'
                % (match.group(1), match.group(2), sk.list_attrs(),
                   sk.xml_escape(template)))
    # Same place as the plain list, drawn with a folder and a count.
    return re.sub(r'<widget name="list" position="([^"]+)" size="([^"]+)"[^>]*/>',
                  listbox, xml, count=1)


def group_rows(channels):
    """[(group name, channel count)], 'All channels' first."""
    counts = {}
    for item in channels:
        name = item.group or 'Ungrouped'
        counts[name] = counts.get(name, 0) + 1
    return [(ALL, len(channels))] + [(g, counts[g])
                                     for g in m3u.groups(channels)]


class FarsiM3UGroups(Screen):

    def __init__(self, session, channels):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        # Not self.items: Screen subclasses dict, and Enigma2 skins a screen
        # by iterating self.items().
        self.channels = list(channels or [])
        self.rows = group_rows(self.channels)
        self.rich = E2ListSource is not None

        self['bg'] = Pixmap()
        self['list'] = E2ListSource([]) if self.rich else MenuList([])
        self['head'] = Label('')
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions'],
            safe_actions(self, {
                'ok': self.open,
                'green': self.open,
                'cancel': self.close,
                'red': self.close,
                'yellow': self.search,
                'menu': self.search,
                'up': self.up,
                'down': self.down,
            }), -1)
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.refresh)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self, 'bg_m3u.png')

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
            self['list'].setList([native('%s   (%d)' % (name, count))
                                  for name, count in self.rows])
        self['head'].setText(native('%d groups' % (len(self.rows) - 1)))
        self['status'].setText(native(
            '%d channels   |   OK opens a group, < > moves between groups '
            'inside it' % len(self.channels)))

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

    # ------------------------------------------------------------ opening

    def open(self, query=''):
        if not self.channels:
            return
        idx = self.index()
        name = self.rows[idx][0] if 0 <= idx < len(self.rows) else ALL
        from .channels import FarsiChannels
        self.session.open(FarsiChannels, self.channels,
                          group=None if name == ALL else name,
                          query=query)

    def search(self):
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
        except ImportError:
            return
        self.session.openWithCallback(self.searched, VirtualKeyBoard,
                                      title='Search channels', text='')

    def searched(self, text=None):
        text = native(text or '').strip()
        if not text:
            return
        from .channels import FarsiChannels
        self.session.open(FarsiChannels, self.channels, query=text)
