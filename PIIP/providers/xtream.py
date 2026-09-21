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
"""Xtream Codes client: live TV, movies and series."""

import json
import re
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import quote, urlencode
    from urllib.error import HTTPError
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen, HTTPError
    from urllib import quote, urlencode

try:
    from html import unescape as _unescape
except ImportError:                                    # Python 2 images
    from HTMLParser import HTMLParser
    _unescape = HTMLParser().unescape

from .models import MediaItem, LIVE, MOVIE, EPISODE, SERIES, parse_duration

try:                                     # inside the plugin package
    from ..utils.compat import native
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import native

UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'

# The first category of Movies and Series, as the reference lists it: the
# whole catalogue, newest additions first.
LATEST = 'LATEST ADDED'

# What the reference plugin tells the user for the panel answers that
# actually happen, instead of a bare "HTTP Error 403".
HTTP_MESSAGES = {
    401: 'HTTP Error 401: Unauthorized. Please check your credentials.',
    403: 'HTTP Error 403: Forbidden. Your IP might be blocked or account expired.',
    404: 'HTTP Error 404: Not Found. The server URL might be incorrect.',
    503: "HTTP Error 503: Service Unavailable. The provider's server is down.",
}


class XtreamError(Exception):
    pass


def newest_first(items):
    """Newest additions first, as the reference sorts films and series."""
    return sorted(items, key=lambda item: -(getattr(item, 'added', 0) or 0))


_ENTITY = re.compile(r'&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);')


def _s(value, default=''):
    """Xtream mixes ints, strings, nulls and empty lists in the same field.

    Panels also HTML-escape names ("Tom &amp; Jerry"), which the reference
    unescapes before showing them.
    """
    if value is None or isinstance(value, (list, dict)):
        return default
    # native(): Python 2's json hands over unicode, which str() refuses.
    text = native(value).strip()
    if '&' in text and _ENTITY.search(text):
        try:
            text = _unescape(text)
        except Exception:
            pass
    return text if text else default


def _timestamp(value):
    try:
        return int(float(_s(value, '0')))
    except (TypeError, ValueError):
        return 0


def archive_days(row):
    """Days of catch-up a live stream keeps; 0 when it has none."""
    if _s(row.get('tv_archive'), '0') in ('0', 'false', 'False'):
        return 0
    try:
        return max(1, int(float(_s(row.get('tv_archive_duration'), '1'))))
    except (TypeError, ValueError):
        return 1


def format_expiry(value):
    """exp_date (a Unix time, or empty for unlimited) as a readable date."""
    stamp = _timestamp(value)
    if stamp <= 0:
        return ''
    try:
        return time.strftime('%Y-%m-%d', time.localtime(stamp))
    except (ValueError, OverflowError, OSError):
        return ''


def _image_value(value):
    """Panels return backdrop_path as either a URL or a one-item list."""
    if isinstance(value, list):
        value = value[0] if value else ''
    return _s(value)


