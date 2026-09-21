#!/usr/bin/env python
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
"""PIIP — IPTV player with live Persian audio translation via Gemini.

Entry point and configuration. Nothing heavy runs here: the translation
pipeline lives in its own process (see translate/engine.py) so that moving
several MB/s of video never blocks the Enigma2 main loop.
"""

from Plugins.Plugin import PluginDescriptor
from Components.config import (
    config, ConfigSubsection, ConfigText, ConfigPassword, ConfigYesNo,
    ConfigSelection, ConfigInteger, ConfigSlider, ConfigDirectory,
)

NAME = 'PIIP'
VERSION = '3.0'

config.plugins.piip = ConfigSubsection()
_c = config.plugins.piip

# ---- source ---------------------------------------------------------------
_c.source = ConfigSelection(default='m3u', choices=[
    ('m3u', 'M3U playlist'),
    ('xtream', 'Xtream Codes'),
    ('stalker', 'Stalker portal (MAC)'),
])
_c.m3u_url = ConfigText(default='http://', fixed_size=False)
_c.xtream_host = ConfigText(default='http://', fixed_size=False)
_c.xtream_user = ConfigText(default='', fixed_size=False)
_c.xtream_pass = ConfigPassword(default='')
_c.stalker_portal = ConfigText(default='http://', fixed_size=False)
_c.stalker_mac = ConfigText(default='00:1A:79:00:00:00', fixed_size=False)
# The name of the saved server these values were copied from, so a
# screen can say which one it is showing.
_c.active_server = ConfigText(default='', fixed_size=False)
# Where LOAD ONLINE fetches a Stalker portal list from. Public
# lists move about, so this is a field rather than a constant.
_c.portal_list_url = ConfigText(
    default='https://satelliweb.gt.tc/stalker_list.log',
    fixed_size=False)

# ---- translation ----------------------------------------------------------
# Off by default: translation costs money on every minute watched, so
# it is something you switch on deliberately.
_c.translate = ConfigYesNo(default=False)
_c.api_key = ConfigText(default='', fixed_size=False)
# Gemini 3.5 Live Translate is the only model built for speech-to-speech
# translation, so there is nothing to choose between.
MODEL = 'gemini-3.5-live-translate-preview'
# Still overridable by hand, so a newer model can be used without an update.
_c.model_custom = ConfigText(default='', fixed_size=False)
_c.language = ConfigSelection(default='Persian', choices=[
    ('Persian', 'Persian / فارسی'),
    ('Arabic', 'Arabic / العربية'),
    ('English', 'English'),
    ('Turkish', 'Turkish / Türkçe'),
])

# Delay must cover the whole round trip: decode -> Gemini -> speech back.
_c.delay = ConfigSlider(default=6, increment=1, limits=(1, 12))
# Once the translation falls this far behind the picture, drop the oldest
# audio and re-anchor to what is on screen now.
_c.max_backlog = ConfigSlider(default=6, increment=1, limits=(2, 20))
# On a weak connection a lighter HLS rendition keeps the picture moving;
# only master playlists offer a choice, others play as they are.
# 3 Mbit/s by default: measured on the target receiver, a 6.2 Mbit/s 1080p
# rendition was delivered at only 93% of real time through the translation
# pipeline and the picture stuttered; 1.7 Mbit/s played without a stall.
_c.translate_max_bitrate = ConfigSelection(default='3000000', choices=[
    ('0', 'Automatic (best)'), ('1500000', '1.5 Mbit/s'),
    ('3000000', '3 Mbit/s'), ('5000000', '5 Mbit/s'),
])

