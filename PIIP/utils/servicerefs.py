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
"""Build the service reference Enigma2 needs to play a stream.

servicemp3 takes extra HTTP headers appended to the URL after a '#', joined
with '&':

    http://host/stream#User-Agent=VLC%2F3.0&Cookie=mac%3D00%3A1A...

Without them many providers answer 403, or simply never send data, and the
player sits on a black screen. This mirrors the convention the established
Enigma2 IPTV plugins use.
"""

import re

try:
    from urllib.parse import quote
except ImportError:                                    # Python 2 images
    from urllib import quote

from .compat import native

# A set-top box user agent: plain browser strings are refused by some panels.
USER_AGENT = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'
X_USER_AGENT = 'Model: MAG250; Link: WiFi'
COOKIE = 'mac=%s; stb_lang=en; timezone=Europe/London'

# Providers often carry the MAC in the stream URL itself.
MAC_IN_URL = re.compile(r'[?&]mac=([^&\s#|]+)')

GSTREAMER = 4097
EXTEPLAYER = 5002
SERVICE_URL = 8193
WIDEVINE = 8197


def add_param(uri, key, value):
    """Append one header to a stream URI the way servicemp3 expects."""
    if not value:
        return uri
    sep = '&' if '#' in uri else '#'
    return '%s%s%s=%s' % (uri, sep, key, quote(native(value), safe=''))


def stream_uri(url, user_agent=USER_AGENT, mac=None, portal=None, token=None):
    """The URL with its headers attached, ready for eServiceReference."""
    uri = native(url).strip()
    if not uri:
        return ''

    if mac is None:
        found = MAC_IN_URL.search(uri)
        if found:
            mac = found.group(1)

    uri = add_param(uri, 'User-Agent', user_agent)
    if 'telewebion.ir' in uri.lower():
        # Telewebion validates the Android/WebView request context. These are
        # the same four context headers observable in HybridIPTV's player.
        uri = add_param(uri, 'Referer', 'https://telewebion.ir/')
        uri = add_param(uri, 'Origin', 'https://telewebion.ir')
        uri = add_param(uri, 'X-Requested-With', 'ir.telewebion')
        uri = add_param(uri, 'Connection', 'keep-alive')
    if mac:
        # A Stalker portal only serves a box it recognises.
        uri = add_param(uri, 'X-User-Agent', X_USER_AGENT)
        uri = add_param(uri, 'Cookie', COOKIE % mac)
    if portal:
        uri = add_param(uri, 'Referer', portal)
    if token:
        uri = add_param(uri, 'Authorization', 'Bearer %s' % token)
    return uri


def make_ref(url, name='', servicetype=GSTREAMER, user_agent=USER_AGENT,
             mac=None, portal=None, token=None):
    """-> eServiceReference, or None when Enigma2 is not available."""
    from enigma import eServiceReference
    uri = stream_uri(url, user_agent=user_agent, mac=mac, portal=portal,
                     token=token)
    ref = eServiceReference(int(servicetype), 0, uri)
    if name:
        ref.setName(native(name))
    return ref
