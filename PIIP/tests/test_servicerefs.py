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
"""The service reference format Enigma2 needs.

Headers ride on the URL after a '#', joined with '&'. Getting this wrong is
invisible in a unit test on a PC and shows up as a black screen on a
receiver, so it is pinned down here.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

from utils import servicerefs as sr

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


URL = 'https://cdn.tv/live/one/playlist.m3u8'

print('add_param()')
one = sr.add_param(URL, 'User-Agent', 'VLC/3.0')
check('the first header starts a fragment', one == URL + '#User-Agent=VLC%2F3.0',
      one)
two = sr.add_param(one, 'Cookie', 'a=b')
check('later headers are joined with &', two.endswith('&Cookie=a%3Db'), two)
check('only one fragment marker', two.count('#') == 1, two)
check('an empty value is skipped', sr.add_param(URL, 'X', '') == URL)
check('special characters are escaped',
      '%20' in sr.add_param(URL, 'User-Agent', 'a b'))
check('the separator itself is escaped, not literal',
      sr.add_param(URL, 'X', 'a&b').endswith('a%26b'))

print('')
print('stream_uri()')
uri = sr.stream_uri(URL)
check('a plain stream carries a user agent', 'User-Agent=' in uri, uri)
check('the url survives intact', uri.startswith(URL))
check('no cookie without a MAC', 'Cookie' not in uri)
check('an empty url stays empty', sr.stream_uri('') == '')
check('whitespace around the url is trimmed',
      sr.stream_uri('  ' + URL + '  ').startswith(URL))

tele = sr.stream_uri('https://cdn.telewebion.ir/live/test.m3u8')
for header in ('Referer', 'Origin', 'X-Requested-With', 'Connection'):
    check('Telewebion adds %s' % header, header + '=' in tele, tele)

mac = sr.stream_uri(URL, mac='00:1A:79:00:00:01')
check('a MAC adds the box identity', 'X-User-Agent=' in mac)
check('a MAC adds the portal cookie', 'Cookie=' in mac)
check('the cookie carries stb_lang', 'stb_lang' in mac.replace('%3B', ';')
      or 'stb_lang' in mac)

found = sr.stream_uri('http://p.tv/c/?mac=00%3A1A%3A79%3A11%3A22%3A33&x=1')
check('a MAC already in the url is picked up', 'Cookie=' in found, found[:90])

full = sr.stream_uri(URL, mac='00:1A:79:00:00:01', portal='http://p.tv',
                     token='TOK')
for header in ('User-Agent', 'X-User-Agent', 'Cookie', 'Referer',
               'Authorization'):
    check('%s present when applicable' % header, header + '=' in full)
check('bearer token formatted', 'Bearer' in full.replace('%20', ' '))

print('')
print('service types match the reference plugin')
check('gstreamer is 4097', sr.GSTREAMER == 4097)
check('exteplayer is 5002', sr.EXTEPLAYER == 5002)
check('service url is 8193', sr.SERVICE_URL == 8193)
check('widevine is 8197', sr.WIDEVINE == 8197)

print('')
print('make_ref() through the Enigma2 stub')
import enigma_stub
enigma_stub.install()
ref = sr.make_ref(URL, name='One HD', servicetype=4097)
check('a reference is built', ref is not None)
check('the type is carried', getattr(ref, 'type', None) == 4097,
      str(getattr(ref, 'type', None)))
check('the name is set', getattr(ref, 'name', '') == 'One HD')
check('the path carries the headers', 'User-Agent=' in getattr(ref, 'path', ''))
check('the name is a native str',
      isinstance(getattr(ref, 'name', ''), str))

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
