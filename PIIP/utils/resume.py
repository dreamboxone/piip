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
"""Remembers how far into a movie or episode you got.

Live channels are never stored. Positions near the very start or the very
end are dropped, so finishing a film does not leave it asking to resume at
the closing credits next time.
"""

import json
import os
import time

from .compat import replace_file

STORE = '/etc/enigma2/piip_resume.json'

MIN_POSITION = 30          # don't bother resuming the first half minute
END_MARGIN = 90            # treat the last 90 s as "finished"
MAX_ENTRIES = 400


def _load(path):
    try:
        with open(path, 'r') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _save(data, path):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as fh:
            json.dump(data, fh)
        # os.replace overwrites an existing file atomically; plain os.rename
        # refuses to on Windows, which silently loses every write after the
        # first one.
        replace_file(tmp, path)
        return True
    except (IOError, OSError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _prune(data):
    if len(data) <= MAX_ENTRIES:
        return data
    ordered = sorted(data.items(), key=lambda kv: kv[1].get('at', 0),
                     reverse=True)
    return dict(ordered[:MAX_ENTRIES])


def get(item, path=STORE):
    """Seconds to resume from, or 0."""
    key = item.resume_key() if hasattr(item, 'resume_key') else str(item)
    if not key:
        return 0
    entry = _load(path).get(key)
    if not isinstance(entry, dict):
        return 0
    try:
        return max(0, int(entry.get('position', 0)))
    except (TypeError, ValueError):
        return 0


def put(item, position, duration=0, path=STORE):
    """Store a position; returns True when something was written."""
    key = item.resume_key() if hasattr(item, 'resume_key') else str(item)
    if not key:
        return False
    try:
        position = int(position)
    except (TypeError, ValueError):
        return False

    data = _load(path)
    duration = duration or getattr(item, 'duration', 0) or 0

    finished = duration and position >= duration - END_MARGIN
    if position < MIN_POSITION or finished:
        if key in data:
            del data[key]
            return _save(data, path)
        return False

    data[key] = {
        'position': position,
        'duration': int(duration or 0),
        'name': getattr(item, 'name', ''),
        'at': int(time.time()),
    }
    return _save(_prune(data), path)


def clear(item=None, path=STORE):
    if item is None:
        return _save({}, path)
    key = item.resume_key() if hasattr(item, 'resume_key') else str(item)
    data = _load(path)
    if key in data:
        del data[key]
        return _save(data, path)
    return False


def percent(item, path=STORE):
    """0-100 progress for the list screens, or 0 when unknown."""
    key = item.resume_key() if hasattr(item, 'resume_key') else str(item)
    if not key:
        return 0
    entry = _load(path).get(key) or {}
    try:
        pos = float(entry.get('position', 0))
        dur = float(entry.get('duration', 0) or getattr(item, 'duration', 0))
    except (TypeError, ValueError):
        return 0
    if dur <= 0:
        return 0
    return max(0, min(100, int(pos * 100 / dur)))
