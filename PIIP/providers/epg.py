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
"""Programme guide: XMLTV files plus the native Xtream and Stalker feeds.

Everything is normalised into Programme objects with epoch timestamps, so
the player and the guide screen never care where the data came from.
"""

import base64
import calendar
import gzip
import io
import json
import os
import re
import time

try:
    from xml.etree import cElementTree as ET
except ImportError:
    from xml.etree import ElementTree as ET

try:
    from urllib.request import Request, urlopen
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen

try:                                     # inside the plugin package
    from ..utils.compat import native, replace_file
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import native, replace_file

UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'
CACHE = '/etc/enigma2/piip_epg.json'
CACHE_TTL = 3 * 3600

_XMLTV_TIME = re.compile(r'^(\d{14})(?:\s*([+-]\d{4}))?')
_SQL_TIME = re.compile(r'^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})')


class Programme(object):
    __slots__ = ('channel', 'start', 'stop', 'title', 'desc')

    def __init__(self, channel, start, stop, title, desc=''):
        self.channel = native(channel)
        self.start = int(start or 0)
        self.stop = int(stop or 0)
        self.title = native(title or '')
        self.desc = native(desc or '')

    @property
    def duration(self):
        return max(0, self.stop - self.start)

    def running_at(self, when):
        return self.start <= when < self.stop

    def progress_at(self, when):
        if self.duration <= 0:
            return 0
        return max(0, min(100, int((when - self.start) * 100 / self.duration)))

    def clock(self):
        if not self.start:
            return ''
        return time.strftime('%H:%M', time.localtime(self.start))

    def span(self):
        if not (self.start and self.stop):
            return ''
        return '%s - %s' % (
            time.strftime('%H:%M', time.localtime(self.start)),
            time.strftime('%H:%M', time.localtime(self.stop)))

    def __repr__(self):
        return '<Programme %s %r>' % (self.clock(), self.title)


# ------------------------------------------------------------ time parsing

def parse_xmltv_time(text):
    """'20260908183000 +0000' -> epoch seconds."""
    if not text:
        return 0
    m = _XMLTV_TIME.match(text.strip())
    if not m:
        return 0
    stamp, offset = m.group(1), m.group(2)
    try:
        parts = (int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]),
                 int(stamp[8:10]), int(stamp[10:12]), int(stamp[12:14]))
        epoch = calendar.timegm(parts + (0, 0, 0))
    except ValueError:
        return 0
    if offset:
        sign = -1 if offset[0] == '-' else 1
        epoch -= sign * (int(offset[1:3]) * 3600 + int(offset[3:5]) * 60)
    return epoch


def parse_sql_time(text, assume_utc=True):
    """'2026-09-08 18:30:00' -> epoch seconds."""
    if not text:
        return 0
    m = _SQL_TIME.match(str(text).strip())
    if not m:
        return 0
    parts = tuple(int(x) for x in m.groups())
    try:
        if assume_utc:
            return calendar.timegm(parts + (0, 0, 0))
        return int(time.mktime(parts + (0, 0, -1)))
    except (ValueError, OverflowError):
        return 0


def _b64(text):
    """Xtream base64-encodes EPG titles, but not always."""
    if not text:
        return ''
    try:
        raw = base64.b64decode(text + '=' * (-len(text) % 4))
        decoded = raw.decode('utf-8')
        # Rubbish in means rubbish out; keep the original if it looks binary.
        if decoded and sum(c < ' ' and c not in '\r\n\t' for c in decoded) == 0:
            return decoded
    except Exception:
        pass
    return text


# ---------------------------------------------------------------- xmltv

def parse_xmltv(data, wanted=None):
    """Parse XMLTV bytes (optionally gzipped) into {channel_id: [Programme]}.

    `wanted` limits parsing to a set of channel ids, which matters on a
    receiver: a full country guide can be tens of megabytes.
    """
    if isinstance(data, bytes):
        if data[:2] == b'\x1f\x8b':
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        stream = io.BytesIO(data)
    else:
        stream = data

    out = {}
    display_names = {}
    for event, elem in ET.iterparse(stream, events=('end',)):
        tag = elem.tag
        if tag == 'channel':
            cid = elem.get('id') or ''
            name = elem.findtext('display-name') or ''
            if cid:
                display_names[cid] = name
            elem.clear()
        elif tag == 'programme':
            cid = elem.get('channel') or ''
            if cid and (wanted is None or cid in wanted):
                out.setdefault(cid, []).append(Programme(
                    channel=cid,
                    start=parse_xmltv_time(elem.get('start')),
                    stop=parse_xmltv_time(elem.get('stop')),
                    title=elem.findtext('title') or '',
                    desc=elem.findtext('desc') or ''))
            elem.clear()
    for progs in out.values():
        progs.sort(key=lambda p: p.start)
    return out, display_names


