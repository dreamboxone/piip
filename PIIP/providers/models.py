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
"""One item type for everything playable: live channel, movie or episode.

The player only ever needs .name and .url, so a single class keeps the
playback path identical whether you are watching a channel or episode 7 of
season 2. The extra fields are metadata for the list screens.
"""

try:                                     # inside the plugin package
    from ..utils.compat import native
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import native

LIVE = 'live'
MOVIE = 'movie'
EPISODE = 'episode'
SERIES = 'series'


class MediaItem(object):
    __slots__ = (
        'name', 'url', 'logo', 'group', 'kind',
        'tvg_id', 'tvg_name',
        'item_id', 'ext', 'duration', 'plot', 'rating', 'year', 'backdrop',
        'series_id', 'season', 'episode',
        'auth_token', 'portal_url', 'mac', 'archive', 'cmd', 'added',
    )

    def __init__(self, name, url='', logo='', group='', kind=LIVE,
                 tvg_id='', tvg_name='', item_id='', ext='',
                 duration=0, plot='', rating='', year='', backdrop='',
                 series_id='', season=0, episode=0, auth_token='',
                 portal_url='', mac='', archive=0, cmd='', added=0):
        # Everything here can end up in a widget, and on Python 2 the
        # providers hand us unicode (json.loads) which SWIG refuses.
        self.name = native(name)
        self.url = native(url)
        self.logo = native(logo)
        self.group = native(group)
        self.kind = native(kind)
        self.tvg_id = native(tvg_id)
        self.tvg_name = native(tvg_name)
        self.item_id = native(item_id)
        self.ext = native(ext)
        self.duration = duration          # seconds, 0 when unknown
        self.plot = native(plot)
        self.rating = native(rating)
        self.year = native(year)
        self.backdrop = native(backdrop)
        self.series_id = native(series_id)
        self.season = season
        self.episode = episode
        self.auth_token = native(auth_token)
        self.portal_url = native(portal_url)
        self.mac = native(mac)
        # Days of recordings the portal keeps for a live channel; 0 is none.
        self.archive = archive
        # A Stalker portal's play token, exchanged through create_link.
        self.cmd = native(cmd)
        # When the provider added it (Unix time), for newest-first lists.
        self.added = added

    @property
    def is_live(self):
        return self.kind == LIVE

    @property
    def seekable(self):
        """Live streams cannot be seeked; recorded content can."""
        return self.kind in (MOVIE, EPISODE)

    def resume_key(self):
        """Stable identity for storing a resume position."""
        if self.kind == EPISODE:
            return 'ep:%s' % (self.item_id or self.url)
        if self.kind == MOVIE:
            return 'mv:%s' % (self.item_id or self.url)
        return ''

    def label(self):
        """What the list screens show."""
        if self.kind == EPISODE and self.season and self.episode:
            return 'S%02dE%02d  %s' % (self.season, self.episode, self.name)
        if self.year:
            return '%s (%s)' % (self.name, self.year)
        return self.name

    def __repr__(self):
        return '<%s %r>' % (self.kind, self.name)


def human_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ''
    if seconds <= 0:
        return ''
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return '%d:%02d:%02d' % (h, m, s)
    return '%d:%02d' % (m, s)


def parse_duration(value):
    """Xtream gives duration either as seconds or as 'HH:MM:SS'."""
    if value in (None, '', 0):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    parts = text.split(':')
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    total = 0
    for p in parts:
        total = total * 60 + p
    return total
