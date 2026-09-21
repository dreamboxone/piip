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
"""Guide data for M3U channels from the receiver's own EPG cache.

Most playlists carry no XMLTV address, yet the receiver already holds a
guide for the satellite channels many of them restream. A channel is
matched to a receiver service two ways:

  1. its tvg-id, when that is an Enigma2 service reference
     (1:0:19:2B66:3F3:1:C00000:0:0:0: - what e2m3u2bouquet style lists use);
  2. its name, against the names of the services in the user's bouquets.

Reading the bouquets walks eServiceCenter, which is not safe off the main
loop, so prepare() must run there. Looking events up afterwards only takes
eEPGCache's own lock and is fine from a worker thread.
"""

import re
import time

try:                                     # inside the plugin package
    from ..providers.epg import Programme
    from .compat import native
except (ImportError, ValueError):        # imported standalone (tests)
    from providers.epg import Programme
    from utils.compat import native

_SERVICE_REF = re.compile(r'^\d+:\d+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:'
                          r'[0-9A-Fa-f]+:[0-9A-Fa-f]+(?::[0-9A-Fa-f]*)*:?$')

# Words that differ between a stream's name and the broadcast service's.
_NOISE = re.compile(r'\b(uhd|fhd|hd|sd|4k|8k|hevc|h26[45]|backup|raw|\+1|'
                    r'\d{3,4}[pi]|\d{3,4})\b')
# "(720p)", "[Not 24/7]", "[Geo-blocked]": playlist annotations, not names.
_BRACKETS = re.compile(r'[\(\[\{][^\)\]\}]*[\)\]\}]')

# A containment match only counts when the shorter name is most of the
# longer: "bbcone" in "bbconehd" is the channel, "show" in
# "30athebeachshow" is a different one.
MIN_FUZZY_LEN = 5
MIN_FUZZY_RATIO = 0.7
_NOT_ALNUM = re.compile(r'[\W_]+', re.U)

_names = {}                              # normalised name -> service ref
_prepared_at = 0.0
NAME_TTL = 900                           # re-read bouquets after 15 minutes


def normalise_name(name):
    text = name or ''
    if isinstance(text, bytes):
        # Python 2 hands names over as UTF-8 bytes, where \W would strip
        # every non-Latin letter and leave Persian names empty.
        text = text.decode('utf-8', 'replace')
    text = text.lower()
    text = re.sub(r'^[a-z]{2,3}\s*[:|-]\s*', '', text)   # "UK: BBC One"
    text = _BRACKETS.sub(' ', text)
    text = _NOISE.sub(' ', text)
    return _NOT_ALNUM.sub('', text)


def ref_from_tvg_id(tvg_id):
    """The tvg-id as a playable-service reference string, or ''."""
    text = native(tvg_id or '').strip()
    if not _SERVICE_REF.match(text):
        return ''
    parts = text.rstrip(':').split(':')
    parts = (parts + ['0'] * 10)[:10]
    # The guide is keyed on DVB services: service type 1, no stream URL.
    parts[0] = '1'
    return ':'.join(parts) + ':'


def set_names(mapping):
    """Replace the name index (used by prepare() and by tests)."""
    global _names, _prepared_at
    _names = dict((normalise_name(k), v) for k, v in mapping.items()
                  if normalise_name(k))
    _prepared_at = time.time()


def prepared():
    return bool(_names) and time.time() - _prepared_at < NAME_TTL


def prepare(force=False):
    """Index the names of the services in the TV bouquets. Main loop only."""
    if prepared() and not force:
        return len(_names)
    try:
        from enigma import eServiceCenter, eServiceReference
    except ImportError:
        return 0
    found = {}
    try:
        center = eServiceCenter.getInstance()
        root = eServiceReference('1:7:1:0:0:0:0:0:0:0:FROM BOUQUET '
                                 '"bouquets.tv" ORDER BY bouquet')
        bouquets = center.list(root)
        for bouquet_ref, _name in (bouquets.getContent('SN', True)
                                   if bouquets else []):
            services = center.list(eServiceReference(bouquet_ref))
            if not services:
                continue
            for ref, name in services.getContent('SN', True):
                # Skip markers, sub-bouquets and IPTV entries: only a DVB
                # service has guide data behind it.
                if not ref.startswith('1:0:') or '://' in ref or \
                        '%3a//' in ref.lower():
                    continue
                key = normalise_name(name)
                if key and key not in found:
                    found[key] = ref
    except Exception:
        return 0
    set_names(found)
    return len(found)


def match_ref(item):
    """The receiver service reference for an M3U channel, or ''."""
    ref = ref_from_tvg_id(getattr(item, 'tvg_id', ''))
    if ref:
        return ref
    if not _names:
        return ''
    for candidate in (getattr(item, 'tvg_name', ''), getattr(item, 'name', ''),
                      getattr(item, 'tvg_id', '')):
        key = normalise_name(candidate)
        if not key:
            continue
        if key in _names:
            return _names[key]
    key = normalise_name(getattr(item, 'name', ''))
    if len(key) < MIN_FUZZY_LEN:
        return ''
    # A close name either way round: "bbconeplus" and "bbcone".
    best = ''
    for name in _names:
        if len(name) < MIN_FUZZY_LEN or not (name in key or key in name):
            continue
        if min(len(name), len(key)) < MIN_FUZZY_RATIO * max(len(name), len(key)):
            continue
        if not best or abs(len(name) - len(key)) < abs(len(best) - len(key)):
            best = name
    return _names[best] if best else ''


def _cache():
    try:
        from enigma import eEPGCache
    except ImportError:
        return None
    try:
        return eEPGCache.getInstance()
    except Exception:
        return None


def programmes(item, hours=24, cache=None):
    """[Programme] for the channel from now on, from the receiver's guide."""
    ref = match_ref(item)
    if not ref:
        return []
    cache = cache if cache is not None else _cache()
    if cache is None:
        return []
    try:
        # B begin, D duration, T title, S short description, E extended.
        # Type 0 from -1 (now) over `hours` gives every event in the window.
        rows = cache.lookupEvent(['BDTSE', (ref, 0, -1, int(hours) * 60)])
    except Exception:
        return []
    out, seen = [], set()
    for row in rows or []:
        if not row or len(row) < 3 or row[0] is None or not row[2]:
            continue
        try:
            begin, duration = int(row[0]), int(row[1] or 0)
        except (TypeError, ValueError):
            continue
        if begin in seen:
            continue
        seen.add(begin)
        desc = ''
        if len(row) > 4 and row[4]:
            desc = row[4]
        elif len(row) > 3 and row[3]:
            desc = row[3]
        out.append(Programme(channel=ref, start=begin, stop=begin + duration,
                             title=native(row[2]), desc=native(desc)))
    out.sort(key=lambda p: p.start)
    return out