def fetch_xmltv(url, wanted=None, timeout=60, user_agent=UA):
    req = Request(url, headers={'User-Agent': user_agent,
                                'Accept-Encoding': 'gzip'})
    fh = urlopen(req, timeout=timeout)
    try:
        raw = fh.read()
    finally:
        fh.close()
    return parse_xmltv(raw, wanted)


def xmltv_url(playlist_text):
    """Pull the url-tvg / x-tvg-url attribute out of an M3U header."""
    if isinstance(playlist_text, bytes):
        playlist_text = playlist_text.decode('utf-8', 'replace')
    head = playlist_text[:2000]
    m = re.search(r'(?:url-tvg|x-tvg-url)="([^"]+)"', head)
    if not m:
        return ''
    # The attribute may list several files separated by commas.
    return m.group(1).split(',')[0].strip()


# ------------------------------------------------- provider native feeds

def from_xtream(payload, channel_id=''):
    """get_short_epg / get_simple_data_table -> [Programme]"""
    rows = []
    if isinstance(payload, dict):
        rows = payload.get('epg_listings') or payload.get('data') or []
    elif isinstance(payload, list):
        rows = payload
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = row.get('start_timestamp') or row.get('start')
        stop = row.get('stop_timestamp') or row.get('end') or row.get('stop')
        out.append(Programme(
            channel=str(row.get('channel_id') or channel_id),
            start=_epoch(start),
            stop=_epoch(stop),
            title=_b64(row.get('title')),
            desc=_b64(row.get('description') or row.get('descr'))))
    out.sort(key=lambda p: p.start)
    return out


def from_stalker(payload, channel_id=''):
    """itv/get_short_epg -> [Programme]"""
    rows = payload.get('js') if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = rows.get('data') or []
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append(Programme(
            channel=str(row.get('ch_id') or channel_id),
            start=_epoch(row.get('start_timestamp') or row.get('time')),
            stop=_epoch(row.get('stop_timestamp') or row.get('time_to')),
            title=str(row.get('name') or ''),
            desc=str(row.get('descr') or '')))
    out.sort(key=lambda p: p.start)
    return out


def _epoch(value):
    if value in (None, '', 0, '0'):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return parse_sql_time(text)


# ------------------------------------------------------------------ index

class EPGIndex(object):
    """Programmes for many channels, keyed by whatever id the source uses."""

    def __init__(self, data=None):
        self.data = data or {}

    def __len__(self):
        return sum(len(v) for v in self.data.values())

    def channels(self):
        return sorted(self.data)

    def put(self, channel_id, programmes):
        self.data[channel_id] = sorted(programmes, key=lambda p: p.start)

    def get(self, channel_id):
        return self.data.get(channel_id) or []

    def now_next(self, channel_id, at=None):
        """-> (current Programme or None, next Programme or None)"""
        at = int(at if at is not None else time.time())
        progs = self.get(channel_id)
        current = nxt = None
        for p in progs:
            if p.running_at(at):
                current = p
            elif p.start > at:
                nxt = p
                break
        if current is None and nxt is None and progs:
            future = [p for p in progs if p.start > at]
            nxt = future[0] if future else None
        return current, nxt

    def upcoming(self, channel_id, at=None, limit=50):
        at = int(at if at is not None else time.time())
        return [p for p in self.get(channel_id) if p.stop > at][:limit]

    # -------------------------------------------------------------- caching

    def save(self, path=CACHE):
        blob = {'at': int(time.time()), 'data': {}}
        for cid, progs in self.data.items():
            blob['data'][cid] = [[p.start, p.stop, p.title, p.desc]
                                 for p in progs]
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w') as fh:
                json.dump(blob, fh)
            replace_file(tmp, path)
            return True
        except (IOError, OSError):
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    @classmethod
    def load(cls, path=CACHE, ttl=CACHE_TTL):
        try:
            with open(path, 'r') as fh:
                blob = json.load(fh)
        except (IOError, OSError, ValueError):
            return None
        if not isinstance(blob, dict):
            return None
        if ttl and time.time() - blob.get('at', 0) > ttl:
            return None
        data = {}
        for cid, rows in (blob.get('data') or {}).items():
            data[cid] = [Programme(cid, r[0], r[1], r[2],
                                   r[3] if len(r) > 3 else '')
                         for r in rows if isinstance(r, list) and len(r) >= 3]
        return cls(data)
