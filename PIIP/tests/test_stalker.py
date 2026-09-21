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
"""Tests for the Stalker portal client."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import stalker as st
from providers.models import LIVE, MOVIE, MediaItem

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


print('MAC handling')
check('colon form kept', st.normalise_mac('00:1A:79:00:00:00') == '00:1A:79:00:00:00')
check('lowercase upcased', st.normalise_mac('00:1a:79:aa:bb:cc') == '00:1A:79:AA:BB:CC')
check('dashes accepted', st.normalise_mac('00-1A-79-00-00-01') == '00:1A:79:00:00:01')
check('bare hex accepted', st.normalise_mac('001A79000002') == '00:1A:79:00:00:02')
check('valid mac recognised', st.valid_mac('00:1A:79:00:00:00') is True)
check('short mac rejected', st.valid_mac('00:1A:79') is False)
check('junk rejected', st.valid_mac('hello') is False)
check('empty rejected', st.valid_mac('') is False)

print('\nportal URL normalisation')
check('trailing /c stripped',
      st.portal_root('http://p.tv:8080/c/') == 'http://p.tv:8080')
check('bare /c stripped',
      st.portal_root('http://p.tv:8080/c') == 'http://p.tv:8080')
check('stalker_portal prefix kept, only /c stripped',
      st.portal_root('http://p.tv/stalker_portal/c') == 'http://p.tv/stalker_portal',
      st.portal_root('http://p.tv/stalker_portal/c'))
check('bare host falls back to a stalker_portal endpoint',
      '/stalker_portal/server/load.php' in st.ENDPOINTS)
check('scheme added', st.portal_root('p.tv:8080') == 'http://p.tv:8080')
check('plain root untouched',
      st.portal_root('http://p.tv:8080') == 'http://p.tv:8080')
check('https preserved', st.portal_root('https://p.tv/c/') == 'https://p.tv')

print('\ncmd cleaning')
check('ffmpeg prefix removed',
      st.clean_cmd('ffmpeg http://s/live/1') == 'http://s/live/1')
check('auto prefix removed',
      st.clean_cmd('auto http://s/live/1') == 'http://s/live/1')
check('bare url untouched',
      st.clean_cmd('http://s/live/1') == 'http://s/live/1')
check('https handled',
      st.clean_cmd('ffmpeg https://s/x?a=1&b=2') == 'https://s/x?a=1&b=2')
check('empty is empty', st.clean_cmd('') == '')


class FakePortal(st.Stalker):
    """Drives the client against canned portal replies."""

    def __init__(self, replies, **kw):
        st.Stalker.__init__(self, 'http://p.tv/c/', '00:1A:79:00:00:00', **kw)
        self.replies = replies
        self.calls = []

    def _call(self, **params):
        self.calls.append(params)
        action = params.get('action')
        reply = self.replies.get(action)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise st.StalkerError('no canned reply for %s' % action)
        return reply


print('\nhandshake')
p = FakePortal({'handshake': {'js': {'token': 'TOK123'}},
                'get_profile': {'js': {'id': '1'}}})
check('token stored', p.connect() == 'TOK123' and p.token == 'TOK123')
check('profile fetched', p.profile == {'id': '1'})

p2 = FakePortal({'handshake': {'js': {}}})
try:
    p2.connect()
    ok = False
except st.StalkerError as e:
    ok = 'token' in str(e)
check('missing token raises a clear error', ok)

p3 = FakePortal({'handshake': {'js': {'token': 'T'}},
                 'get_profile': st.StalkerError('nope')})
check('portal still usable when get_profile fails',
      p3.connect() == 'T' and p3.profile is None)

bad = st.Stalker('http://p.tv', 'not-a-mac')
try:
    bad.connect()
    ok = False
except st.StalkerError as e:
    ok = 'MAC' in str(e)
check('invalid MAC refused before any request', ok)

print('\nheaders')
p.token = 'TOK123'
h = p._headers()
check('mac in cookie', 'mac=00%3A1A%3A79%3A00%3A00%3A00' in h['Cookie'], h['Cookie'])
check('bearer token sent', h['Authorization'] == 'Bearer TOK123')
check('MAG user agent', 'MAG200' in h['User-Agent'])
check('X-User-Agent present', h['X-User-Agent'] == st.X_UA)
check('referer points at the portal', h['Referer'] == 'http://p.tv/c/')
p.token = ''
check('no auth header before handshake', 'Authorization' not in p._headers())

print('\nchannels')
p = FakePortal({
    'handshake': {'js': {'token': 'T'}},
    'get_profile': {'js': {}},
    'get_genres': {'js': [{'id': '5', 'title': 'News'},
                          {'id': '6', 'title': 'Sport'}]},
    'get_all_channels': {'js': {'data': [
        {'id': '101', 'name': 'BBC', 'cmd': 'ffmpeg http://x/1',
         'logo': 'l.png', 'tv_genre_id': '5', 'xmltv_id': 'bbc'},
        {'id': '102', 'name': 'Sky', 'cmd': 'http://x/2', 'tv_genre_id': '9'},
    ]}},
})
p.connect()
chans = p.channels()
check('channels parsed', len(chans) == 2)
check('genre name resolved', chans[0].group == 'News', chans[0].group)
check('unknown genre falls back', chans[1].group == 'Ungrouped', chans[1].group)
check('cmd kept for later resolution', chans[0].cmd == 'ffmpeg http://x/1')
check('the token is not shown as the description', chans[0].plot == '')
check('url empty until resolved', chans[0].url == '')
check('kind is live', chans[0].kind == LIVE)
check('epg id captured', chans[0].tvg_id == 'bbc')

p.replies['get_all_channels'] = {'js': []}
check('empty channel list is safe', p.channels() == [])

print('\ncreate_link')
p.replies['create_link'] = {'js': {'cmd': 'ffmpeg http://real/stream?t=1'}}
url = p.create_link('ffmpeg http://x/1')
check('link resolved and cleaned', url == 'http://real/stream?t=1', url)

item = chans[0]
p.resolve(item)
# Always through the portal: the token in a cmd expires long before you
# get round to watching.
check('resolve asks the portal for a fresh link',
      item.url == 'http://real/stream?t=1', item.url)

p.replies['create_link'] = {'js': {'cmd': ''}}
try:
    p.create_link('x')
    ok = False
except st.StalkerError:
    ok = True
check('empty link raises', ok)

try:
    p.create_link('')
    ok = False
except st.StalkerError:
    ok = True
check('missing cmd raises', ok)

print('\nvod')
p.replies['get_categories'] = {'js': [{'id': '1', 'title': 'Action'}]}
p.replies['get_ordered_list'] = {'js': {'total_items': 42, 'data': [
    {'id': '7', 'name': 'Film', 'time': '95', 'year': '2020',
     'cmd': 'ffmpeg http://v/7', 'category_id': '1'},
]}}
cats = p.vod_categories()
check('vod categories parsed', cats == [('1', 'Action')], str(cats))
movies, total = p.vod_list('1')
check('vod list parsed', len(movies) == 1 and movies[0].kind == MOVIE)
check('vod total reported', total == 42)
check('vod duration parsed', movies[0].duration == 95)
check('vod cmd kept', movies[0].cmd == 'ffmpeg http://v/7')
check('vod token not used as the plot', movies[0].plot != 'ffmpeg http://v/7')
check('old items with the token in plot still resolve', st.token_of(MediaItem('o', plot='tok')) == 'tok')


# ---------------------------------------------------------------- the cmd

print('')
print('a cmd is stripped of whatever wraps it')
for prefix in st.CMD_PREFIXES:
    got = st.strip_prefix('%s http://h/p?a=1' % prefix)
    check('%s is stripped' % prefix, got == 'http://h/p?a=1', got)
check('an unwrapped cmd is left alone',
      st.strip_prefix('http://h/p') == 'http://h/p')
check('a token is left alone',
      st.strip_prefix('/media/file_1234') == '/media/file_1234')
check('an empty cmd is empty', st.strip_prefix(None) == '')
check('a prefix without a space is not a prefix',
      st.strip_prefix('ffmpegx http://h/p') == 'ffmpegx http://h/p')

print('')
print('a cmd that is already an address needs no exchange')
LIVE_CMD = ('ffmpeg http://4y-ott.online:80/play/live.php'
            '?mac=00:1A:79:63:5F:84&stream=1402421&extension=ts'
            '&play_token=1t7aXqtePN')
check('the real portal cmd is playable as it stands',
      st.direct_url(LIVE_CMD)
      == LIVE_CMD[len('ffmpeg '):], st.direct_url(LIVE_CMD))
for token in ('ffmpeg http://localhost/ch/1402421_',
              'ffmpeg http://127.0.0.1:8080/play',
              'ffrt http://0.0.0.0/x',
              '/media/movie_88', 'auto /some/path', '', None):
    check('%r is a token, not an address' % (token,),
          st.direct_url(token) == '', st.direct_url(token))

print('')
print('a create_link answer that lost the stream id is refused')
GOOD = ('http://4y-ott.online:80/play/live.php?mac=M&stream=1402421'
        '&extension=ts')
BLANKED = ('http://4y-ott.online:80/play/live.php?mac=M&stream='
           '&extension=ts&play_token=FRESHTOKEN&sn2=')
check('a blanked stream id is worse', st.link_is_worse(BLANKED, GOOD))
check('a different stream id is not worse',
      not st.link_is_worse(
          GOOD.replace('1402421', '999'), GOOD))
check('a wholly different url is not worse',
      not st.link_is_worse('http://cdn.example/live/9.m3u8', GOOD))
check('nothing to compare against is not worse',
      not st.link_is_worse(BLANKED, ''))
check('a blanked file= is caught too',
      st.link_is_worse('http://h/p?file=', 'http://h/p?file=1234'))

print('')
print('resolving a live channel')


class _Portal(st.Stalker):
    """A portal that answers create_link the way 4y-ott.online does."""

    asked = []

    def create_link(self, cmd, series=0):
        _Portal.asked.append(cmd)
        return st.Stalker.create_link(self, cmd, series)

    def _call(self, **params):
        _Portal.asked.append(params.get('cmd'))
        return {'js': {'cmd': BLANKED}}


item = MediaItem(name='x', url='', kind=LIVE, plot=LIVE_CMD)
portal = _Portal('http://4y-ott.online:80/c/', '00:1A:79:63:5F:84')
url = portal.resolve(item)
check('the portal is always asked, for a fresh token',
      _Portal.asked and LIVE_CMD in _Portal.asked, str(_Portal.asked))
check('the blanked stream id is put back', 'stream=1402421' in url, url)
check('and the fresh token is kept',
      'play_token=FRESHTOKEN' in url, url)
check('the item carries it', item.url == url)

print('')
print('repairing a blanked answer')
FRESH = ('http://4y-ott.online:80/play/live.php?mac=M&stream='
         '&extension=ts&play_token=NEWTOKEN&sn2=')
ORIG = ('http://4y-ott.online:80/play/live.php?mac=M&stream=1402421'
        '&extension=ts&play_token=OLDTOKEN')
fixed = st.repair_link(FRESH, ORIG)
check('the channel comes from the cmd', 'stream=1402421' in fixed, fixed)
check('the token comes from the portal', 'play_token=NEWTOKEN' in fixed,
      fixed)
check('the stale token is gone', 'OLDTOKEN' not in fixed, fixed)
check('a good answer is left alone',
      st.repair_link('http://cdn/x.m3u8', ORIG) == 'http://cdn/x.m3u8')

print('')
print('a portal that refuses altogether falls back to the cmd')


class _Dead(_Portal):
    def _call(self, **params):
        raise st.StalkerError('portal is down')


dead_item = MediaItem(name='z', url='', kind=LIVE, plot=LIVE_CMD)
dead = _Dead('http://4y-ott.online:80/c/', '00:1A:79:63:5F:84')
url = dead.resolve(dead_item)
check('the cmd is used as it stands', url == LIVE_CMD[len('ffmpeg '):], url)

dead_token = MediaItem(name='z', url='', kind=LIVE,
                       plot='ffmpeg http://localhost/ch/1_')
ok = False
try:
    dead.resolve(dead_token)
except Exception:
    ok = True
check('with nothing to fall back to it raises', ok)

print('\narchive flag')
check('no archive is 0', st.archive_days({'tv_archive': '0'}) == 0)
check('archive without depth is a day', st.archive_days({'tv_archive': '1'}) == 1)
check('depth in hours rounds up to days',
      st.archive_days({'tv_archive': 1, 'tv_archive_duration': '50'}) == 3)
arch = FakePortal({'get_genres': {'js': []},
                   'get_all_channels': {'js': {'data': [
                       {'id': 1, 'name': 'A', 'cmd': 'x', 'tv_archive': '1',
                        'tv_archive_duration': 72},
                       {'id': 2, 'name': 'B', 'cmd': 'y'}]}}})
chans = arch.channels()
check('archive days carried onto the channel',
      [c.archive for c in chans] == [3, 0])

print('\nchannels page by page')
paged = FakePortal({'get_genres': {'js': [{'id': '5', 'title': 'News'}]},
                    'get_all_channels': st.StalkerError('disabled'),
                    'get_ordered_list': {'js': {
                        'total_items': 2, 'max_page_items': 14,
                        'data': [{'id': 9, 'name': 'N', 'cmd': 'c',
                                  'tv_genre_id': '5'},
                                 {'id': 10, 'name': 'M', 'cmd': 'd'}]}}})
chans = paged.channels()
check('refused get_all_channels falls back to get_ordered_list',
      [c.item_id for c in chans] == ['9', '10'])
check('genre names still applied', chans[0].group == 'News')
check('page request names genre and page',
      any(c.get('action') == 'get_ordered_list' and c.get('genre') == '*'
          and c.get('p') == '1' for c in paged.calls))
dead_all = FakePortal({'get_genres': {'js': []},
                       'get_all_channels': st.StalkerError('down')})
ok = False
try:
    dead_all.channels()
except st.StalkerError as e:
    ok = 'down' in str(e)
check('both failing reports the original error', ok)

print('\nfull guide')
import time as _time
now = int(_time.time())
guide = FakePortal({'get_simple_data_table': {'js': {
    'total_items': 2, 'max_page_items': 10,
    'data': [{'name': 'Past', 'start_timestamp': now - 7200,
              'stop_timestamp': now - 3600},
             {'name': 'Now', 'start_timestamp': now - 60,
              'stop_timestamp': now + 600}]}}})
progs = guide.full_epg('7', days=2)
check('past programmes included', [p.title for p in progs] == ['Past', 'Now'])
check('one request per day from days back to tomorrow',
      len([c for c in guide.calls
           if c.get('action') == 'get_simple_data_table']) == 4)
check('channel id sent', guide.calls[0].get('ch_id') == '7')
short = FakePortal({'get_simple_data_table': st.StalkerError('no'),
                    'get_short_epg': {'js': [{'name': 'Soon',
                                              'start_timestamp': now + 60,
                                              'stop_timestamp': now + 120}]}})
check('falls back to the short guide',
      [p.title for p in short.full_epg('7')] == ['Soon'])

refused = FakePortal({'get_simple_data_table': st.StalkerError('empty response'),
                      'get_epg_info': {'js': {'data': {
                          '7': [{'name': 'Info', 'start_timestamp': now + 30,
                                 'stop_timestamp': now + 90}],
                          '8': [{'name': 'Other', 'start_timestamp': now,
                                 'stop_timestamp': now + 60}]}}},
                      'get_short_epg': {'js': [{'name': 'Soon',
                                                'start_timestamp': now + 60,
                                                'stop_timestamp': now + 120},
                                               {'name': 'Info',
                                                'start_timestamp': now + 30,
                                                'stop_timestamp': now + 90}]}})
progs = refused.full_epg('7', days=3)
check('a portal without the day table uses get_epg_info and the short guide',
      [p.title for p in progs] == ['Info', 'Soon'], str([p.title for p in progs]))
check('an unsupported day table is asked once, not once per day',
      len([c for c in refused.calls
           if c.get('action') == 'get_simple_data_table']) == 1)
refused.full_epg('8', days=3)
check('and never again on the next channel',
      len([c for c in refused.calls
           if c.get('action') == 'get_simple_data_table']) == 1)
check('the all-channel guide is fetched once and reused',
      len([c for c in refused.calls if c.get('action') == 'get_epg_info']) == 1)
dead_guide = FakePortal({})
ok = False
try:
    dead_guide.full_epg('7')
except st.StalkerError:
    ok = True
check('with no guide source at all the error is reported', ok)

print('\nexpiry')
check('unset date is blank', st.format_expiry('0000-00-00 00:00:00') == '')
check('midnight time trimmed', st.format_expiry('2026-12-01 00:00:00') == '2026-12-01')
check('timestamp formatted', len(st.format_expiry(str(now))) == 10)
exp = FakePortal({})
exp.profile = {'expire_billing_date': '2027-01-31 00:00:00'}
check('expiry read from the profile', exp.expiry() == '2027-01-31')
exp2 = FakePortal({'get_main_info': {'js': {'end_date': '2026-10-10'}}})
exp2.profile = {}
check('expiry falls back to account info', exp2.expiry() == '2026-10-10')
exp3 = FakePortal({})
check('no expiry anywhere is blank', exp3.expiry() == '')

print('\nserver-side search')
srch = FakePortal({'get_ordered_list': {'js': {
    'total_items': 1, 'data': [{'id': 3, 'name': 'Matrix', 'cmd': 'm'}]}}})
found = srch.search_vod('matrix')
check('search results returned', [m.name for m in found] == ['Matrix'])
check('query sent to the portal', srch.calls[0].get('search') == 'matrix')
check('blank query asks nothing', srch.search_vod('  ') == [] and len(srch.calls) == 1)
ssrch = FakePortal({'get_categories': {'js': []},
                    'get_ordered_list': {'js': {'data': [
                        {'id': 4, 'name': 'Dark'}]}}})
check('series search', [s.name for s in ssrch.search_series('dark')] == ['Dark']
      and ssrch.calls[-1].get('search') == 'dark')

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
