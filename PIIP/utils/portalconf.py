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
"""Lists of Stalker portals, in the format everybody shares them in.

A stalkerclient.conf is one portal per line, the MAC glued onto the URL:

    http://portal.example.com:8080/c/mac=00:1A:79:00:00:00

Whitespace-separated "url mac" lines turn up just as often, so both are
accepted. Anything unparseable is skipped rather than fatal - these files
are hand-edited and pasted around, and one bad line should not lose the
other two hundred.
"""

import re
import subprocess

from .compat import native, devnull

try:
    from urllib.request import Request, urlopen
except ImportError:                                    # Python 2 images
    from urllib2 import Request, urlopen

# Where a portal list is normally left on a receiver, plus our own.
LOCAL_PATHS = ('/home/stalkerclient.conf',
               '/etc/enigma2/piip_portals.conf',
               '/root/portals.conf')

MAC = re.compile(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})')
URL = re.compile(r'(https?://[^\s,;|]+)', re.I)


# The API path a portal tends to be written with, which the provider adds
# back itself. Anchored at the end so a host with a /cdn/ in it is safe.
_API_PATH = re.compile(r'/(?:c|stalker_portal|portal\.php)(?:/.*)?$', re.I)


def normalise_portal(url):
    """The portal root, with the /c/ the servers expect."""
    url = native(url).strip()
    cut = url.lower().find('/c/mac=')
    if cut != -1:
        url = url[:cut]
    else:
        url = _API_PATH.sub('', url.rstrip('/'))
    return url.rstrip('/') + '/c/'


def parse(content):
    """Every portal in a list. Returns [{'portal': ..., 'mac': ...}]."""
    if isinstance(content, bytes):
        content = content.decode('utf-8', 'replace')
    out, seen = [], set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        url = URL.search(line)
        mac = MAC.search(line)
        if not url or not mac:
            continue
        entry = {'portal': normalise_portal(url.group(1)),
                 'mac': native(mac.group(1).upper())}
        key = (entry['portal'].lower(), entry['mac'])
        if key in seen:                     # these lists repeat themselves
            continue
        seen.add(key)
        out.append(entry)
    return out


def hostname(portal):
    """Just the host, which is what identifies a portal on screen."""
    text = native(portal or '')
    if '://' in text:
        text = text.split('://', 1)[1]
    return text.split('/', 1)[0]


def local_path(paths=None):
    """The first portal list already on this receiver, or ''."""
    import os
    for path in (paths or LOCAL_PATHS):
        if os.path.exists(path):
            return path
    return ''


def load_local(paths=None):
    """(entries, path). An empty path means there was no local file."""
    path = local_path(paths)
    if not path:
        return [], ''
    try:
        with open(path, 'rb') as fh:
            return parse(fh.read()), path
    except (IOError, OSError):
        return [], path


# Old receiver images commonly have a Python TLS stack which cannot verify
# the list host.  Some also ship a BusyBox wget which sends a request rejected
# by that host (HTTP 400), while their curl works.  Keep all three transports.
CURL = ('curl', '-k', '-L', '--silent', '--show-error', '--max-time')
WGET = ('wget', '-qO-', '--no-check-certificate', '--timeout=15', '--tries=1')

UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'


def fetch(url, timeout=20):
    """Download a portal list. Returns (entries, error)."""
    url = native(url or '').strip()
    if not url:
        return [], 'no list address is set'
    raw, error = _download(url, timeout)
    if raw is None:
        return [], error
    entries = parse(raw)
    if not entries:
        return [], 'downloaded %d bytes but found no portals in it' % len(raw)
    return entries, ''


def _download(url, timeout):
    try:
        request = Request(url, headers={'User-Agent': UA})
        handle = urlopen(request, timeout=timeout)
        try:
            return handle.read(), ''
        finally:
            handle.close()
    except Exception as exc:
        first = '%s: %s' % (type(exc).__name__, exc)

    # Second try: curl is more compatible with current HTTPS servers than the
    # BusyBox wget found on several Enigma2 images.
    try:
        out = subprocess.check_output(CURL + (str(int(timeout)),
                                               '-A', UA, url),
                                      stderr=devnull())
        if out:
            return out, ''
        curl_error = 'curl returned nothing'
    except Exception as exc:
        curl_error = 'curl: %s' % exc

    # Last try, retained for images which have wget but no curl.
    try:
        out = subprocess.check_output(WGET + (url,), stderr=devnull())
        if out:
            return out, ''
        return None, '%s; %s; wget returned nothing' % (first, curl_error)
    except Exception as exc:
        return None, '%s; %s; wget: %s' % (first, curl_error, exc)