# ---- subtitles ------------------------------------------------------------
_c.opensubtitles_key = ConfigText(default='', fixed_size=False)
_c.subdl_key = ConfigText(default='', fixed_size=False)
_c.sub_language = ConfigSelection(default='Persian', choices=[
    ('Persian', 'Persian / فارسی'),
    ('Arabic', 'Arabic / العربية'),
    ('English', 'English'),
    ('Turkish', 'Turkish / Türkçe'),
])
_c.sub_size = ConfigSelection(default='medium', choices=[
    ('small', 'Small'), ('medium', 'Medium'),
    ('large', 'Large'), ('extra', 'Extra large'),
])
_c.sub_position = ConfigSelection(default='bottom', choices=[
    ('bottom', 'Bottom'), ('middle', 'Middle'), ('top', 'Top'),
])
_c.sub_color = ConfigSelection(default='white', choices=[
    ('white', 'White'), ('yellow', 'Yellow'), ('green', 'Green'),
])
# Our stream is delayed, so a per-user nudge is usually needed.
_c.sub_offset = ConfigInteger(default=0, limits=(-60000, 60000))

# ---- HybridIPTV parity ----------------------------------------------------
_c.download_dir = ConfigDirectory(default='/media/hdd/movie/')
_c.picon_cache_dir = ConfigDirectory(default='/media/hdd/.piip_cache/')
_c.show_adult = ConfigYesNo(default=False)
_c.poster_count = ConfigSelection(default='20', choices=[
    ('10', '10 items / page'), ('20', '20 items / page'),
    ('30', '30 items / page'), ('40', '40 items / page'),
    ('50', '50 items / page'),
])
_c.skin_style = ConfigSelection(default='default', choices=[
    ('default', 'Default'), ('hybrid', 'Hybrid carousel'),
    ('cover', 'Cover collection'), ('cover2d', '2D cover collection'),
])
_c.tmdb_key = ConfigText(default='', fixed_size=False)

# ---- epg ------------------------------------------------------------------
_c.epg_enabled = ConfigYesNo(default=True)
# Only needed for M3U sources whose playlist has no url-tvg attribute.
_c.xmltv_url = ConfigText(default='', fixed_size=False)

# ---- mixing ---------------------------------------------------------------
# Volume is a share of the source, never an amplifier: going past 100%
# only clips the mix.
_c.vol_original = ConfigSlider(default=30, increment=5, limits=(0, 100))
_c.vol_translated = ConfigSlider(default=100, increment=5, limits=(0, 100))

# ---- plumbing -------------------------------------------------------------
_c.http_port = ConfigInteger(default=8901, limits=(1024, 65535))
_c.control_port = ConfigInteger(default=8902, limits=(1024, 65535))
# HybridIPTV also uses 8903.  PIIP may be installed beside it during
# migration/testing, so use a distinct default to let both resolvers start.
_c.resolver_port = ConfigInteger(default=8913, limits=(1024, 65535))
_c.webif_port = ConfigInteger(default=8914, limits=(1024, 65535))
# Bouquet entries can carry translated audio, at the cost of a couple of
# seconds of start-up on every zap.
_c.bouquet_translate = ConfigYesNo(default=False)
_c.ffmpeg = ConfigText(default='ffmpeg', fixed_size=False)
_c.service_type = ConfigSelection(default='4097', choices=[
    ('4097', '4097 (gstreamer)'),
    ('5002', '5002 (exteplayer3)'),
    ('8193', '8193 (ServiceURL)'),
    ('8197', '8197 (widevine)'),
])
_c.vod_streamtype = ConfigSelection(default='4097', choices=[
    ('4097', '4097 (gstreamer)'),
    ('5002', '5002 (exteplayer3)'),
    ('8193', '8193 (ServiceURL)'),
    ('8197', '8197 (widevine)'),
])
_c.user_agent = ConfigText(
    default='Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3',
    fixed_size=False)


def make_stalker():
    """A Stalker client built from the current settings."""
    from .providers.stalker import Stalker
    return Stalker(_c.stalker_portal.value, _c.stalker_mac.value,
                   user_agent=_c.user_agent.value)


def api_key():
    """The Gemini key: apikey.txt wins over anything typed in settings."""
    from .utils.apikey import find
    return find(_c.api_key.value)[0]


