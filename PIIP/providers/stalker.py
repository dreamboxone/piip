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
"""Stalker / Ministra portal client (MAG set-top-box emulation).

Unlike Xtream, a Stalker portal never hands out a stable stream URL. Each
channel carries a `cmd` token which must be exchanged for a real URL through
`create_link` immediately before playing, and that URL expires quickly. This
is why bouquet entries cannot point at the portal directly — see
translate/resolver.py.
"""

import json
import re
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import quote, urlencode, urlparse, urljoin
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen
    from urllib import quote, urlencode
    from urlparse import urlparse, urljoin

from .models import MediaItem, LIVE, MOVIE, SERIES, EPISODE, parse_duration

UA = ('Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 '
      '(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3')
X_UA = 'Model: MAG250; Link: WiFi'

# Portals answer on one of these; which one varies by installation.
ENDPOINTS = ('/portal.php', '/server/load.php', '/stalker_portal/server/load.php')

MAC_RE = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
_URL_IN_CMD = re.compile(r'(https?://\S+)')
_INLINE_HEADER = re.compile(r'[|#](?:Authorization|User-Agent|Cookie|Referer)=.*$', re.I)


class StalkerError(Exception):
    pass


def normalise_mac(mac):
    """Accept 001A79000000, 00-1A-79-.., 00:1a:79:.. -> 00:1A:79:00:00:00."""
    raw = re.sub(r'[^0-9A-Fa-f]', '', mac or '')
    if len(raw) != 12:
        return (mac or '').strip().upper()
    return ':'.join(raw[i:i + 2] for i in range(0, 12, 2)).upper()


def valid_mac(mac):
    return bool(MAC_RE.match(normalise_mac(mac)))


def portal_root(url):
    """Strip the /c/ suffix people copy from portal links."""
    url = (url or '').strip().rstrip('/')
    if not url.startswith('http'):
        url = 'http://' + url
    # Only the trailing /c goes: a portal at .../stalker_portal/c/ keeps its
    # /stalker_portal prefix, because that is where its API lives.
    if url.endswith('/c'):
        url = url[:-2]
    return url.rstrip('/')


# What portals put in front of a cmd. The reference plugin strips exactly
# these, and so does every MAG box.
CMD_PREFIXES = ('ffmpeg', 'ffrt', 'vlc', 'auto', 'mpegts')

# A cmd pointing at the box itself is a token, not an address.
LOCAL_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '::1')


def strip_prefix(cmd):
    """'ffmpeg http://x/y' -> 'http://x/y'."""
    text = (cmd or '').strip()
    for prefix in CMD_PREFIXES:
        if text.lower().startswith(prefix + ' '):
            return text[len(prefix):].strip()
    return text


def clean_cmd(cmd):
    """The URL inside a cmd, whatever is wrapped around it."""
    if not cmd:
        return ''
    m = _URL_IN_CMD.search(cmd)
    value = m.group(1) if m else strip_prefix(cmd)
    return _INLINE_HEADER.sub('', value)


def resolve_url(url, portal):
    """Apply HybridIPTV's final Stalker URL processing.

    MAG portals commonly return localhost URLs or paths relative to their API
    root. They name the portal itself, not this receiver.
    """
    value = clean_cmd(url)
    if not value:
        return ''
    root = portal_root(portal)
    parsed = urlparse(value)
    if parsed.hostname in LOCAL_HOSTS:
        base = urlparse(root)
        authority = base.netloc
        value = '%s://%s%s' % (base.scheme or 'http', authority,
                               parsed.path or '/')
        if parsed.query:
            value += '?' + parsed.query
    elif not parsed.scheme:
        value = urljoin(root.rstrip('/') + '/', value.lstrip('/'))
    return value


