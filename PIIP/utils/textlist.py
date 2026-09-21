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
"""One-column text lists drawn at HybridIPTV's size.

A plain MenuList uses the image's small default font and always aligns
left. The reference's source and setup lists are 40px rows, centred on
the IPTV-org screen. The skin side swaps the plain `list` widget for a
TemplatedMultiContent listbox; the screen side keeps one API whether the
image has Components.Sources.List (receiver) or not (test stub).
"""

import re

from Components.MenuList import MenuList
try:
    from Components.Sources.List import List as E2ListSource
except ImportError:                                  # test/development stub
    E2ListSource = None

from . import skin as sk
from .compat import native

ALIGN = {'center': 'RT_HALIGN_CENTER', 'left': 'RT_HALIGN_LEFT'}


def rich():
    return E2ListSource is not None


def listbox(xml, font=40, align='center', pad=24):
    """Replace the skin's plain `list` widget with a big-font text listbox."""
    if not rich():
        return xml
    f = sk.skin_factor()
    q = lambda value: int(round(value * f))

    def swap(match):
        attrs = match.group(0)
        size = re.search(r'size="(\d+),(\d+)"', attrs)
        row = re.search(r'itemHeight="(\d+)"', attrs)
        width = int(size.group(1))
        row_h = int(row.group(1)) if row else q(70)
        template = (
            '{"templates": {"default": (%d, [\n'
            '  MultiContentEntryText(pos=(%d,0), size=(%d,%d), font=0, '
            'flags=%s|RT_VALIGN_CENTER, text=0)\n'
            '])}, "fonts": [gFont("Regular",%d)], "itemHeight": %d}'
            % (row_h, q(pad), width - 2 * q(pad), row_h,
               ALIGN.get(align, ALIGN['center']), q(font), row_h))
        head = attrs.replace('<widget name="list"',
                             '<widget source="list" render="Listbox"', 1)
        head = re.sub(r'\s*itemHeight="\d+"', '', head)
        return ('%s><convert type="TemplatedMultiContent">%s</convert>'
                '</widget>' % (head[:-2].rstrip(), sk.xml_escape(template)))
    return re.sub(r'<widget name="list" [^>]*/>', swap, xml, count=1)


def make():
    return E2ListSource([]) if rich() else MenuList([])


def set_rows(widget, texts):
    texts = [native(t) for t in texts]
    widget.setList([(t,) for t in texts] if rich() else texts)


def index(widget):
    try:
        return int(widget.index)
    except Exception:
        try:
            return int(widget.getSelectedIndex() or 0)
        except Exception:
            return 0


def select(widget, target):
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


def move(widget, delta, count, wrap=True):
    """Move the selection; single steps wrap, page steps stop at the ends."""
    if count <= 0:
        return
    target = index(widget) + delta
    if wrap and abs(delta) == 1:
        target %= count
    select(widget, max(0, min(count - 1, target)))
