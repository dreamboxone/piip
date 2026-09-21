# -*- coding: utf-8 -*-
"""Small TMDB client with a disk cache suitable for receiver storage."""

import json
import os
import re
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import Request, urlopen
    from urllib import urlencode

from .compat import native

API = 'https://api.themoviedb.org/3'
IMAGE = 'https://image.tmdb.org/t/p/w500'
CACHE = '/etc/enigma2/piip_tmdb.json'
TTL = 7 * 86400
_YEAR = re.compile(r'\b(?:19|20)\d{2}\b')
_JUNK = re.compile(r'\b(?:4k|uhd|fhd|hd|sd|1080p?|720p?|2160p?|multi|dubbed)\b', re.I)
_PREFIX = re.compile(r'^[A-Z]{2,4}\s*[|:\-]\s*', re.I)


def clean_title(title):
    text = _PREFIX.sub('', native(title or '').strip())
    text = _YEAR.sub(' ', text)
    text = _JUNK.sub(' ', text)
    text = re.sub(r'[._]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' -|')
    return text


def _load_cache():
    try:
        data = json.load(open(CACHE, 'r'))
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _save_cache(data):
    folder = os.path.dirname(CACHE)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(CACHE, 'w') as handle:
        json.dump(data, handle, sort_keys=True)


def _get(path, key, params=None, timeout=20):
    query = dict(params or {})
    query['api_key'] = key
    url = '%s/%s?%s' % (API, path.lstrip('/'), urlencode(query))
    req = Request(url, headers={'User-Agent': 'PIIP/1.0', 'Accept': 'application/json'})
    handle = urlopen(req, timeout=timeout)
    try:
        return json.loads(handle.read().decode('utf-8', 'replace'))
    finally:
        handle.close()


def image(path):
    return IMAGE + path if path and str(path).startswith('/') else native(path or '')


def search(title, api_key, language='en-US'):
    cleaned = clean_title(title)
    if not cleaned or not api_key:
        return {}
    cache = _load_cache()
    cache_key = '%s|%s' % (language, cleaned.lower())
    saved = cache.get(cache_key) or {}
    if saved and time.time() - saved.get('_cached', 0) < TTL:
        return saved
    data = _get('search/multi', api_key,
                {'query': cleaned, 'language': language, 'include_adult': 'false'})
    rows = [x for x in data.get('results', [])
            if x.get('media_type') in ('movie', 'tv')]
    if not rows:
        return {}
    row = rows[0]
    result = {
        'id': row.get('id'), 'media_type': row.get('media_type'),
        'title': row.get('title') or row.get('name') or cleaned,
        'plot': row.get('overview') or '',
        'rating': row.get('vote_average') or '',
        'year': (row.get('release_date') or row.get('first_air_date') or '')[:4],
        'poster': image(row.get('poster_path')),
        'backdrop': image(row.get('backdrop_path')),
        '_cached': int(time.time()),
    }
    cache[cache_key] = result
    _save_cache(cache)
    return result


def enrich(item, api_key, language='en-US'):
    info = search(item.name, api_key, language)
    if not info:
        return item
    item.plot = item.plot or native(info.get('plot') or '')
    item.logo = item.logo or native(info.get('poster') or '')
    item.rating = item.rating or native(info.get('rating') or '')
    item.backdrop = item.backdrop or native(info.get('backdrop') or '')
    item.year = item.year or native(info.get('year') or '')
    return item
