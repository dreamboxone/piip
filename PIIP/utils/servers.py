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
"""Saved servers, one JSON file per provider type.

The reference plugin keeps three lists side by side rather than one mixed
list, and so does this: an Xtream account, an M3U playlist and a Stalker
portal have nothing in common but a name, and merging them only makes the
files harder to hand-edit.

A server becomes "active" by being copied into the plugin's config, which
is where every screen already looks. That keeps the whole content side of
the plugin unaware that there is now more than one server.
"""

import json
import os

from .compat import native

TYPES = ('xtream', 'm3u', 'stalker')

TITLES = {
    'xtream': 'Xtream Codes',
    'm3u': 'M3U Playlist',
    'stalker': 'Stalker Portal',
}

# (key, prompt, default, secret) - the order is the order on screen.
FIELDS = {
    'xtream': (
        ('name', 'Server name', '', False),
        ('host', 'Server URL', 'http://', False),
        ('user', 'Username', '', False),
        ('password', 'Password', '', True),
    ),
    'm3u': (
        ('name', 'Playlist name', '', False),
        ('url', 'Playlist URL', 'http://', False),
    ),
    'stalker': (
        ('name', 'Portal name', '', False),
        ('portal', 'Portal URL', 'http://', False),
        ('mac', 'MAC address', '00:1A:79:00:00:00', False),
    ),
}

# Everything but the name has to be filled in before a server is usable.
REQUIRED = {
    'xtream': ('name', 'host', 'user', 'password'),
    'm3u': ('name', 'url'),
    'stalker': ('name', 'portal', 'mac'),
}

# /etc/enigma2 survives a plugin upgrade, which /usr/lib does not.
DIR = '/etc/enigma2'


def path(kind):
    return os.path.join(DIR, 'piip_%s.json' % kind)


def blank(kind):
    """A new entry with every field at its default."""
    entry = {'type': kind}
    for key, _prompt, default, _secret in FIELDS[kind]:
        entry[key] = default
    return entry


def load(kind):
    """Every saved server of one type. A broken file is never fatal."""
    try:
        with open(path(kind), 'r') as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entry = blank(kind)
        for key in entry:
            if key in item and item[key] is not None:
                # json gives unicode on Python 2 and the widgets reject it.
                entry[key] = native(item[key])
        entry['type'] = kind
        out.append(entry)
    return out


def save(kind, entries):
    """Write one type's list back. Returns an error string, or ''."""
    try:
        if not os.path.isdir(DIR):
            os.makedirs(DIR)
        with open(path(kind), 'w') as fh:
            json.dump(list(entries), fh, indent=2, sort_keys=True)
        return ''
    except (IOError, OSError) as exc:
        return '%s: %s' % (path(kind), exc)


def identity(kind, value):
    """What makes two saved servers the same connection."""
    value = value or {}
    if kind == 'xtream':
        return ('%s|%s' % (value.get('host', ''),
                           value.get('user', ''))).strip().lower()
    if kind == 'stalker':
        return ('%s|%s' % (value.get('portal', ''),
                           value.get('mac', ''))).strip().lower()
    return (value.get('url', '') or '').strip().lower()


def upsert(kind, entry, replaces=None):
    """Add a server, replacing the same connection identity.

    HybridIPTV treats the address/credentials as the identity. `replaces`
    is the entry as it was before an edit, so changing its address or name
    replaces it rather than adding a second one.

    Names are not identities: imported portal lists name dozens of MACs
    after the same host, and replacing by name wiped every other MAC of a
    portal whenever one of them was saved or connected.
    """
    targets = set([identity(kind, entry)])
    if replaces:
        targets.add(identity(kind, replaces))
    entries = [e for e in load(kind) if identity(kind, e) not in targets]
    entries.append(dict(entry, type=kind))
    entries.sort(key=lambda e: e.get('name', '').lower())
    return save(kind, entries)


def delete(kind, name, entry=None):
    """Remove one server: `entry` by identity, or every server named `name`.

    Pass the entry whenever it is known; several servers can share a name.
    """
    if entry is not None:
        target = identity(kind, entry)
        entries = [e for e in load(kind) if identity(kind, e) != target]
    else:
        entries = [e for e in load(kind)
                   if e.get('name', '').lower() != (name or '').lower()]
    return save(kind, entries)


def load_all():
    """Every saved server of every type, grouped by type in TYPES order."""
    out = []
    for kind in TYPES:
        out.extend(load(kind))
    return out


def missing(kind, entry):
    """The prompts of the fields still left empty."""
    prompts = dict((k, p) for k, p, _d, _s in FIELDS[kind])
    empty = []
    for key in REQUIRED[kind]:
        value = (entry.get(key) or '').strip()
        if not value or value in ('http://', 'https://'):
            empty.append(prompts.get(key, key))
    return empty


def address(entry):
    """The bit of a server worth showing next to its name."""
    kind = entry.get('type')
    if kind == 'xtream':
        return entry.get('host', '')
    if kind == 'm3u':
        return entry.get('url', '')
    return entry.get('portal', '')


def label(entry):
    """One line for a list: name, type and where it points."""
    where = address(entry)
    # A playlist URL carries the credentials, so only the host is shown.
    if '://' in where:
        where = where.split('://', 1)[1].split('/', 1)[0]
    return native('%-8s  %s%s' % (entry.get('type', '?').upper(),
                                  entry.get('name', 'unnamed'),
                                  '   [%s]' % where if where else ''))


def activate(entry, config_root=None):
    """Make this the server every content screen reads.

    The plugin already keeps one server's details in its config, and every
    screen already reads them from there; connecting therefore means
    copying the chosen entry over those values rather than threading a
    server object through the whole plugin.
    """
    if config_root is None:
        from Components.config import config
        config_root = config
    _c = config_root.plugins.piip
    kind = entry.get('type', 'm3u')

    _c.source.value = kind
    if kind == 'xtream':
        _c.xtream_host.value = native(entry.get('host', ''))
        _c.xtream_user.value = native(entry.get('user', ''))
        _c.xtream_pass.value = native(entry.get('password', ''))
    elif kind == 'm3u':
        _c.m3u_url.value = native(entry.get('url', ''))
    else:
        _c.stalker_portal.value = native(entry.get('portal', ''))
        _c.stalker_mac.value = native(entry.get('mac', ''))
    _c.active_server.value = native(entry.get('name', ''))

    for element in (_c.source, _c.xtream_host, _c.xtream_user, _c.xtream_pass,
                    _c.m3u_url, _c.stalker_portal, _c.stalker_mac,
                    _c.active_server):
        try:
            element.save()
        except Exception:
            pass
    try:
        from Components.config import configfile
        configfile.save()
    except Exception:
        pass
    return entry


def active(config_root=None):
    """The entry matching what the config currently points at.

    Reconstructed from the config rather than remembered separately, so a
    server edited in Settings is still the active one.
    """
    if config_root is None:
        from Components.config import config
        config_root = config
    _c = config_root.plugins.piip
    kind = _c.source.value
    entry = blank(kind)
    entry['name'] = native(getattr(_c, 'active_server').value or '')
    if kind == 'xtream':
        entry['host'] = native(_c.xtream_host.value)
        entry['user'] = native(_c.xtream_user.value)
        entry['password'] = native(_c.xtream_pass.value)
    elif kind == 'm3u':
        entry['url'] = native(_c.m3u_url.value)
    else:
        entry['portal'] = native(_c.stalker_portal.value)
        entry['mac'] = native(_c.stalker_mac.value)
    return entry
