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
"""Where it is safe to write, on a receiver that may have no disk at all.

/media/hdd exists on every Enigma2 image whether or not a disk is plugged
in. Without one it is an empty directory on the receiver's own flash, the
same filesystem the image boots from, and anything written there lands on
the root filesystem. Writing to it every second for the length of a
translated programme meant a power cut during playback could catch the
root filesystem mid-write, and a receiver that would not boot afterwards
until it was flashed again. Nothing here ever writes to the flash.
"""

import os

RAM = '/tmp'


def _device(path):
    """The device id of path, or of its nearest existing parent."""
    probe = path or ''
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return os.stat(probe).st_dev
    except OSError:
        return None


def on_flash(path):
    """Whether path is on the filesystem the receiver boots from.

    An unmounted /media/hdd is: it shares its device with /. Anything that
    cannot be checked counts as flash, because guessing wrong the other way
    is the expensive mistake.
    """
    device = _device(path)
    return device is None or device == _device('/')


def on_disk(path):
    """Whether path is on a plugged-in disk: neither the flash nor RAM."""
    return not on_flash(path) and _device(path) != _device(RAM)


def cache_dir(configured, fallback='/tmp/piip-cache'):
    """The artwork cache: the configured place if it is a disk, else RAM."""
    configured = configured or ''
    if configured and on_disk(configured):
        return configured
    return fallback