class Xtream(object):
    def __init__(self, host, username, password, timeout=25, user_agent=UA):
        self.host = host.rstrip('/')
        if not self.host.startswith('http'):
            self.host = 'http://' + self.host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.user_agent = user_agent
        self.info = None

    # ------------------------------------------------------------------ api

    def _api(self, **params):
        params.setdefault('username', self.username)
        params.setdefault('password', self.password)
        url = '%s/player_api.php?%s' % (self.host, urlencode(params))
        req = Request(url, headers={'User-Agent': self.user_agent})
        try:
            fh = urlopen(req, timeout=self.timeout)
        except HTTPError as exc:
            raise XtreamError(HTTP_MESSAGES.get(exc.code) or
                              'HTTP Error %s' % exc.code)
        try:
            raw = fh.read()
        finally:
            fh.close()
        try:
            return json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            raise XtreamError('server did not return JSON')

    def login(self):
        data = self._api()
        info = (data or {}).get('user_info') or {}
        if not info or str(info.get('auth', 0)) != '1':
            raise XtreamError(_s(info.get('message')) or 'authentication failed')
        self.info = info
        return info

    def status(self):
        if not self.info:
            return None
        return {
            'status': _s(self.info.get('status')),
            'expires': _s(self.info.get('exp_date')),
            'expiry': format_expiry(self.info.get('exp_date')),
            'max_connections': _s(self.info.get('max_connections')),
            'active_connections': _s(self.info.get('active_cons')),
        }

    def _categories(self, action):
        data = self._api(action=action) or []
        return [(_s(c.get('category_id')), _s(c.get('category_name')))
                for c in data if isinstance(c, dict)]

    # ----------------------------------------------------------------- urls

    def _play_url(self, kind, item_id, ext):
        return '%s/%s/%s/%s/%s.%s' % (
            self.host, kind,
            quote(self.username, safe=''), quote(self.password, safe=''),
            item_id, ext or 'mp4')

    def stream_url(self, stream_id, ext='ts'):
        return self._play_url('live', stream_id, ext)

    def catchup_url(self, stream_id, start, duration, ext='ts'):
        """Xtream timeshift URL for an archived EPG event."""
        stamp = time.strftime('%Y-%m-%d:%H-%M', time.localtime(int(start)))
        minutes = max(1, int((int(duration) + 59) / 60))
        return '%s/timeshift/%s/%s/%d/%s/%s.%s' % (
            self.host, quote(self.username, safe=''),
            quote(self.password, safe=''), minutes, stamp, stream_id,
            ext or 'ts')

    def movie_url(self, stream_id, ext='mp4'):
        return self._play_url('movie', stream_id, ext)

    def episode_url(self, episode_id, ext='mp4'):
        return self._play_url('series', episode_id, ext)

    # ----------------------------------------------------------------- live

    def live_categories(self):
        return self._categories('get_live_categories')

    def live_streams(self, category_id=None):
        kw = {'action': 'get_live_streams'}
        if category_id is not None:
            kw['category_id'] = str(category_id)
        out = []
        for s in self._api(**kw) or []:
            if not isinstance(s, dict):
                continue
            sid = s.get('stream_id')
            if sid is None:
                continue
            out.append(MediaItem(
                name=_s(s.get('name'), 'unnamed'),
                url=self.stream_url(sid),
                logo=_s(s.get('stream_icon')),
                group=_s(s.get('category_id')),
                kind=LIVE,
                tvg_id=_s(s.get('epg_channel_id')),
                tvg_name=_s(s.get('name')),
                item_id=_s(sid),
                archive=archive_days(s)))
        return out

    def all_live(self):
        names = dict(self.live_categories())
        items = self.live_streams()
        for c in items:
            c.group = names.get(c.group, c.group or 'Ungrouped')
        return items

    # ------------------------------------------------------------------ epg

    def short_epg(self, stream_id, limit=12):
        """Upcoming programmes for one channel -> [Programme]."""
        from . import epg
        data = self._api(action='get_short_epg', stream_id=str(stream_id),
                         limit=str(limit))
        return epg.from_xtream(data or {}, str(stream_id))

    def full_epg(self, stream_id):
        from . import epg
        data = self._api(action='get_simple_data_table',
                         stream_id=str(stream_id))
        return epg.from_xtream(data or {}, str(stream_id))

    # --------------------------------------------------------------- movies

    def vod_categories(self):
        return self._categories('get_vod_categories')

    def vod_streams(self, category_id=None):
        kw = {'action': 'get_vod_streams'}
        if category_id is not None:
            kw['category_id'] = str(category_id)
        out = []
        for s in self._api(**kw) or []:
            if not isinstance(s, dict):
                continue
            sid = s.get('stream_id')
            if sid is None:
                continue
            ext = _s(s.get('container_extension'), 'mp4')
            out.append(MediaItem(
                name=_s(s.get('name'), 'unnamed'),
                url=self.movie_url(sid, ext),
                logo=_s(s.get('stream_icon')) or _s(s.get('cover')),
                group=_s(s.get('category_id')),
                kind=MOVIE,
                item_id=_s(sid),
                ext=ext,
                rating=_s(s.get('rating')),
                year=_s(s.get('year')),
                backdrop=_image_value(s.get('backdrop_path')),
                duration=parse_duration(s.get('duration')),
                added=_timestamp(s.get('added'))))
        return out

    def all_movies(self):
        names = dict(self.vod_categories())
        items = newest_first(self.vod_streams())
        for m in items:
            m.group = names.get(m.group, m.group or 'Ungrouped')
        return items

    def movie_info(self, stream_id):
        """Plot, duration and artwork for one movie; best-effort."""
        data = self._api(action='get_vod_info', vod_id=str(stream_id)) or {}
        info = data.get('info') or {}
        return {
            'plot': _s(info.get('plot')) or _s(info.get('description')),
            'duration': parse_duration(info.get('duration')),
            'rating': _s(info.get('rating')),
            'year': _s(info.get('releasedate'))[:4],
            'cover': _s(info.get('movie_image')) or _s(info.get('cover_big')),
            'backdrop': _image_value(info.get('backdrop_path')),
            'genre': _s(info.get('genre')),
            'cast': _s(info.get('cast')),
        }

    # --------------------------------------------------------------- series

    def series_categories(self):
        return self._categories('get_series_categories')

    def series_list(self, category_id=None):
        kw = {'action': 'get_series'}
        if category_id is not None:
            kw['category_id'] = str(category_id)
        out = []
        for s in self._api(**kw) or []:
            if not isinstance(s, dict):
                continue
            sid = s.get('series_id')
            if sid is None:
                continue
            out.append(MediaItem(
                name=_s(s.get('name'), 'unnamed'),
                url='',                            # resolved per episode
                logo=_s(s.get('cover')),
                group=_s(s.get('category_id')),
                kind=SERIES,
                item_id=_s(sid),
                series_id=_s(sid),
                plot=_s(s.get('plot')),
                rating=_s(s.get('rating')),
                backdrop=_image_value(s.get('backdrop_path')),
                year=_s(s.get('releaseDate'))[:4] or _s(s.get('year')),
                added=_timestamp(s.get('last_modified') or s.get('added'))))
        return out

    def all_series(self):
        names = dict(self.series_categories())
        items = newest_first(self.series_list())
        for s in items:
            s.group = names.get(s.group, s.group or 'Ungrouped')
        return items

    def series_episodes(self, series_id):
        """-> (info dict, {season_number: [MediaItem, ...]})"""
        data = self._api(action='get_series_info',
                         series_id=str(series_id)) or {}
        info = data.get('info') or {}
        raw = data.get('episodes') or {}
        seasons = {}

        # Some panels return a dict keyed by season, others a bare list.
        if isinstance(raw, list):
            raw = {'1': raw}
        for season_key, eps in raw.items():
            try:
                season_no = int(season_key)
            except (TypeError, ValueError):
                season_no = 0
            bucket = []
            for ep in eps or []:
                if not isinstance(ep, dict):
                    continue
                eid = ep.get('id')
                if eid is None:
                    continue
                ext = _s(ep.get('container_extension'), 'mp4')
                meta = ep.get('info') or {}
                try:
                    ep_no = int(_s(ep.get('episode_num'), '0') or 0)
                except ValueError:
                    ep_no = 0
                bucket.append(MediaItem(
                    name=_s(ep.get('title'), 'Episode %d' % ep_no),
                    url=self.episode_url(eid, ext),
                    logo=_s(meta.get('movie_image')) or _s(info.get('cover')),
                    group=_s(info.get('name')),
                    kind=EPISODE,
                    item_id=_s(eid),
                    ext=ext,
                    series_id=_s(series_id),
                    season=season_no,
                    episode=ep_no,
                    plot=_s(meta.get('plot')),
                    rating=_s(meta.get('rating')),
                    backdrop=_image_value(meta.get('backdrop_path')) or
                             _image_value(info.get('backdrop_path')),
                    duration=parse_duration(
                        meta.get('duration_secs') or meta.get('duration'))))
            bucket.sort(key=lambda e: e.episode)
            if bucket:
                seasons[season_no] = bucket
        return info, seasons
