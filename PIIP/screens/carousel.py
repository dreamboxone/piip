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
"""The ring of illuminated icons both menus are built from.

The reference plugin has two of these - one to pick a provider and one
inside a connected server to pick Live TV, Movies or Series - and they are
the same screen twice over, so they are one class here.

Geometry is the reference's: icons 300/500/300 at x=240/700/1360, the
title at y=20, the label at y=780 and the chips on a rule at y=960.
"""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from ..utils import skin as sk
from ..utils.backdrop import ICONS, load
from ..utils.compat import native
from ..utils.uisafe import safe_actions


def build_skin(name, chips=(), subtitle=False):
    """The carousel skin, laid out the way the reference lays it out.

    `subtitle` adds a line under the title, for a server's own details
    such as when its subscription runs out.
    """
    width = sk.desktop_width()
    W, H = ((2560, 1440) if width >= 2560 else
            ((1920, 1080) if width >= 1920 else (1280, 720)))
    factor = W / 1920.0
    q = lambda v: int(round(v * factor))

    body = [
        '<widget name="bg" position="0,0" size="%d,%d" zPosition="0" '
        'scale="stretch" alphatest="on"/>' % (W, H),
        # Behind the artwork, not over it: it shows through where the
        # picture is transparent and darkens the ground when there is none.
        '<eLabel position="0,0" size="%d,%d" backgroundColor="%s" '
        'zPosition="-1"/>' % (W, H, sk.SCRIM),
        '<widget name="title" position="0,%d" size="%d,%d" font="Regular;%d" '
        'halign="center" foregroundColor="%s" transparent="1" zPosition="3"/>'
        % (q(20), W, q(60), q(44), sk.ACCENT),
    ]
    if subtitle:
        body.append(
            '<widget name="subtitle" position="0,%d" size="%d,%d" '
            'font="Regular;%d" halign="center" foregroundColor="%s" '
            'transparent="1" zPosition="3"/>'
            % (q(90), W, q(44), q(28), sk.ACCENT_WARM))
    body += [
        '<widget name="icon_left" position="%d,%d" size="%d,%d" '
        'zPosition="2" alphatest="blend"/>'
        % (q(240), q(340), q(300), q(300)),
        '<widget name="icon_mid" position="%d,%d" size="%d,%d" '
        'zPosition="3" alphatest="blend"/>'
        % (q(700), q(240), q(500), q(500)),
        '<widget name="icon_right" position="%d,%d" size="%d,%d" '
        'zPosition="2" alphatest="blend"/>'
        % (q(1360), q(340), q(300), q(300)),
        '<widget name="name" position="0,%d" size="%d,%d" font="Regular;%d" '
        'halign="center" foregroundColor="%s" transparent="1" zPosition="3"/>'
        % (q(780), W, q(60), q(56), sk.TEXT),
        # Kept as hidden widgets for API compatibility; Hybrid's main page
        # has only the selected name between carousel and footer.
        '<widget name="hint" position="0,0" size="1,1" transparent="1"/>',
        '<widget name="dots" position="0,0" size="1,1" transparent="1"/>',
        '<widget name="status" position="0,0" size="1,1" transparent="1"/>',
        '<eLabel position="0,%d" size="%d,2" backgroundColor="%s" '
        'zPosition="3"/>' % (q(900), W, sk.ACCENT),
    ]

    # Three chips from the left, and the fourth against the right edge, as
    # the reference places its MENU chip.
    cw, chh, cy = q(260), q(56), q(930)
    chip_x = (40, 320, 600, 1580)
    for index, (text, colour) in enumerate(chips):
        x = q(chip_x[index] if index < len(chip_x) else 40 + index * 280)
        # Outlined, as the reference draws its carousel chips: a
        # coloured ring round a dark middle, text in the same colour.
        body.append(sk.chip(text, x, cy, colour, cw, chh, font=q(24),
                            outline=True, wide=True))

    return ('<screen name="%s" position="center,center" size="%d,%d" '
            'backgroundColor="%s">\n  %s\n</screen>' %
            (name, W, H, sk.OPAQUE, (chr(10) + '  ').join(body)))


class CarouselScreen(Screen):
    """Subclass and fill in NAME, TITLE, ITEMS, CHIPS and select()."""

    NAME = 'FarsiCarousel'
    TITLE = 'PIIP'
    # (label, action, icon base name, one-line hint, background base name)
    ITEMS = ()
    CHIPS = ()
    SUBTITLE = False

    def __init__(self, session):
        self.skin = build_skin(self.NAME, self.CHIPS, self.SUBTITLE)
        Screen.__init__(self, session)
        self.session = session
        self.index = 0

        self['bg'] = Pixmap()
        self['icon_left'] = Pixmap()
        self['icon_mid'] = Pixmap()
        self['icon_right'] = Pixmap()
        self['title'] = Label(native(self.TITLE))
        if self.SUBTITLE:
            self['subtitle'] = Label('')
        self['name'] = Label('')
        self['hint'] = Label('')
        self['dots'] = Label('')
        self['status'] = Label('')

        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'MenuActions', 'InfobarActions', 'EPGSelectActions'],
            safe_actions(self, self.keymap()), -1)
        self.onLayoutFinish.append(self.startUI)

    def keymap(self):
        return {
            'ok': self.select,
            'cancel': self.close,
            'left': self.moveLeft,
            'right': self.moveRight,
            'up': self.moveLeft,
            'down': self.moveRight,
            'red': self.close,
        }

    # ------------------------------------------------------------ painting

    def _setPixmap(self, widget, filename):
        """Draw one of the plugin's pictures into a widget."""
        return load(self, widget, filename)

    def startUI(self):
        self.updateUI()

    def item(self, offset=0):
        return self.ITEMS[(self.index + offset) % len(self.ITEMS)]

    def background(self):
        """The wallpaper for the selected item, which may change per item."""
        current = self.item()
        return (current[4] if len(current) > 4 and current[4]
                else 'bg_main.png')

    def updateUI(self):
        n = len(self.ITEMS)
        self._setPixmap('bg', self.background())
        self._setPixmap('icon_left', '%s_s.png' % self.item(-1)[2])
        self._setPixmap('icon_mid', '%s.png' % self.item()[2])
        self._setPixmap('icon_right', '%s_s.png' % self.item(1)[2])

        self['name'].setText(native(self.item()[0]))
        self['hint'].setText(native(self.item()[3]))
        self['dots'].setText(native(
            '   '.join('*' if i == self.index else '.' for i in range(n))))
        self.refresh()

    def refresh(self):
        """Whatever belongs on the status line. Subclasses fill this in."""

    # -------------------------------------------------------------- moving

    def moveLeft(self):
        self.index = (self.index - 1) % len(self.ITEMS)
        self.updateUI()

    def moveRight(self):
        self.index = (self.index + 1) % len(self.ITEMS)
        self.updateUI()

    def select(self):
        raise NotImplementedError
