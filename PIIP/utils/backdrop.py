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
"""Putting a picture into a widget, in the one way that works everywhere.

instance.setPixmapFromFile is missing on several Enigma2 images and fails
silently where it exists, which is why the main menu spent so long with no
background at all. LoadPixmap is what the reference plugin uses, and it
also scales the picture to the widget, which an ePixmap will not do.
"""

import os

from Tools.LoadPixmap import LoadPixmap

from .uisafe import note

ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), 'icons')


def pixmap(path, box=None):
    """LoadPixmap, with the size argument only where the image accepts it.

    Several images carry an older Tools.LoadPixmap whose signature has no
    `size`, and passing it raised TypeError for every picture: the whole
    interface came up with no artwork at all. Without it the picture keeps
    its own size, which the widgets already scale.
    """
    if box is not None:
        try:
            return LoadPixmap(path, size=box)
        except TypeError:
            pass
    return LoadPixmap(path)


def load(screen, widget, filename):
    """Draw `filename` from the icons directory into `screen[widget]`."""
    path = os.path.join(ICONS, filename)
    if not os.path.exists(path):
        note('artwork', 'missing: %s' % path)
        return False
    try:
        instance = getattr(screen[widget], 'instance', None)
    except (KeyError, LookupError):
        note('artwork', 'no %s widget on this screen' % widget)
        return False
    if instance is None:
        note('artwork', 'no instance for %s yet' % widget)
        return False
    try:
        # An empty eSize means "at the picture's own size", which is the
        # sane fallback when a widget has not been laid out yet.
        try:
            box = instance.size()
        except Exception:
            box = None
        picture = pixmap(path, box)
        if picture is None:
            note('artwork', 'not loadable: %s' % path)
            return False
        instance.setPixmap(picture)
        return True
    except Exception as exc:
        note('artwork', '%s failed: %s' % (path, exc))
        return False


def backdrop(screen, filename='bg_list.png'):
    """The wallpaper every browsing screen sits on."""
    return load(screen, 'bg', filename)


def load_path(screen, widget, path):
    """Draw an arbitrary cached image through the shared safe loader."""
    if not path or not os.path.exists(path):
        return False
    try:
        instance = screen[widget].instance
        picture = pixmap(path, instance.size())
        if picture is None:
            return False
        instance.setPixmap(picture)
        screen[widget].show()
        return True
    except Exception as exc:
        note('artwork', '%s failed: %s' % (path, exc))
        return False
