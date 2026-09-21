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
"""Subtitle search and download: OpenSubtitles and SubDL.

Both need a free API key. Whichever keys are present get searched; results
are merged and ranked so the best Persian match floats to the top.
"""

import json
import re

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen
    from urllib import urlencode

try:                                     # inside the plugin package
    from ..utils.compat import native
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import native

OS_API = 'https://api.opensubtitles.com/api/v1'
SUBDL_API = 'https://api.subdl.com/api/v1/subtitles'
SUBDL_DL = 'https://dl.subdl.com'
UA = 'PIIP v3.0'

# OpenSubtitles uses ISO-639-1, SubDL its own names.
LANG_OS = {'Persian': 'fa', 'Arabic': 'ar', 'English': 'en', 'Turkish': 'tr'}
LANG_SUBDL = {'Persian': 'FA', 'Arabic': 'AR', 'English': 'EN', 'Turkish': 'TR'}

_YEAR = re.compile(r'\b(19|20)\d{2}\b')
_SXXEYY = re.compile(r'\bS(\d{1,2})[\s._-]*E(\d{1,3})\b', re.I)
_NOISE = re.compile(
    r'\b(1080p|720p|2160p|4k|uhd|hdr|web-?dl|webrip|bluray|brrip|hdtv|'
    r'x264|x265|h264|h265|hevc|aac|ac3|dts|dual|multi|subbed|dubbed)\b', re.I)


class SubtitleError(Exception):
    pass


class Candidate(object):
    __slots__ = ('source', 'name', 'language', 'downloads', 'ref', 'release')

    def __init__(self, source, name, language, downloads=0, ref=None,
                 release=''):
        self.source = native(source)
        self.name = native(name)
        self.language = native(language)
        self.downloads = downloads or 0
        self.ref = ref
        self.release = native(release or '')

    def label(self):
        bits = [self.name]
        if self.downloads:
            bits.append('(%d)' % self.downloads)
        bits.append('[%s]' % self.source)
        return '  '.join(bits)

    def __repr__(self):
        return '<Candidate %s %r>' % (self.source, self.name)


def clean_title(name):
    """Strip release noise so a search actually matches something."""
    text = name or ''
    text = re.sub(r'\.(mkv|mp4|avi|ts|m4v)$', '', text, flags=re.I)
    text = _SXXEYY.sub(' ', text)
    text = _NOISE.sub(' ', text)
    text = re.sub(r'[._]+', ' ', text)
    text = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', text)
    text = _YEAR.sub(' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip(' -')


def season_episode(name):
    m = _SXXEYY.search(name or '')
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _get_json(url, headers=None, timeout=25, data=None):
    req = Request(url, headers=headers or {}, data=data)
    fh = urlopen(req, timeout=timeout)
    try:
        raw = fh.read()
    finally:
        fh.close()
    try:
        return json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        raise SubtitleError('service did not return JSON')


def _get_bytes(url, headers=None, timeout=45):
    req = Request(url, headers=headers or {})
    fh = urlopen(req, timeout=timeout)
    try:
        return fh.read()
    finally:
        fh.close()


# ------------------------------------------------------------ OpenSubtitles

class OpenSubtitles(object):
    def __init__(self, api_key, user_agent=UA):
        self.api_key = (api_key or '').strip()
        self.user_agent = user_agent

    def _headers(self):
        return {'Api-Key': self.api_key,
                'User-Agent': self.user_agent,
                'Content-Type': 'application/json',
                'Accept': 'application/json'}

    def search(self, query, language='Persian', season=0, episode=0):
        if not self.api_key:
            return []
        params = {'query': query,
                  'languages': LANG_OS.get(language, 'fa')}
        if season and episode:
            params['season_number'] = season
            params['episode_number'] = episode
        data = _get_json('%s/subtitles?%s' % (OS_API, urlencode(params)),
                         self._headers())
        out = []
        for row in (data or {}).get('data') or []:
            attrs = row.get('attributes') or {}
            files = attrs.get('files') or []
            if not files:
                continue
            out.append(Candidate(
                source='OpenSubtitles',
                name=files[0].get('file_name') or attrs.get('release') or query,
                language=attrs.get('language') or '',
                downloads=attrs.get('download_count') or 0,
                ref=files[0].get('file_id'),
                release=attrs.get('release') or ''))
        return out

    def download(self, candidate):
        body = json.dumps({'file_id': candidate.ref}).encode('utf-8')
        data = _get_json('%s/download' % OS_API, self._headers(), data=body)
        link = (data or {}).get('link')
        if not link:
            raise SubtitleError((data or {}).get('message')
                                or 'no download link returned')
        return _get_bytes(link, {'User-Agent': self.user_agent})


# -------------------------------------------------------------------- SubDL

class SubDL(object):
    def __init__(self, api_key, user_agent=UA):
        self.api_key = (api_key or '').strip()
        self.user_agent = user_agent

    def search(self, query, language='Persian', season=0, episode=0):
        if not self.api_key:
            return []
        params = {'api_key': self.api_key,
                  'film_name': query,
                  'languages': LANG_SUBDL.get(language, 'FA'),
                  'subs_per_page': 30}
        if season and episode:
            params['season_number'] = season
            params['episode_number'] = episode
        data = _get_json('%s?%s' % (SUBDL_API, urlencode(params)),
                         {'User-Agent': self.user_agent})
        if isinstance(data, dict) and data.get('status') is False:
            raise SubtitleError(data.get('error') or 'SubDL rejected the request')
        out = []
        for row in (data or {}).get('subtitles') or []:
            url = row.get('url')
            if not url:
                continue
            out.append(Candidate(
                source='SubDL',
                name=row.get('release_name') or row.get('name') or query,
                language=row.get('language') or row.get('lang') or '',
                downloads=0,
                ref=url,
                release=row.get('release_name') or ''))
        return out

    def download(self, candidate):
        url = candidate.ref
        if not url.startswith('http'):
            url = SUBDL_DL + ('' if url.startswith('/') else '/') + url
        return _get_bytes(url, {'User-Agent': self.user_agent})


# ------------------------------------------------------------------ facade

class SubtitleFinder(object):
    """Searches every configured service and merges the results."""

    def __init__(self, opensubtitles_key='', subdl_key='', language='Persian'):
        self.language = language
        self.services = {}
        if (opensubtitles_key or '').strip():
            self.services['OpenSubtitles'] = OpenSubtitles(opensubtitles_key)
        if (subdl_key or '').strip():
            self.services['SubDL'] = SubDL(subdl_key)

    @property
    def configured(self):
        return bool(self.services)

    def search(self, name, language=None):
        """-> ([Candidate], [error strings])"""
        language = language or self.language
        query = clean_title(name)
        season, episode = season_episode(name)
        results, errors = [], []
        for label, svc in self.services.items():
            try:
                results.extend(svc.search(query, language, season, episode))
            except Exception as e:
                errors.append('%s: %s' % (label, e))
        wanted = LANG_OS.get(language, 'fa').lower()
        results.sort(key=lambda c: (
            0 if (c.language or '').lower().startswith(wanted) else 1,
            -c.downloads))
        return results, errors

    def download(self, candidate):
        svc = self.services.get(candidate.source)
        if svc is None:
            raise SubtitleError('%s is not configured' % candidate.source)
        return svc.download(candidate)
