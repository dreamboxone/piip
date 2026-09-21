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
"""Extended M3U playlist parsing."""

import re

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlparse, parse_qs
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen, HTTPError, URLError
    from urlparse import urlparse, parse_qs

from .models import MediaItem, LIVE, MOVIE, EPISODE

try:                                     # inside the plugin package
    from ..utils.compat import native
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import native

UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'

# Plenty of IPTV panels answer 403 to anything that does not look like a
# media player, so a refused request is retried as one of these.
PLAYER_AGENTS = (
    'VLC/3.0.20 LibVLC/3.0.20',
    'Lavf/58.76.100',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
)

# Statuses worth retrying with a different identity.
RETRY_STATUS = (401, 403, 406, 429)


_SECRET = re.compile(r'(password|pass|pwd|token|api_key)=([^&\s]*)', re.I)


def mask_url(url):
    """Hide credentials so a URL can be shown on screen or pasted."""
    return _SECRET.sub(lambda m: '%s=***' % m.group(1), native(url))


def server_says(exc, limit=160):
    """The body of an error response, which usually explains the refusal."""
    reader = getattr(exc, 'read', None)
    if reader is None:
        return ''
    try:
        raw = reader()
    except Exception:
        return ''
    if not raw:
        return ''
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    # Panels answer with HTML as often as with plain text.
    text = re.sub(r'<[^>]+>', ' ', text)
    text = ' '.join(text.split())
    if not text:
        return ''
    return text[:limit] + ('...' if len(text) > limit else '')


def error_text(exc):
    """A message that actually says what went wrong."""
    code = getattr(exc, 'code', None)
    if code is not None:
        reason = getattr(exc, 'reason', '') or getattr(exc, 'msg', '')
        out = 'HTTP %s%s' % (code, ' %s' % reason if reason else '')
        body = server_says(exc)
        return '%s - "%s"' % (out, body) if body else out
    reason = getattr(exc, 'reason', None)
    if reason is not None:
        return '%s (%s)' % (reason, type(exc).__name__)
    return '%s: %s' % (type(exc).__name__, exc)


def probe(url, timeout=20, user_agent=UA, agents=PLAYER_AGENTS):
    """Try a playlist and describe the outcome, for the diagnostics screen."""
    tried = [user_agent] + [a for a in agents if a != user_agent]
    last = ''
    for agent in tried:
        try:
            raw = _download(url, timeout, agent)
        except Exception as exc:
            last = error_text(exc)
            code = getattr(exc, 'code', None)
            if code is not None and code not in RETRY_STATUS:
                break
            continue
        items = parse(raw)
        note = 'OK - %d channels, %d bytes' % (len(items), len(raw))
        if agent != user_agent:
            note += ' (needed %s)' % agent.split('/')[0]
        if not items:
            note = ('downloaded %d bytes but found no channels - '
                    'is this really an M3U?' % len(raw))
        return note
    return last or 'no response'


_ATTR = re.compile(r'([\w-]+)="([^"]*)"')

# Xtream-style playlists encode the content type in the path, which is the
# only reliable signal an M3U gives us about what a line actually is.
_MOVIE_URL = re.compile(r'/(movie|movies|vod)/', re.I)
_SERIES_URL = re.compile(r'/series/', re.I)
_SXXEYY = re.compile(r'\bS(\d{1,2})[\s._-]*E(\d{1,3})\b', re.I)

# Kept as an alias so existing code and tests keep working.
Channel = MediaItem


def extinf_name(line):
    """The channel name, which is whatever follows the attributes.

    Splitting on the first comma breaks any playlist carrying a User-Agent
    in the EXTINF line, since browser UA strings are full of commas. Taking
    the last comma instead would truncate names that contain one. So the
    split is the first comma AFTER the final quoted attribute.
    """
    last_quote = line.rfind('"')
    if last_quote != -1:
        cut = line.find(',', last_quote)
        if cut != -1:
            return line[cut + 1:].strip()
    cut = line.find(',')
    return line[cut + 1:].strip() if cut != -1 else ''


def classify(url, group='', name=''):
    """Guess whether an entry is live, a movie or an episode."""
    if _SERIES_URL.search(url) or _SXXEYY.search(name):
        return EPISODE
    if _MOVIE_URL.search(url):
        return MOVIE
    blob = group.lower()
    if any(w in blob for w in ('vod', 'movie', 'film', 'cinema')):
        return MOVIE
    if any(w in blob for w in ('series', 'serie', 'show')):
        return EPISODE
    return LIVE


def parse(text, classify_kind=True):
    """Parse an extended M3U into a list of MediaItem."""
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    items = []
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            attrs = dict(_ATTR.findall(line))
            name = extinf_name(line)
            pending = MediaItem(
                name=name or attrs.get('tvg-name', 'unnamed'),
                url='',
                logo=attrs.get('tvg-logo', ''),
                group=attrs.get('group-title', ''),
                tvg_id=attrs.get('tvg-id', ''),
                tvg_name=attrs.get('tvg-name', ''))
        elif line.startswith('#EXTGRP:') and pending is not None:
            pending.group = line[len('#EXTGRP:'):].strip()
        elif line.startswith('#'):
            continue
        elif pending is not None:
            pending.url = line
            if classify_kind:
                pending.kind = classify(line, pending.group, pending.name)
                _fill_episode_numbers(pending)
            items.append(pending)
            pending = None
        elif _playable(line):
            # A bare URL list with no #EXTINF headers at all.
            items.append(MediaItem(name=line, url=line))
    return items


_SCHEME = re.compile(r'^(https?|rtmpe?|rtsp|udp|rtp|file)://', re.I)


