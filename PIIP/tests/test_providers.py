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
"""Tests for the M3U parser and Xtream URL building."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import m3u
from providers.xtream import Xtream

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


SAMPLE = u'''#EXTM3U url-tvg="http://x/epg.xml"
#EXTINF:-1 tvg-id="bbc1.uk" tvg-name="BBC One" tvg-logo="http://l/bbc.png" group-title="UK",BBC One HD
http://server/live/u/p/101.ts
#EXTINF:-1 tvg-id="cnn.us" tvg-logo="http://l/cnn.png" group-title="News",CNN International
#EXTGRP:World News
http://server/live/u/p/102.ts
#EXTINF:-1,Plain Channel
http://server/live/u/p/103.ts

# a stray comment
#EXTINF:-1 tvg-name="Only Tvg" group-title="UK",
http://server/live/u/p/104.ts
'''

print('M3U parsing')
ch = m3u.parse(SAMPLE)
check('parses all entries', len(ch) == 4, 'got %d' % len(ch))
check('name after comma', ch[0].name == 'BBC One HD', ch[0].name)
check('tvg-id attribute', ch[0].tvg_id == 'bbc1.uk')
check('tvg-logo attribute', ch[0].logo == 'http://l/bbc.png')
check('group-title attribute', ch[0].group == 'UK')
check('url follows EXTINF', ch[0].url == 'http://server/live/u/p/101.ts')
check('EXTGRP overrides group-title', ch[1].group == 'World News', ch[1].group)
check('entry without attributes', ch[2].name == 'Plain Channel')
check('empty name falls back to tvg-name', ch[3].name == 'Only Tvg', ch[3].name)
check('comments ignored', all(not c.name.startswith('#') for c in ch))

check('bytes input accepted', len(m3u.parse(SAMPLE.encode('utf-8'))) == 4)
check('empty playlist is empty', m3u.parse(u'#EXTM3U\n') == [])
check('blank input is safe', m3u.parse(u'') == [])

g = m3u.groups(ch)
check('groups are unique and ordered',
      g == ['UK', 'World News', 'Ungrouped'], str(g))
check('groupless channels land in Ungrouped', ch[2].group == '')

utf8 = u'#EXTM3U\n#EXTINF:-1 group-title="\u0641\u0627\u0631\u0633\u06cc",\u0634\u0628\u06a9\u0647 \u06f3\nhttp://s/1.ts\n'
cu = m3u.parse(utf8)
check('unicode names survive', cu[0].name == u'\u0634\u0628\u06a9\u0647 \u06f3')
check('unicode groups survive', cu[0].group == u'\u0641\u0627\u0631\u0633\u06cc')

# a bare URL list with no EXTINF at all
bare = m3u.parse(u'http://a/1.ts\nhttp://a/2.ts\n')
check('bare url list works', len(bare) == 2 and bare[0].url == 'http://a/1.ts')

print('\nXtream URL building')
x = Xtream('http://srv.tv:8080', 'user', 'pass')
check('stream url shape',
      x.stream_url(101) == 'http://srv.tv:8080/live/user/pass/101.ts',
      x.stream_url(101))
check('extension override', x.stream_url(101, 'm3u8').endswith('/101.m3u8'))

x2 = Xtream('srv.tv:8080/', 'user', 'pass')
check('scheme added, trailing slash trimmed',
      x2.host == 'http://srv.tv:8080', x2.host)

x3 = Xtream('http://srv.tv', 'us er', 'p@ss/w+d')
u = x3.stream_url(7)
check('credentials are url-encoded',
      'us%20er' in u and 'p%40ss%2Fw%2Bd' in u, u)

check('status is None before login', x.status() is None)

print('\nXtream behaviour matched to the reference')
from providers import xtream as xm


class FakeXtream(xm.Xtream):
    def __init__(self, replies):
        xm.Xtream.__init__(self, 'http://srv.tv', 'u', 'p')
        self.replies = replies

    def _api(self, **params):
        return self.replies.get(params.get('action'))


fx = FakeXtream({
    'get_vod_categories': [{'category_id': '1', 'category_name': 'Drama &amp; Crime'}],
    'get_vod_streams': [
        {'stream_id': 1, 'name': 'Old', 'category_id': '1', 'added': '1600000000'},
        {'stream_id': 2, 'name': 'Tom &amp; Jerry', 'category_id': '1', 'added': '1700000000'},
        {'stream_id': 3, 'name': 'Middle', 'category_id': '1', 'added': 1650000000},
    ],
    'get_series_categories': [],
    'get_series': [{'series_id': 5, 'name': 'A', 'last_modified': '10'},
                   {'series_id': 6, 'name': 'B', 'last_modified': '20'}],
    'get_live_categories': [],
    'get_live_streams': [
        {'stream_id': 9, 'name': 'Archived', 'tv_archive': 1, 'tv_archive_duration': '3'},
        {'stream_id': 10, 'name': 'Plain', 'tv_archive': 0}],
})
movies = fx.all_movies()
check('films newest first', [m.name for m in movies] == ['Tom & Jerry', 'Middle', 'Old'],
      str([m.name for m in movies]))
check('html entities unescaped in names', movies[0].name == 'Tom & Jerry')
check('and in category names', movies[0].group == 'Drama & Crime', movies[0].group)
check('added time kept', movies[0].added == 1700000000)
check('series newest first', [s.name for s in fx.all_series()] == ['B', 'A'])
live = fx.all_live()
check('archive days read from the stream', [c.archive for c in live] == [3, 0])
check('the latest-added label is the reference\'s', xm.LATEST == 'LATEST ADDED')
check('unlimited account has no expiry', xm.format_expiry(None) == '' and
      xm.format_expiry('') == '')
check('expiry formatted as a date', len(xm.format_expiry('1789384338')) == 10)

try:
    from urllib.error import HTTPError as _HTTPError
except ImportError:
    from urllib2 import HTTPError as _HTTPError
real_urlopen = xm.urlopen


def refusing(code):
    def _open(req, timeout=None):
        raise _HTTPError('http://srv.tv/player_api.php', code, 'x', {}, None)
    return _open


for code, words in ((401, 'check your credentials'), (403, 'account expired'),
                    (404, 'URL might be incorrect'), (503, 'server is down')):
    xm.urlopen = refusing(code)
    try:
        xm.Xtream('http://srv.tv', 'u', 'p').login()
        got = ''
    except xm.XtreamError as exc:
        got = str(exc)
    check('HTTP %d explained' % code, words in got, got)
xm.urlopen = refusing(500)
try:
    xm.Xtream('http://srv.tv', 'u', 'p').login()
    got = ''
except xm.XtreamError as exc:
    got = str(exc)
check('other HTTP errors still named', got == 'HTTP Error 500', got)
xm.urlopen = real_urlopen

print('')
print('EXTINF name splitting')
UA_LINE = ('#EXTINF:-1 tvg-id="" tvg-logo="" http-user-agent="Mozilla/5.0 '
           '(Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, '
           'like Gecko) Chrome/149.0.0.0 Safari/537.36" '
           'group-title="General",1+1 International')
check('a user agent full of commas does not become the name',
      m3u.extinf_name(UA_LINE) == '1+1 International',
      m3u.extinf_name(UA_LINE))
check('a plain line still works',
      m3u.extinf_name('#EXTINF:-1 group-title="News",BBC One HD') == 'BBC One HD')
check('a name containing a comma survives',
      m3u.extinf_name('#EXTINF:-1 group-title="N",Channel, with a comma')
      == 'Channel, with a comma')
check('no attributes at all', m3u.extinf_name('#EXTINF:-1,Plain') == 'Plain')
check('no comma gives nothing', m3u.extinf_name('#EXTINF:-1') == '')

parsed = m3u.parse('#EXTM3U' + chr(10) + UA_LINE + chr(10) + 'http://x/1.ts')
check('the parsed entry has the real name',
      parsed and parsed[0].name == '1+1 International', parsed[0].name)
check('the group is still read', parsed[0].group == 'General')

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
