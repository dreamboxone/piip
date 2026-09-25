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
"""A list of M3U playlists kept in a plain text file.

One playlist per line, so more can be added over SSH without touching the
plugin settings. Every entry is loaded and the channels are merged, with
each playlist's name used as a group prefix so it is obvious where a
channel came from.

    # lines starting with # are ignored
    http://provider-one.tv/get.php?username=x&password=y&type=m3u_plus
    Sports = http://provider-two.tv/playlist.m3u
    /media/hdd/local.m3u

An optional "Name = url" form labels the playlist; without it the host name
is used. Local file paths work as well as URLs.
"""

import os

from .compat import in_root_homes, native, root_home

# Written in root's home on this image, which on OE-Alliance is /home/root:
# asking for /root/m3u.txt there failed without a word, because /root does
# not exist, and the list was never created at all.
STORE = os.path.join(root_home(), 'm3u.txt')

# Searched in order; the first file that exists wins.
SEARCH_PATHS = in_root_homes('m3u.txt') + (
    '/etc/enigma2/piip_m3u.txt',
    '/media/hdd/m3u.txt',
)

TEMPLATE = """# PIIP - playlist list
#
# One M3U playlist per line. Lines starting with # are ignored.
# Optionally give a playlist a name with "Name = url".
#
# Examples:
#   http://provider.tv/get.php?username=USER&password=PASS&type=m3u_plus
#   Sports = http://another.tv/playlist.m3u
#   /media/hdd/local.m3u
#
# Add as many as you like; they are all loaded and merged.

"""


class Entry(object):
    __slots__ = ('name', 'url')

    def __init__(self, name, url):
        self.name = native(name)
        self.url = native(url)

    def __repr__(self):
        return '<Playlist %r %s>' % (self.name, self.url)


def default_name(url):
    """A readable label when the line carries no explicit name."""
    text = native(url)
    if '://' in text:
        host = text.split('://', 1)[1].split('/', 1)[0]
        return host.split('@')[-1].split(':')[0] or 'playlist'
    return os.path.basename(text) or 'playlist'


def parse(text):
    """Text of the list file -> [Entry]."""
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    out = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name = ''
        # "Name = url", but not the '=' inside a query string. The test is
        # on the label, not the value: a plain word before the first '='
        # is a name, whereas anything containing a path, scheme or query
        # marker is part of the URL itself.
        if '=' in line:
            head, _, tail = line.partition('=')
            label, value = head.strip(), tail.strip()
            if value and label and not any(c in head for c in '/:?&'):
                name, line = label, value
        if not line or line in seen:
            continue
        seen.add(line)
        out.append(Entry(name or default_name(line), line))
    return out


def path(paths=SEARCH_PATHS):
    """The list file in use, or None."""
    for candidate in paths:
        if os.path.isfile(candidate):
            return candidate
    return None


def load(paths=SEARCH_PATHS):
    """[Entry] from whichever list file exists, or []."""
    found = path(paths)
    if not found:
        return []
    try:
        with open(found, 'rb') as fh:
            return parse(fh.read())
    except (IOError, OSError):
        return []


def ensure(target=STORE):
    """Create the list file with a commented template if it is missing.

    Returns the path when a file was written, or None if one already
    existed or the location is not writable.
    """
    if os.path.exists(target):
        return None
    directory = os.path.dirname(target)
    if directory and not os.path.isdir(directory):
        return None
    try:
        with open(target, 'w') as fh:
            fh.write(TEMPLATE)
        return target
    except (IOError, OSError):
        return None


def add(url, name='', target=None):
    """Append one playlist to the list file."""
    target = target or path() or STORE
    line = '%s = %s' % (native(name), native(url)) if name else native(url)
    try:
        existing = ''
        if os.path.exists(target):
            with open(target, 'rb') as fh:
                existing = fh.read().decode('utf-8', 'replace')
        if native(url) in existing:
            return False
        with open(target, 'a') as fh:
            if existing and not existing.endswith('\n'):
                fh.write('\n')
            fh.write(line + '\n')
        return True
    except (IOError, OSError):
        return False


def describe(paths=SEARCH_PATHS):
    """One line for the requirements screen."""
    found = path(paths)
    if not found:
        return 'no playlist list (create %s)' % STORE
    entries = load(paths)
    return '%d playlist(s) in %s' % (len(entries), found)
