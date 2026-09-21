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
"""M3U behaviours matched to the reference: panel API loading, the
receiver's own guide, and the cached IPTV-org catalogue."""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import m3u, iptvorg
from providers import xtream as xtream_mod
from providers.models import MediaItem, LIVE, MOVIE
from utils import e2epg

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


print('Xtream get.php links')
creds = m3u.xtream_credentials(
    'http://panel.tv:8080/get.php?username=u1&password=p%402&type=m3u_plus&output=ts')
check('credentials read from the link',
      creds == ('http://panel.tv:8080', 'u1', 'p@2', 'ts'), str(creds))
check('hls output becomes m3u8',
      m3u.xtream_credentials('http://h/get.php?username=a&password=b&output=hls')[3] == 'm3u8')
check('a sub-path is kept in the host',
      m3u.xtream_credentials('https://h/panel/get.php?username=a&password=b')[0]
      == 'https://h/panel')
check('ordinary playlist is not a panel link',
      m3u.xtream_credentials('http://h/list.m3u') is None)
check('missing password is not a panel link',
      m3u.xtream_credentials('http://h/get.php?username=a') is None)


class FakeXtream(object):
    made = []

    def __init__(self, host, user, password, timeout=25, user_agent=''):
        self.host, self.user, self.password = host, user, password
        FakeXtream.made.append(self)

    def live_categories(self):
        return [('1', 'News'), ('2', 'Sport')]

    def live_streams(self):
        return [MediaItem('CNN', url='x', group='1', kind=LIVE, item_id='10'),
                MediaItem('ESPN', url='x', group='9', kind=LIVE, item_id='11')]

    def stream_url(self, sid, ext='ts'):
        return '%s/live/%s/%s/%s.%s' % (self.host, self.user, self.password,
                                        sid, ext)


real_xtream = xtream_mod.Xtream
xtream_mod.Xtream = FakeXtream
try:
    items = m3u.fetch_xtream_live(
        'http://panel.tv/get.php?username=u&password=p&output=m3u8')
finally:
    xtream_mod.Xtream = real_xtream
check('channels come from the API', [i.name for i in items] == ['CNN', 'ESPN'])
check('category ids become names', items[0].group == 'News')
check('unknown category keeps its id', items[1].group == '9')
check('stream URL uses the requested output',
      items[0].url == 'http://panel.tv/live/u/p/10.m3u8', items[0].url)

PLAYLIST = b'#EXTM3U\n#EXTINF:-1 group-title="Films",Movie\nhttp://p/movie/u/p/1.mp4\n' \
           b'#EXTINF:-1,Live One\nhttp://p/u/p/2\n'
calls = []
real_live, real_download = m3u.fetch_xtream_live, m3u._download


def fake_download(url, timeout, agent):
    calls.append(url)
    return PLAYLIST


m3u._download = fake_download
try:
    m3u.fetch_xtream_live = lambda url, **kw: [MediaItem('API', url='a', kind=LIVE)]
    got = m3u.fetch('http://p/get.php?username=u&password=p', kinds=(LIVE,))
    check('live-only request of a panel link uses the API',
          [i.name for i in got] == ['API'] and not calls)
    got = m3u.fetch('http://p/get.php?username=u&password=p')
    check('a request for everything still reads the playlist',
          len(got) == 2 and len(calls) == 1)
    got = m3u.fetch('http://p/list.m3u', kinds=(LIVE,))
    check('ordinary playlists are downloaded as before', len(got) == 2)

    def refused(url, **kw):
        raise IOError('api down')
    m3u.fetch_xtream_live = refused
    got = m3u.fetch('http://p/get.php?username=u&password=p', kinds=(LIVE,))
    check('API failure falls back to the playlist', len(got) == 2)
    m3u.fetch_xtream_live = lambda url, **kw: []
    got = m3u.fetch('http://p/get.php?username=u&password=p', kinds=(LIVE, MOVIE))
    check('asking for films too skips the live-only API', len(got) == 2)
finally:
    m3u.fetch_xtream_live, m3u._download = real_live, real_download

print('\nreceiver guide')
check('service reference tvg-id recognised',
      e2epg.ref_from_tvg_id('1:0:19:2B66:3F3:1:C00000:0:0:0:')
      == '1:0:19:2B66:3F3:1:C00000:0:0:0:')
check('short reference padded to ten fields',
      e2epg.ref_from_tvg_id('1:0:1:445D:453:1:C00000') ==
      '1:0:1:445D:453:1:C00000:0:0:0:')
