# -*- coding: utf-8 -*-
"""Public IPTV-org catalogue helpers."""

import json
import os
import time

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen

API = 'https://iptv-org.github.io/api'
PLAYLISTS = 'https://iptv-org.github.io/iptv'
UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'

# The catalogue lists change rarely and are slow to fetch on a receiver, so
# they are kept on disk, as the reference browser does. A stale copy is
# still used when the site cannot be reached.
CACHE_DIR = '/tmp/piip-cache/iptvorg'
CACHE_TTL = 24 * 3600


def _cache_path(path, cache_dir=None):
    name = path.strip('/').replace('/', '_')
    return os.path.join(cache_dir or CACHE_DIR, name)


def _read_cache(path, max_age=None):
    try:
        if max_age is not None and time.time() - os.path.getmtime(path) > max_age:
            return None
        with open(path, 'rb') as fh:
            return json.loads(fh.read().decode('utf-8', 'replace'))
    except Exception:
        return None


def _write_cache(path, raw):
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        tmp = path + '.part'
        with open(tmp, 'wb') as fh:
            fh.write(raw)
        if os.path.exists(path):              # rename will not overwrite
            os.remove(path)
        os.rename(tmp, path)
    except Exception:
        pass


def _download(path, timeout):
    req = Request('%s/%s' % (API, path.lstrip('/')),
                  headers={'User-Agent': UA})
    handle = urlopen(req, timeout=timeout)
    try:
        return handle.read()
    finally:
        handle.close()


def _json(path, timeout=25, cache_dir=None, fetch=None):
    cached = _cache_path(path, cache_dir)
    fresh = _read_cache(cached, CACHE_TTL)
    if fresh is not None:
        return fresh
    try:
        raw = (fetch or _download)(path, timeout)
        data = json.loads(raw.decode('utf-8', 'replace'))
    except Exception:
        stale = _read_cache(cached)
        if stale is not None:
            return stale
        raise
    _write_cache(cached, raw)
    return data


def countries():
    rows = []
    for item in _json('countries.json'):
        code = str(item.get('code') or '').lower()
        name = item.get('name') or code.upper()
        if code:
            rows.append((name, code, int(item.get('population') or 0)))
    rows.sort(key=lambda row: row[0].lower())
    return rows


def catalogue(kind):
    """Return (name, code, extra) rows for every IPTV-org browser mode."""
    if kind == 'countries':
        return countries()
    endpoint = {'categories': 'categories.json',
                'languages': 'languages.json',
                'regions': 'regions.json'}[kind]
    rows = []
    for item in _json(endpoint):
        code = str(item.get('id') or item.get('code') or '').lower()
        name = item.get('name') or code.upper()
        if code:
            rows.append((name, code, len(item.get('countries') or [])))
    rows.sort(key=lambda row: row[0].lower())
    return rows


def playlist_url(kind, code):
    folders = {'countries': 'countries', 'categories': 'categories',
               'languages': 'languages', 'regions': 'regions'}
    return '%s/%s/%s.m3u' % (PLAYLISTS, folders[kind], str(code).lower())


def country_url(code):
    return playlist_url('countries', code)


def all_url():
    return '%s/index.m3u' % PLAYLISTS