def direct_url(cmd):
    """The cmd as a playable address, or '' if it is only a token.

    Portals answer create_link two ways: some mint a real stream URL,
    others echo their own template back with the stream id dropped. When
    the channel's own cmd is already an absolute address on a real host
    there is nothing to exchange, so it is played as it stands.
    """
    url = strip_prefix(cmd)
    if not url.lower().startswith(('http://', 'https://')):
        return ''
    try:
        host = (urlparse(url).hostname or '').lower()
    except Exception:
        return ''
    if not host or host in LOCAL_HOSTS:
        return ''
    return url


def archive_days(row):
    """How many days back a channel's recordings go; 0 when it has none.

    Ministra flags archived channels with tv_archive and gives the depth in
    hours as tv_archive_duration.
    """
    flag = str(row.get('tv_archive') or row.get('archive') or '0').strip()
    if flag in ('', '0', 'false', 'False', 'None'):
        return 0
    try:
        hours = int(float(row.get('tv_archive_duration') or 0))
    except (TypeError, ValueError):
        hours = 0
    return max(1, (hours + 23) // 24) if hours > 0 else 1


_NO_DATE = ('', '0', 'null', 'none', '0000-00-00', '0000-00-00 00:00:00')


def format_expiry(value):
    """A portal's expiry field as a date a person can read; '' if unset."""
    if value is None:
        return ''
    text = str(value).strip()
    if text.lower() in _NO_DATE:
        return ''
    if text.isdigit():
        try:
            return time.strftime('%Y-%m-%d', time.localtime(int(text)))
        except (ValueError, OverflowError, OSError):
            return ''
    if text.endswith(' 00:00:00'):
        text = text[:-len(' 00:00:00')]
    return text


# Profile fields different Ministra versions keep the expiry in.
EXPIRY_KEYS = ('expire_billing_date', 'end_date', 'tariff_expired_date',
               'expire_date', 'exp_date')


def _query_value(url, key):
    """One query parameter, without pulling in a parser for it."""
    marker = '%s=' % key
    cut = url.find('?')
    if cut == -1:
        return None
    for part in url[cut + 1:].split('&'):
        if part.startswith(marker):
            return part[len(marker):]
    return None


# What identifies the channel, as opposed to the session.
_STREAM_KEYS = ('stream', 'file', 'id')


def link_is_worse(answer, original):
    """Whether create_link blanked out something the cmd already had.

    Seen on more than one portal: the reply carries the same parameters
    with the stream id emptied, so every channel plays the same thing.
    """
    if not answer or not original:
        return False
    for key in _STREAM_KEYS:
        had = _query_value(original, key)
        got = _query_value(answer, key)
        # Present but blank is the failure. Absent altogether is a portal
        # handing back a different kind of address, which is the normal
        # successful answer and must not be second-guessed.
        if had and got == '':
            return True
    return False


def _replace_query_value(url, key, value):
    """Put `value` into an existing `key=` in a URL's query."""
    cut = url.find('?')
    if cut == -1:
        return url
    head, query = url[:cut + 1], url[cut + 1:]
    parts = query.split('&')
    for i, part in enumerate(parts):
        if part.startswith('%s=' % key):
            parts[i] = '%s=%s' % (key, value)
    return head + '&'.join(parts)


def repair_link(answer, original):
    """The portal's fresh answer with the channel put back into it.

    The answer carries the session - a play_token good for right now -
    and the cmd carries the channel. Neither alone is playable when a
    portal blanks the stream id, so the two are combined.
    """
    fixed = answer
    for key in _STREAM_KEYS:
        had = _query_value(original, key)
        if had and _query_value(fixed, key) == '':
            fixed = _replace_query_value(fixed, key, had)
    return fixed


def token_of(item):
    """An item's create_link token.

    It lives in .cmd; catalogues and bouquets saved by older versions kept
    it in .plot, so that is still read when .cmd is empty.
    """
    return getattr(item, 'cmd', '') or getattr(item, 'plot', '')


class Stalker(object):
    def __init__(self, portal, mac, timeout=25, user_agent=UA, timezone='Europe/London'):
        self.root = portal_root(portal)
        self.mac = normalise_mac(mac)
        self.timeout = timeout
        self.user_agent = user_agent
        self.timezone = timezone
        self.token = ''
        self.endpoint = None
        self.profile = None
        # None until known; False once the portal refuses the day table.
        self.day_table = None
        self._epg_info = (0.0, None)    # (fetched at, {ch_id: [rows]})

    # ------------------------------------------------------------- requests

    def _headers(self):
        h = {
            'User-Agent': self.user_agent,
            'X-User-Agent': X_UA,
            'Referer': '%s/c/' % self.root,
            'Accept': '*/*',
            'Cookie': 'mac=%s; stb_lang=en; timezone=%s'
                      % (quote(self.mac, safe=''), quote(self.timezone, safe='')),
        }
        if self.token:
            h['Authorization'] = 'Bearer %s' % self.token
        return h

    def _get(self, endpoint, params):
        params = dict(params)
        params['JsHttpRequest'] = '1-xml'
        url = '%s%s?%s' % (self.root, endpoint, urlencode(params))
        req = Request(url, headers=self._headers())
        fh = urlopen(req, timeout=self.timeout)
        try:
            raw = fh.read()
        finally:
            fh.close()
        text = raw.decode('utf-8', 'replace').strip()
        if not text:
            raise StalkerError('empty response')
        try:
            return json.loads(text)
        except ValueError:
            raise StalkerError('portal did not return JSON')

    def _call(self, **params):
        """Call the portal, discovering which endpoint path it uses."""
        if self.endpoint:
            return self._get(self.endpoint, params)
        last = None
        for ep in ENDPOINTS:
            try:
                data = self._get(ep, params)
            except Exception as e:
                last = e
                continue
            if isinstance(data, dict) and 'js' in data:
                self.endpoint = ep
                return data
            last = StalkerError('unexpected reply from %s' % ep)
        raise StalkerError('no working portal endpoint (%s)' % (last or '?'))

    # ------------------------------------------------------------ handshake

    def connect(self):
        if not valid_mac(self.mac):
            raise StalkerError('invalid MAC address: %r' % self.mac)
        data = self._call(type='stb', action='handshake', token='', prehash='')
        js = data.get('js') or {}
        token = js.get('token') if isinstance(js, dict) else None
        if not token:
            raise StalkerError('portal did not issue a token '
                               '(MAC not authorised?)')
        self.token = token
        try:
            self.profile = self.get_profile()
        except Exception:
            self.profile = None            # many portals work without it
        return self.token

    def get_profile(self):
        data = self._call(type='stb', action='get_profile', hd='1',
                          ver='ImageDescription: 0.2.18-r14-pub-250; '
                              'ImageDate: Wed Aug 29 10:33:42 EEST 2018; '
                              'PORTAL version: 5.3.0; API Version: JS API '
                              'version: 343; STB API version: 146; '
                              'Player Engine version: 0x58c',
                          device_id='', device_id2='', signature='',
                          auth_second_step='0', hw_version='1.7-BD-00',
                          not_valid_token='0', num_banks='2',
                          stb_type='MAG250', client_type='STB',
                          image_version='218', video_out='hdmi')
        return (data.get('js') or {})

    def account_info(self):
        """Expiry / status line for the settings screen; best effort."""
        try:
            data = self._call(type='account_info', action='get_main_info')
            js = data.get('js') or {}
            return {'phone': js.get('phone', ''),
                    'end_date': js.get('end_date', ''),
                    'tariff': js.get('tariff_plan', '')}
        except Exception:
            return {}

    def expiry(self):
        """When the subscription runs out, or '' if the portal won't say."""
        profile = self.profile if isinstance(self.profile, dict) else {}
        for key in EXPIRY_KEYS:
            value = format_expiry(profile.get(key))
            if value:
                return value
        return format_expiry(self.account_info().get('end_date'))

    # --------------------------------------------------------------- genres

    def genres(self):
        data = self._call(type='itv', action='get_genres')
        js = data.get('js') or []
        out = {}
        if isinstance(js, list):
            for g in js:
                if isinstance(g, dict):
                    out[str(g.get('id'))] = g.get('title') or g.get('name') or ''
        return out

    # ------------------------------------------------------------- channels

    @staticmethod
    def _channel_item(row, names):
        cid = row.get('id')
        if cid is None:
            return None
        genre = str(row.get('tv_genre_id', ''))
        return MediaItem(
            name=str(row.get('name') or 'unnamed'),
            url='',                                  # filled by resolve()
            logo=str(row.get('logo') or ''),
            group=names.get(genre, '') or 'Ungrouped',
            kind=LIVE,
            item_id=str(cid),
            tvg_id=str(row.get('xmltv_id') or ''),
            # The token create_link needs later.
            cmd=str(row.get('cmd') or ''),
            archive=archive_days(row))

    def channels(self):
        """Every live channel. `url` is a placeholder until create_link.

        get_all_channels is one request, but some portals disable it or
        time out on a big list; those are read page by page instead.
        """
        names = {}
        try:
            names = self.genres()
        except Exception:
            pass

        rows, failure = None, None
        try:
            data = self._call(type='itv', action='get_all_channels')
            js = data.get('js') or {}
            rows = js.get('data') if isinstance(js, dict) else js
        except Exception as exc:
            failure = exc

        out = []
        for row in rows or []:
            if isinstance(row, dict):
                item = self._channel_item(row, names)
                if item is not None:
                    out.append(item)
        if out:
            return out
        try:
            out = self.channels_by_genre(names)
        except Exception:
            # A portal that answered get_all_channels with nothing just
            # has no channels; only a portal that refused it is an error.
            if failure is not None:
                raise failure
            return []
        if not out and failure is not None:
            raise failure
        return out

    def channels_page(self, genre='*', page=1, names=None):
        """One page of a genre's channels -> (items, total, per_page)."""
        data = self._call(type='itv', action='get_ordered_list',
                          genre=str(genre), fav='0', sortby='number',
                          hd='0', p=str(page))
        js = data.get('js') or {}
        rows = js.get('data') if isinstance(js, dict) else js
        names = names or {}
        items = []
        for row in rows or []:
            if isinstance(row, dict):
                item = self._channel_item(row, names)
                if item is not None:
                    items.append(item)
        total = per_page = 0
        if isinstance(js, dict):
            try:
                total = int(js.get('total_items') or 0)
                per_page = int(js.get('max_page_items') or 0)
            except (TypeError, ValueError):
                total = per_page = 0
        return items, total, per_page

    def _genre_pages(self, genre, names, seen, max_pages):
        out = []
        for page in range(1, max_pages + 1):
            batch, total, per_page = self.channels_page(genre, page, names)
            fresh = [x for x in batch if x.item_id not in seen]
            if not fresh:
                break
            out.extend(fresh)
            seen.update(x.item_id for x in fresh)
            if total and per_page and page * per_page >= total:
                break
        return out

    def channels_by_genre(self, names=None, max_pages=200):
        """Every channel, read through get_ordered_list a page at a time.

        Genre '*' covers the lot on most portals; the rest only list a
        channel under its own genre, so those are walked one by one.
        """
        names = names if names is not None else {}
        seen = set()
        out = self._genre_pages('*', names, seen, max_pages)
        if out:
            return out
        for genre in names:
            if genre in ('*', ''):
                continue
            out.extend(self._genre_pages(genre, names, seen, max_pages))
        return out

    # ------------------------------------------------------------------ epg

    def short_epg(self, channel_id, size=12):
        """Upcoming programmes for one channel -> [Programme]."""
        from . import epg
        data = self._call(type='itv', action='get_short_epg',
                          ch_id=str(channel_id), size=str(size))
        return epg.from_stalker(data or {}, str(channel_id))

    def full_epg(self, channel_id, days=1, ahead=1, max_pages=30):
        """Past and coming programmes for one channel -> [Programme].

        get_short_epg only looks forward, so it never offers anything to
        catch up on. get_simple_data_table is read one day at a time, from
        `days` back (the channel's archive depth, capped at a week) to
        `ahead` days on. Portals without it get get_epg_info - what the
        reference plugin's full guide uses - merged with the short guide.
        """
        out = self._day_table_epg(channel_id, days, ahead, max_pages)
        if out:
            return out
        seen, merged = set(), []
        sources = (lambda: self.epg_info(channel_id),
                   lambda: self.short_epg(channel_id, size=24))
        failure = None
        for source in sources:
            try:
                progs = source()
            except Exception as exc:
                failure = exc
                continue
            for prog in progs:
                if (prog.start, prog.title) not in seen:
                    seen.add((prog.start, prog.title))
                    merged.append(prog)
        if not merged and failure is not None:
            raise failure
        merged.sort(key=lambda p: p.start)
        return merged

    def _day_table_epg(self, channel_id, days, ahead, max_pages):
        from . import epg
        if self.day_table is False:
            return []
        days = max(0, min(7, int(days or 0)))
        now = time.time()
        out, seen = [], set()
        for offset in range(-days, max(0, int(ahead)) + 1):
            date = time.strftime('%Y-%m-%d',
                                 time.localtime(now + offset * 86400))
            for page in range(1, max_pages + 1):
                try:
                    data = self._call(type='itv',
                                      action='get_simple_data_table',
                                      ch_id=str(channel_id), date=date,
                                      p=str(page))
                except Exception:
                    if self.day_table is None:
                        # Refused on the very first request: the portal
                        # does not have it, so stop asking day after day.
                        self.day_table = False
                        return []
                    break
                self.day_table = True
                fresh = [p for p in epg.from_stalker(data or {},
                                                     str(channel_id))
                         if (p.start, p.title) not in seen]
                if not fresh:
                    break
                out.extend(fresh)
                seen.update((p.start, p.title) for p in fresh)
                js = (data or {}).get('js')
                try:
                    total = int(js.get('total_items') or 0)
                    per_page = int(js.get('max_page_items') or 0)
                except (AttributeError, TypeError, ValueError):
                    total = per_page = 0
                if not (total and per_page) or page * per_page >= total:
                    break
        out.sort(key=lambda p: p.start)
        return out

    EPG_INFO_TTL = 600

    def epg_info(self, channel_id, period=3):
        """One channel's programmes from get_epg_info -> [Programme].

        The reply covers every channel at once and runs to megabytes, so it
        is kept for EPG_INFO_TTL and reused for the next channel's guide.
        """
        from . import epg
        fetched, table = self._epg_info
        if table is None or time.time() - fetched > self.EPG_INFO_TTL:
            data = self._call(type='itv', action='get_epg_info',
                              period=str(period))
            js = data.get('js') if isinstance(data, dict) else None
            table = js.get('data') if isinstance(js, dict) else None
            if not isinstance(table, dict):
                table = {}
            self._epg_info = (time.time(), table)
        rows = table.get(str(channel_id)) or []
        return epg.from_stalker(rows, str(channel_id))

    def catchup_link(self, cmd, start, duration):
        """Resolve a recorded ITV event using Ministra's archive arguments."""
        data = self._call(type='itv', action='create_link', cmd=cmd,
                          series='0', forced_storage='0', disable_ad='0',
                          download='0', uts=str(int(start)),
                          duration=str(max(1, int(duration))))
        js = data.get('js') or {}
        url = resolve_url(js.get('cmd') if isinstance(js, dict) else '', self.root)
        if not url:
            raise StalkerError('portal returned no catch-up link')
        return url

    # ------------------------------------------------------------------ vod

    def vod_categories(self):
        data = self._call(type='vod', action='get_categories')
        js = data.get('js') or []
        return [(str(c.get('id')), c.get('title') or c.get('name') or '')
                for c in js if isinstance(c, dict)]

    def vod_list(self, category='*', page=1, search=''):
        params = {'category': str(category), 'sortby': 'added', 'p': str(page)}
        if search:
            params['search'] = search
        data = self._call(type='vod', action='get_ordered_list', **params)
        js = data.get('js') or {}
        rows = js.get('data') if isinstance(js, dict) else js
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            vid = row.get('id')
            if vid is None:
                continue
            out.append(MediaItem(
                name=str(row.get('name') or 'unnamed'),
                url='',
                logo=str(row.get('screenshot_uri') or ''),
                group=str(row.get('category_id') or ''),
                kind=MOVIE,
                item_id=str(vid),
                year=str(row.get('year') or ''),
                rating=str(row.get('rating_imdb') or ''),
                backdrop=str(row.get('background') or row.get('backdrop') or ''),
                duration=parse_duration(row.get('time')),
                plot=str(row.get('description') or ''),
                cmd=str(row.get('cmd') or '')))
        total = 0
        if isinstance(js, dict):
            try:
                total = int(js.get('total_items') or 0)
            except (TypeError, ValueError):
                total = 0
        return out, total

    def all_vod(self, category='*', max_pages=500, search=''):
        """Fetch every server page, stopping on an empty/duplicate page."""
        out, seen, page, total = [], set(), 1, 0
        while page <= max_pages:
            batch, reported = self.vod_list(category, page, search)
            total = max(total, reported)
            fresh = [x for x in batch if x.item_id not in seen]
            if not fresh:
                break
            out.extend(fresh)
            seen.update(x.item_id for x in fresh)
            if total and len(out) >= total:
                break
            page += 1
        return out

    def search_vod(self, query, max_pages=20):
        """Films matching `query`, searched by the portal itself."""
        query = (query or '').strip()
        if not query:
            return []
        return self.all_vod('*', max_pages=max_pages, search=query)

    # ------------------------------------------------------------- series

    def series_categories(self):
        data = self._call(type='series', action='get_categories')
        js = data.get('js') or []
        return [(str(c.get('id')), c.get('title') or c.get('name') or '')
                for c in js if isinstance(c, dict)]

    def series_list(self, category='*', page=1, search=''):
        return self.series_page(category, page, search)[0]

    def series_page(self, category='*', page=1, search=''):
        """One page of a series category -> (items, total_items)."""
        params = {'category': str(category), 'sortby': 'added', 'p': str(page)}
        if search:
            params['search'] = search
        data = self._call(type='series', action='get_ordered_list', **params)
        js = data.get('js') or {}
        rows = js.get('data') if isinstance(js, dict) else js
        total = 0
        if isinstance(js, dict):
            try:
                total = int(js.get('total_items') or 0)
            except (TypeError, ValueError):
                total = 0
        out = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            sid = row.get('id') or row.get('movie_id')
            if sid is None:
                continue
            out.append(MediaItem(
                name=str(row.get('name') or row.get('title') or 'unnamed'),
                url='', logo=str(row.get('screenshot_uri') or row.get('logo') or ''),
                group=str(row.get('category_id') or ''), kind=SERIES,
                item_id=str(sid), year=str(row.get('year') or ''),
                rating=str(row.get('rating_imdb') or row.get('rating') or ''),
                backdrop=str(row.get('background') or row.get('backdrop') or ''),
                plot=str(row.get('description') or ''),
                cmd=str(row.get('cmd') or '')))
        return out, total

    def all_series(self, search='', max_pages=500):
        names = dict(self.series_categories())
        items, seen = [], set()
        for page in range(1, max_pages + 1):
            batch = self.series_list('*', page, search)
            fresh = [x for x in batch if x.item_id not in seen]
            if not fresh:
                break
            items.extend(fresh)
            seen.update(x.item_id for x in fresh)
        for item in items:
            item.group = names.get(item.group, item.group or 'Ungrouped')
        return items

    def search_series(self, query, max_pages=20):
        """Series matching `query`, searched by the portal itself."""
        query = (query or '').strip()
        if not query:
            return []
        return self.all_series(search=query, max_pages=max_pages)

    @staticmethod
    def _episode_rows(value):
        out = []

        def walk(node, season=0, parent_cmd='', parent_name=''):
            if isinstance(node, list):
                for child in node:
                    walk(child, season, parent_cmd, parent_name)
                return
            if not isinstance(node, dict):
                return
            local_season = node.get('season') or node.get('season_num') or season
            cmd = node.get('cmd') or parent_cmd
            name = node.get('name') or node.get('title') or parent_name
            children = node.get('episodes') or node.get('series') or node.get('seasons')
            if children:
                walk(children, local_season, cmd, name)
                return
            if cmd or node.get('id') is not None:
                item = dict(node)
                item['_season'], item['_cmd'], item['_name'] = local_season, cmd, name
                out.append(item)

        walk(value)
        return out

    def series_episodes(self, series_id, page=1):
        attempts = (
            ('series', {'action': 'get_ordered_list', 'movie_id': series_id,
                        'p': str(page)}),
            ('series', {'action': 'get_episodes', 'movie_id': series_id,
                        'p': str(page)}),
            ('vod', {'action': 'get_ordered_list', 'movie_id': series_id,
                     'p': str(page)}),
        )
        rows, last = [], None
        for media_type, params in attempts:
            try:
                data = self._call(type=media_type, **params)
                js = data.get('js') or {}
                root = js.get('data') if isinstance(js, dict) and 'data' in js else js
                rows = self._episode_rows(root)
                if rows:
                    break
            except Exception as exc:
                last = exc
        if not rows and last:
            raise last
        out = []
        for pos, row in enumerate(rows, 1):
            try:
                season = int(row.get('_season') or 0)
            except (TypeError, ValueError):
                season = 0
            try:
                episode = int(row.get('episode_num') or row.get('episode') or pos)
            except (TypeError, ValueError):
                episode = pos
            out.append(MediaItem(
                name=str(row.get('_name') or 'Episode %d' % episode),
                url='', kind=EPISODE,
                item_id=str(row.get('id') or '%s-%d' % (series_id, pos)),
                series_id=str(series_id), season=season, episode=episode,
                logo=str(row.get('screenshot_uri') or row.get('logo') or ''),
                duration=parse_duration(row.get('time')),
                plot=str(row.get('description') or ''),
                cmd=str(row.get('_cmd') or '')))
        return out

    # -------------------------------------------------------------- linking

    def create_link(self, cmd, series=0):
        """Exchange a channel/VOD cmd token for a playable URL."""
        if not cmd:
            raise StalkerError('no cmd to resolve')
        data = self._call(type='itv' if not series else 'vod',
                          action='create_link', cmd=cmd, series=str(series),
                          forced_storage='0', disable_ad='0', download='0')
        js = data.get('js') or {}
        url = resolve_url(js.get('cmd') if isinstance(js, dict) else '',
                          self.root)
        original = direct_url(cmd)
        if link_is_worse(url, original):
            # A fresh session with the channel blanked out. Put the channel
            # back rather than falling back to the cmd, whose play_token
            # was minted when the channel list was fetched and has very
            # likely expired by now.
            return repair_link(url, original)
        if not url:
            if original:
                return original
            raise StalkerError('portal returned no playable link')
        return url

    def resolve(self, item):
        """Fill item.url with a link that works right now.

        Always through create_link: the token in a channel's own cmd was
        minted when the list was fetched and expires long before you get
        round to watching. Only if the portal refuses altogether does the
        cmd get used as it stands.
        """
        cmd = token_of(item)
        try:
            item.url = self.create_link(cmd,
                                        series=0 if item.kind == LIVE else 1)
        except Exception:
            direct = direct_url(cmd)
            if not direct:
                raise
            item.url = direct
        item.auth_token = self.token
        item.portal_url = '%s/c/' % self.root
        item.mac = self.mac
        return item.url
