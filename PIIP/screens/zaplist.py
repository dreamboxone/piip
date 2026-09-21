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
"""The channel list you call up while watching.

A vertical panel down the left of the picture rather than a dialog in the
middle, so the programme stays visible while you pick. Closing it returns
the chosen index, or None when nothing was picked.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Screens.Screen import Screen

from ..utils import skin as sk
from ..utils.compat import native
from ..utils.uisafe import safe_actions


def build_skin():
    width = sk.desktop_width()
    w, h = ((1100, 1440) if width >= 2560 else
            ((800, 1080) if width >= 1920 else (533, 720)))
    factor = h / 1080.0
    q = lambda value: int(round(value * factor))
    head = q(80)
    font_title = q(32)
    item = q(90)
    pad = q(10)

    return (
        '<screen name="FarsiZapList" position="0,0" size="%d,%d" '
        'backgroundColor="%s" flags="wfNoBorder">\n'
        '  <eLabel position="0,0" size="%d,%d" backgroundColor="%s" '
        'transparent="0"/>\n'
        '  <widget name="title" position="%d,%d" size="%d,%d" '
        'font="Regular;%d" halign="center" foregroundColor="%s" '
        'transparent="1"/>\n'
        '  <widget name="list" position="%d,%d" size="%d,%d" '
        'scrollbarMode="showOnDemand" %s itemHeight="%d" transparent="1" '
        'zPosition="2"/>\n'
        '  <widget name="footer" position="%d,%d" size="%d,%d" '
        'font="Regular;%d" halign="center" foregroundColor="%s" '
        'transparent="1"/>\n'
        '</screen>'
        % (w, h, sk.ZAP_GROUND,
           w, head, sk.ZAP_HEADER,
           pad, head // 4, w - 2 * pad, head // 2, font_title, sk.ACCENT,
           pad, head + pad, w - 2 * pad, h - head - 3 * pad - item // 2,
           sk.list_attrs(zap=True), item,
           pad, h - item // 2 - pad, w - 2 * pad, item // 2,
           max(14, int(font_title * 0.6)), sk.TEXT_DIM)
    )


class FarsiZapList(Screen):
    """close() returns the selected index, or None."""

    def __init__(self, session, channels, current=0, title='Channels'):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.channels = list(channels or [])
        self.start_index = max(0, min(current, max(0, len(self.channels) - 1)))

        self['title'] = Label(native(title))
        self['list'] = MenuList([])
        self['footer'] = Label(native('OK: watch    EXIT: back'))
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions'],
            safe_actions(self, {
                'ok': self.choose,
                'cancel': self.dismiss,
                'red': self.dismiss,
                'up': self.up,
                'down': self.down,
                'left': self.pageUp,
                'right': self.pageDown,
            }), -1)
        self.onLayoutFinish.append(self.fill)

    def fill(self):
        rows = []
        for i, item in enumerate(self.channels):
            label = item.label() if hasattr(item, 'label') else str(item)
            marker = '> ' if i == self.start_index else '   '
            rows.append(native('%s%d. %s' % (marker, i + 1, label)))
        self['list'].setList(rows)
        try:
            self['list'].moveToIndex(self.start_index)
        except Exception:
            pass
        self['title'].setText(native('%d channels' % len(self.channels)))

    # ------------------------------------------------------------ movement

    def up(self):
        self['list'].up()

    def down(self):
        self['list'].down()

    def pageUp(self):
        for _ in range(8):
            self['list'].up()

    def pageDown(self):
        for _ in range(8):
            self['list'].down()

    # ------------------------------------------------------------ choosing

    def choose(self):
        index = self['list'].getSelectedIndex()
        if index is None or index >= len(self.channels):
            self.close(None)
            return
        self.close(index)

    def dismiss(self):
        self.close(None)
