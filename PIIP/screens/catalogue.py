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
"""Loading a server's live, film or series catalogue, and its offline copy.

The category screen loads the catalogue once and hands it, with the
connected provider, to the list it opens; the lists load it themselves
when opened any other way. Both go through here so they cannot drift.

Everything here runs on a worker thread except where noted.
"""

import os
import time

from ..plugin import config, make_stalker
from ..providers.models import MediaItem
from ..providers.xtream import Xtream, XtreamError, newest_first
from ..utils import sqldb
from ..utils.compat import native

_c = config.plugins.piip

LIVE, MOVIES, SERIES = 'live', 'movies', 'series'
KINDS = (LIVE, MOVIES, SERIES)

# Offline databases are keyed by server and by what they hold. Films and
# series keep the names the lists always used, so catalogues saved by
# earlier versions are still found.
DB_MODE = {LIVE: 'live', MOVIES: 'movies', SERIES: 'series'}


def make_xtream():
    return Xtream(_c.xtream_host.value, _c.xtream_user.value,
                  _c.xtream_pass.value, user_agent=_c.user_agent.value)


def fetch(kind, source=None):
    """-> (items, providers) straight from the server.

    `providers` holds the connected client the lists need later to
    resolve links, read guides and search: {'stalker': ...} or
    {'xtream': ...}, plus 'vod_names' for Stalker films.
    """
    source = source or _c.source.value
    if source == 'stalker':
        portal = make_stalker()
        portal.connect()
        if kind == LIVE:
            return portal.channels(), {'stalker': portal}
        if kind == MOVIES:
            names = dict(portal.vod_categories())
            items = portal.all_vod('*')
            for item in items:
                item.group = names.get(item.group, item.group or 'Ungrouped')
            return items, {'stalker': portal, 'vod_names': names}
        return portal.all_series(), {'stalker': portal}
    if source == 'xtream':
        api = make_xtream()
        api.login()
        if kind == LIVE:
            return api.all_live(), {'xtream': api}
        if kind == MOVIES:
            return api.all_movies(), {'xtream': api}
        return api.all_series(), {'xtream': api}
    raise ValueError('no %s catalogue for a %s source' % (kind, source))


def paged(kind, source=None):
    """Whether a catalogue is browsed a category page at a time.

    A Stalker portal hands out films and series 14 at a time, and a big one
    holds tens of thousands: reading it all first takes the better part of
    an hour. The reference lists categories and fetches each on demand.
    """
    return (source or _c.source.value) == 'stalker' and kind in (MOVIES, SERIES)


def fetch_categories(kind):
    """-> (rows, ids, providers) for a paged catalogue.

    rows are (name, count) with the whole catalogue first; only that count
    is known without reading every category, so the others carry ''.
    """
    from ..providers.xtream import LATEST
    portal = make_stalker()
    portal.connect()
    if kind == MOVIES:
        cats = portal.vod_categories()
        _first, total = portal.vod_list('*', 1)
    else:
        cats = portal.series_categories()
        _first, total = portal.series_page('*', 1)
    names = dict(cats)
    rows = [(LATEST, total)]
    ids = {LATEST: '*'}
    for cid, name in cats:
        if cid in ('*', '') or not name:
            continue
        rows.append((native(name), ''))
        ids[native(name)] = cid
    return rows, ids, {'stalker': portal, 'vod_names': names}


def fetch_page(providers, kind, category_id, page, search=''):
    """One server page of a paged catalogue -> (items, total)."""
    portal = providers['stalker']
    names = providers.get('vod_names') or {}
    if kind == MOVIES:
        items, total = portal.vod_list(category_id, page, search)
    else:
        items, total = portal.series_page(category_id, page, search)
    for item in items:
        item.group = native(names.get(item.group, item.group or 'Ungrouped'))
    return items, total


def db_identity():
    return '%s|%s' % (_c.xtream_host.value, _c.xtream_user.value)


def save(kind, items):
    """Keep an offline copy of an Xtream catalogue. Returns success."""
    if _c.source.value != 'xtream' or not items:
        return False
    try:
        db = sqldb.connect(db_identity(), DB_MODE[kind])
        groups = sorted(set(item.group or 'Ungrouped' for item in items))
        sqldb.sync_categories(db, [(name, name) for name in groups])
        sqldb.sync_streams(db, items)
        db.close()
        return True
    except Exception:
        return False


def load_saved(kind):
    """The offline copy of an Xtream catalogue, or [] if there is none."""
    if _c.source.value != 'xtream':
        return []
    try:
        if not os.path.exists(sqldb.path(db_identity(), DB_MODE[kind])):
            return []
        db = sqldb.connect(db_identity(), DB_MODE[kind])
        rows = sqldb.streams(db, None, 0, 1000000)
        db.close()
        known = set(MediaItem.__slots__)
        items = [MediaItem(**dict((k, v) for k, v in row.items() if k in known))
                 for row in rows]
        # The database keeps rows by id; the lists show newest first.
        return newest_first(items) if kind != LIVE else items
    except Exception:
        return []


def saved_at(kind):
    """When the offline copy was written, as text; '' when there is none."""
    if _c.source.value != 'xtream':
        return ''
    try:
        stamp = os.path.getmtime(sqldb.path(db_identity(), DB_MODE[kind]))
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))
    except Exception:
        return ''


def error_text(exc):
    if isinstance(exc, XtreamError):
        return 'Xtream error: %s' % exc
    detail = native(exc)
    if 'Name or service not known' in detail or \
            'Temporary failure in name resolution' in detail:
        return ('Portal error: the server hostname does not exist or DNS '
                'cannot resolve it.')
    return '%s: %s' % (type(exc).__name__, detail)