def _playable(line):
    """Whether a header-less line could be a stream at all.

    Without this an HTML error page from a provider turns into a screenful
    of nonsense channels instead of an error.
    """
    return bool(_SCHEME.match(line)) or line.startswith('/')


def _fill_episode_numbers(item):
    if item.kind != EPISODE:
        return
    m = _SXXEYY.search(item.name)
    if m:
        item.season = int(m.group(1))
        item.episode = int(m.group(2))


def _download(url, timeout, user_agent):
    req = Request(url, headers={'User-Agent': user_agent,
                                'Accept': '*/*',
                                'Connection': 'close'})
    fh = urlopen(req, timeout=timeout)
    try:
        return fh.read()
    finally:
        fh.close()


def xtream_credentials(url):
    """(host, username, password, output) of an Xtream get.php link, or None.

    A panel's "M3U link" is its API in disguise. Reading the channels
    through player_api.php is far quicker than a multi-megabyte m3u_plus
    download, and is not refused as often.
    """
    try:
        parsed = urlparse(native(url).strip())
    except Exception:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    if not parsed.path.lower().endswith('/get.php'):
        return None
    query = parse_qs(parsed.query)
    user = (query.get('username') or [''])[0]
    password = (query.get('password') or [''])[0]
    if not user or not password:
        return None
    base = parsed.path[:-len('/get.php')]
    host = '%s://%s%s' % (parsed.scheme, parsed.netloc, base)
    output = (query.get('output') or ['ts'])[0].lower()
    if output in ('hls', 'm3u8'):
        output = 'm3u8'
    elif output not in ('ts', 'mpegts'):
        output = 'ts'
    return host, user, password, 'ts' if output == 'mpegts' else output


def fetch_xtream_live(url, timeout=30, user_agent=UA):
    """The live channels of a get.php link, read through the panel's API."""
    creds = xtream_credentials(url)
    if creds is None:
        raise ValueError('not an Xtream get.php link')
    host, user, password, output = creds
    from .xtream import Xtream
    api = Xtream(host, user, password, timeout=timeout, user_agent=user_agent)
    names = dict(api.live_categories())
    items = api.live_streams()
    for item in items:
        item.group = names.get(item.group, item.group or 'Ungrouped')
        item.ext = output
        item.url = api.stream_url(item.item_id, output)
    return items


def fetch(url, timeout=30, user_agent=UA, agents=PLAYER_AGENTS, kinds=None):
    """Download and parse a playlist, retrying as a player when refused.

    `kinds` names the entry types the caller wants. When only live channels
    are wanted from an Xtream get.php link they come from the panel's API,
    falling back to the playlist itself if the API will not answer.
    """
    live_only = kinds is not None and set(kinds) <= set([LIVE])
    if live_only and xtream_credentials(url) is not None:
        try:
            items = fetch_xtream_live(url, timeout=timeout,
                                      user_agent=user_agent)
            if items:
                return items
        except Exception:
            pass
    tried = [user_agent]
    for agent in agents:
        if agent not in tried:
            tried.append(agent)

    last = None
    for agent in tried:
        try:
            return parse(_download(url, timeout, agent))
        except HTTPError as exc:
            last = exc
            if exc.code not in RETRY_STATUS:
                raise
        except URLError:
            raise
    if last is not None:
        raise last
    return []


def load(path):
    with open(path, 'rb') as fh:
        return parse(fh.read())


def load_all(settings_url='', user_agent=UA, timeout=30, paths=None,
             kinds=None):
    """Every configured playlist, merged.

    The settings field and each line of the playlist list file are loaded.
    Group names are prefixed with the playlist name so a channel's origin
    stays visible once several providers are mixed together.

    Returns (items, errors) - a failing playlist never hides the others.
    """
    try:                                     # inside the plugin package
        from ..utils import playlists
    except (ImportError, ValueError):        # imported standalone (tests)
        from utils import playlists

    sources = []
    settings_url = (settings_url or '').strip()
    if settings_url and settings_url not in ('http://', 'https://'):
        sources.append(playlists.Entry('', settings_url))
    file_entries = playlists.load() if paths is None else playlists.load(paths)
    sources.extend(file_entries)

    items, errors = [], []
    multiple = len(sources) > 1
    for entry in sources:
        try:
            if '://' in entry.url:
                found = fetch(entry.url, timeout=timeout,
                              user_agent=user_agent, kinds=kinds)
            else:
                found = load(entry.url)
        except Exception as exc:
            errors.append('%s: %s' % (entry.name or entry.url,
                                      error_text(exc)))
            continue
        if multiple and entry.name:
            for item in found:
                item.group = '%s / %s' % (entry.name,
                                          item.group or 'Ungrouped')
        items.extend(found)
    return items, errors


def groups(items):
    """Ordered unique group names."""
    seen, out = set(), []
    for c in items:
        g = c.group or 'Ungrouped'
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def of_kind(items, kind):
    return [i for i in items if i.kind == kind]


def series_from_episodes(items):
    """Group loose episodes into {series name: [episodes]} for M3U sources."""
    out = {}
    for i in items:
        if i.kind != EPISODE:
            continue
        # The series name is whatever precedes the SxxEyy marker; stripping
        # the marker out of the middle would leave the episode title glued on.
        m = _SXXEYY.search(i.name)
        title = (i.name[:m.start()] if m else i.name).strip(' -_.')
        out.setdefault(title or i.group or 'Unknown', []).append(i)
    for eps in out.values():
        eps.sort(key=lambda e: (e.season, e.episode, e.name))
    return out