check('IPTV reference type normalised to DVB',
      e2epg.ref_from_tvg_id('4097:0:1:445D:453:1:C00000:0:0:0:')
      .startswith('1:0:1:445D'))
check('an XMLTV id is not a reference', e2epg.ref_from_tvg_id('bbc1.uk') == '')
check('persian names survive, bytes or text',
      e2epg.normalise_name(u'شبکه سه HD') ==
      e2epg.normalise_name(u'شبکه سه'.encode('utf-8')) != u'')
check('names normalised',
      e2epg.normalise_name('UK: BBC One HD') == e2epg.normalise_name('BBC ONE'))

e2epg.set_names({'BBC One': '1:0:19:1:1:1:1:0:0:0:',
                 'Sky Sport Premier League': '1:0:19:2:2:2:2:0:0:0:'})
check('exact name match', e2epg.match_ref(MediaItem('BBC One FHD')) ==
      '1:0:19:1:1:1:1:0:0:0:')
check('contained name match',
      e2epg.match_ref(MediaItem('Sky Sport Premier League 1080')) ==
      '1:0:19:2:2:2:2:0:0:0:')
check('tvg-id reference wins over the name',
      e2epg.match_ref(MediaItem('BBC One', tvg_id='1:0:1:9:9:9:9:0:0:0:'))
      .startswith('1:0:1:9'))
check('unknown channel has no match', e2epg.match_ref(MediaItem('Zzqx')) == '')
e2epg.set_names({'SHOW': '1:0:1:5:5:5:5:0:0:0:',
                 'Sky News': '1:0:1:6:6:6:6:0:0:0:'})
check('a short service name inside a longer channel name is not a match',
      e2epg.match_ref(MediaItem('30A The Beach Show (720p)')) == '')
check('playlist annotations ignored when matching',
      e2epg.match_ref(MediaItem('Sky News (1080p) [Not 24/7]')) ==
      '1:0:1:6:6:6:6:0:0:0:')
check('a close variant still matches',
      e2epg.match_ref(MediaItem('Sky News Int')) == '1:0:1:6:6:6:6:0:0:0:')
e2epg.set_names({'BBC One': '1:0:19:1:1:1:1:0:0:0:',
                 'Sky Sport Premier League': '1:0:19:2:2:2:2:0:0:0:'})


class FakeCache(object):
    def __init__(self):
        self.queries = []

    def lookupEvent(self, query):
        self.queries.append(query)
        now = int(time.time())
        return [(now - 60, 1800, 'News', 'short', 'long text'),
                (now + 1740, 3600, 'Weather', '', ''),
                (None, None, None, None, None)]


cache = FakeCache()
progs = e2epg.programmes(MediaItem('BBC One'), cache=cache)
check('events turned into programmes', [p.title for p in progs] == ['News', 'Weather'])
check('extended description preferred', progs[0].desc == 'long text')
check('stop is begin plus duration', progs[0].stop - progs[0].start == 1800)
check('queried with the matched reference',
      cache.queries[0][1][0] == '1:0:19:1:1:1:1:0:0:0:')
check('no match asks the cache nothing',
      e2epg.programmes(MediaItem('Zzqx'), cache=FakeCache()) == [])


class BrokenCache(object):
    def lookupEvent(self, query):
        raise RuntimeError('boom')


check('a failing cache yields nothing',
      e2epg.programmes(MediaItem('BBC One'), cache=BrokenCache()) == [])

print('\nIPTV-org catalogue cache')
tmp = tempfile.mkdtemp()
try:
    fetched = []

    def fetch_ok(path, timeout):
        fetched.append(path)
        return json.dumps([{'code': 'IR', 'name': 'Iran'}]).encode('utf-8')

    data = iptvorg._json('countries.json', cache_dir=tmp, fetch=fetch_ok)
    check('first read downloads', data[0]['code'] == 'IR' and len(fetched) == 1)
    data = iptvorg._json('countries.json', cache_dir=tmp, fetch=fetch_ok)
    check('second read comes from disk', len(fetched) == 1)

    old = time.time() - iptvorg.CACHE_TTL - 60
    os.utime(os.path.join(tmp, 'countries.json'), (old, old))

    def fetch_down(path, timeout):
        raise IOError('offline')
    data = iptvorg._json('countries.json', cache_dir=tmp, fetch=fetch_down)
    check('stale copy used when offline', data[0]['name'] == 'Iran')
    ok = False
    try:
        iptvorg._json('languages.json', cache_dir=tmp, fetch=fetch_down)
    except IOError:
        ok = True
    check('offline with no copy still reports the error', ok)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