def engine_config(url, item=None, start_at=0.0, diag_dir=None):
    """Build the JSON config handed to the engine process.

    Note this dict is written to the engine's stdin, never passed as command
    line arguments, so the key never shows up in the process list.
    """
    key = api_key()
    recorded = bool(item is not None and getattr(item, 'seekable', False))
    headers = {}
    if item is not None and getattr(item, 'mac', ''):
        from .providers.stalker import X_UA
        from .utils.servicerefs import COOKIE
        headers = {
            'X-User-Agent': X_UA,
            'Cookie': COOKIE % item.mac,
            'Referer': getattr(item, 'portal_url', '') or '',
            'Authorization': ('Bearer %s' % item.auth_token
                              if getattr(item, 'auth_token', '') else ''),
        }
    if 'telewebion.ir' in (url or '').lower():
        headers.update({
            'Referer': 'https://telewebion.ir/',
            'Origin': 'https://telewebion.ir',
            'X-Requested-With': 'ir.telewebion',
            'Connection': 'keep-alive',
        })
    translating = bool(_c.translate.value) and bool(key)
    tap_mb = 0
    try:
        from .utils import diaglog
        watch = diaglog.active_watch()
        if translating and not diag_dir:
            # Bouquet zaps come through here without a player screen.
            diag_dir = diaglog.new_dir('zap', getattr(item, 'name', ''))
        if watch:
            tap_mb = int(watch.get('tap_mb') or 0)
    except Exception:
        pass
    return {
        'url': url,
        'diag_dir': diag_dir or '',
        'tap_mb': tap_mb,
        # Movies and episodes are files: without -re ffmpeg would read them
        # as fast as the disk allows and swamp the delay buffer.
        'realtime': recorded,
        'start_at': float(start_at or 0),
        'duration': int(getattr(item, 'duration', 0) or 0),
        'api_key': key,
        'model': (_c.model_custom.value.strip() or MODEL),
        'language': _c.language.value,
        'translate': bool(_c.translate.value) and bool(key),
        # Only reached when translating; kept for the resolver, which can
        # be asked for an untouched stream.
        'passthrough': not (bool(_c.translate.value) and bool(key)),
        'delay': float(_c.delay.value),
        'max_backlog': float(_c.max_backlog.value),
        'max_bandwidth': int(_c.translate_max_bitrate.value or 0),
        'gain_original': _c.vol_original.value / 100.0,
        'gain_translated': _c.vol_translated.value / 100.0,
        'http_port': int(_c.http_port.value),
        'control_port': int(_c.control_port.value),
        'ffmpeg': _c.ffmpeg.value,
        'user_agent': _c.user_agent.value,
        'http_headers': headers,
    }


def ensure_playlist_file():
    """Create /root/m3u.txt on first run so it is there to be filled in."""
    try:
        from .utils.playlists import ensure
        created = ensure()
        if created:
            print('[PIIP] created playlist list at %s' % created)
    except Exception as e:
        print('[PIIP] could not create the playlist list: %s' % e)


def start_resolver():
    """Bouquet entries are dead without this, so it starts with Enigma2."""
    try:
        from .translate import resolver
        from .utils.bouquet import MAP_FILE
        resolver.configure(map_file=MAP_FILE,
                           port=int(_c.resolver_port.value),
                           engine_config=engine_config,
                           stalker_factory=make_stalker)
        resolver.start()
    except Exception as e:
        print('[PIIP] resolver did not start: %s' % e)


def start_webif():
    try:
        from .utils import webif
        webif.configure(config=_c, free_url=_c.portal_list_url.value)
        webif.start(int(_c.webif_port.value))
    except Exception as e:
        print('[PIIP] WebIF did not start: %s' % e)


def sessionstart(reason, session=None, **kwargs):
    """Start the decoder sampler used by playback diagnostics."""
    if session is None:
        return
    try:
        from .utils import diagagent
        diagagent.start(session)
    except Exception as e:
        print('[PIIP] diagnostics agent did not start: %s' % e)


def main(session, **kwargs):
    from .main import FarsiMain
    session.open(FarsiMain)


def Plugins(**kwargs):
    ensure_playlist_file()
    start_resolver()
    start_webif()
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART,
                         fnc=sessionstart),
        PluginDescriptor(
            name='PIIP',
            description='Xtream / M3U /Stalker IPTV Player with translation',
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon='icon.png',
            fnc=main,
        )
    ]
