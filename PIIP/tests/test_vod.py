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
"""Tests for movies, series, the media model and the resume store."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import m3u
from providers.models import (MediaItem, LIVE, MOVIE, EPISODE, SERIES,
                              human_duration, parse_duration)
from providers.xtream import Xtream
from utils import resume as rs
from utils import downloads

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


# ------------------------------------------------------------------- model
print('MediaItem')
live = MediaItem('BBC', 'http://s/live/u/p/1.ts', kind=LIVE, item_id='1')
mov = MediaItem('Dune', 'http://s/movie/u/p/9.mkv', kind=MOVIE, item_id='9',
                year='2021', duration=9300)
ep = MediaItem('Pilot', 'http://s/series/u/p/55.mp4', kind=EPISODE,
               item_id='55', season=2, episode=7, duration=2700)

check('live is not seekable', live.seekable is False)
check('movie is seekable', mov.seekable is True)
check('episode is seekable', ep.seekable is True)
check('live has no resume key', live.resume_key() == '')
check('movie resume key', mov.resume_key() == 'mv:9')
check('episode resume key', ep.resume_key() == 'ep:55')
check('resume keys never collide across kinds',
      mov.resume_key() != ep.resume_key())
check('movie label shows year', mov.label() == 'Dune (2021)', mov.label())
check('episode label shows SxxExx', ep.label() == 'S02E07  Pilot', ep.label())
check('plain label falls through', live.label() == 'BBC')

print('\nduration helpers')
check('seconds passthrough', parse_duration(3600) == 3600)
check('numeric string', parse_duration('125') == 125)
check('HH:MM:SS', parse_duration('01:30:00') == 5400)
check('MM:SS', parse_duration('02:30') == 150)
check('empty is zero', parse_duration('') == 0 and parse_duration(None) == 0)
check('junk is zero', parse_duration('abc') == 0)
check('format hours', human_duration(5400) == '1:30:00', human_duration(5400))
check('format minutes', human_duration(150) == '2:30')
check('zero renders empty', human_duration(0) == '')
check('junk renders empty', human_duration('x') == '')

# ------------------------------------------------------------ xtream urls
print('\nXtream URLs')
x = Xtream('http://srv:8080', 'u', 'p')
check('live url', x.stream_url(1) == 'http://srv:8080/live/u/p/1.ts')
check('movie url', x.movie_url(9, 'mkv') == 'http://srv:8080/movie/u/p/9.mkv')
check('episode url', x.episode_url(55, 'mp4') == 'http://srv:8080/series/u/p/55.mp4')
check('missing extension defaults to mp4', x.movie_url(9, '').endswith('.mp4'))

# ---------------------------------------------------- series_info parsing
print('\nseries episode parsing')
payload = {
    'info': {'name': 'Show', 'cover': 'http://c/show.jpg'},
    'episodes': {
        '2': [
            {'id': '102', 'episode_num': '2', 'title': 'Second',
             'container_extension': 'mkv',
             'info': {'duration_secs': 2700, 'plot': 'p2'}},
            {'id': '101', 'episode_num': '1', 'title': 'First',
             'container_extension': 'mp4',
             'info': {'duration': '00:45:00'}},
        ],
        '1': [
            {'id': '11', 'episode_num': '1', 'title': 'Start',
             'container_extension': 'mp4', 'info': {}},
        ],
    },
}
x._api = lambda **kw: payload
info, seasons = x.series_episodes(7)
check('seasons parsed', sorted(seasons) == [1, 2], str(sorted(seasons)))
check('episodes sorted within a season',
      [e.episode for e in seasons[2]] == [1, 2])
check('episode url built from its own extension',
      seasons[2][1].url.endswith('/102.mkv'), seasons[2][1].url)
check('duration_secs used', seasons[2][1].duration == 2700)
check('HH:MM:SS duration used', seasons[2][0].duration == 2700)
check('season and episode recorded',
      seasons[2][0].season == 2 and seasons[2][0].episode == 1)
check('series id propagated', seasons[1][0].series_id == '7')
check('cover falls back to the series cover',
      seasons[1][0].logo == 'http://c/show.jpg')

x._api = lambda **kw: {'info': {}, 'episodes': [
    {'id': '5', 'episode_num': '1', 'title': 'Only', 'info': {}}]}
info, seasons = x.series_episodes(1)
check('bare episode list is accepted', list(seasons) == [1], str(list(seasons)))

x._api = lambda **kw: {}
info, seasons = x.series_episodes(1)
check('empty response is safe', seasons == {})

# ---------------------------------------------------------- m3u classify
print('\nM3U classification')
PL = u'''#EXTM3U
#EXTINF:-1 group-title="News",BBC News
http://s/live/u/p/1.ts
#EXTINF:-1 group-title="VOD Action",Dune 2021
http://s/movie/u/p/9.mkv
#EXTINF:-1 group-title="Series",Show S02E07 Pilot
http://s/series/u/p/55.mp4
#EXTINF:-1 group-title="Films",Some Film
http://s/other/path/3.mp4
'''
items = m3u.parse(PL)
kinds = [i.kind for i in items]
check('live detected from /live/', kinds[0] == LIVE, kinds[0])
check('movie detected from /movie/', kinds[1] == MOVIE, kinds[1])
check('episode detected from /series/', kinds[2] == EPISODE, kinds[2])
check('movie detected from group name', kinds[3] == MOVIE, kinds[3])
check('SxxExx parsed from the title',
      items[2].season == 2 and items[2].episode == 7,
      'S%sE%s' % (items[2].season, items[2].episode))
check('of_kind filters', len(m3u.of_kind(items, MOVIE)) == 2)
check('classification can be switched off',
      all(i.kind == LIVE for i in m3u.parse(PL, classify_kind=False)))

grouped = m3u.series_from_episodes(items)
check('episodes grouped into a series title', 'Show' in grouped, str(list(grouped)))

# ------------------------------------------------------------ resume store
print('\nresume store')
tmpdir = tempfile.mkdtemp(prefix='farsiresume')
store = os.path.join(tmpdir, 'r.json')

check('unknown item resumes at zero', rs.get(mov, store) == 0)
check('live items are never stored', rs.put(live, 500, 3600, store) is False)
check('positions below the threshold are ignored',
      rs.put(mov, 5, 9300, store) is False)
check('a real position is stored', rs.put(mov, 1800, 9300, store) is True)
check('stored position reads back', rs.get(mov, store) == 1800)
check('progress percent computed', rs.percent(mov, store) == 19,
      str(rs.percent(mov, store)))

check('finishing clears the entry', rs.put(mov, 9280, 9300, store) is True)
check('finished item resumes at zero', rs.get(mov, store) == 0)

rs.put(ep, 600, 2700, store)
rs.put(mov, 1200, 9300, store)
check('two items coexist',
      rs.get(ep, store) == 600 and rs.get(mov, store) == 1200)
check('clearing one leaves the other',
      rs.clear(ep, store) and rs.get(ep, store) == 0
      and rs.get(mov, store) == 1200)

with open(store, 'w') as fh:
    fh.write('{ not json')
check('corrupt store degrades to zero', rs.get(mov, store) == 0)
check('corrupt store can still be written', rs.put(mov, 900, 9300, store) is True)
check('and reads back after repair', rs.get(mov, store) == 900)

missing = os.path.join(tmpdir, 'nope', 'deep.json')
check('unwritable path fails quietly',
      rs.put(mov, 900, 9300, missing) is False)
check('unreadable path reads zero', rs.get(mov, missing) == 0)

download_store = os.path.join(tmpdir, 'downloads.json')
old_download_store = downloads.STORE
downloads.STORE = download_store
downloads.save([
    {'id': '1', 'status': 'complete', 'path': ''},
    {'id': '2', 'status': 'failed', 'path': ''},
    {'id': '3', 'status': 'paused', 'path': ''},
])
check('clear-finished removes complete and failed queue rows',
      downloads.clear_finished() == 2)
check('clear-finished keeps paused downloads',
      [x['id'] for x in downloads.load()] == ['3'])
downloads.STORE = old_download_store

no_dur = MediaItem('X', 'u', kind=MOVIE, item_id='x')
rs.put(no_dur, 300, 0, store)
check('item without duration still stores', rs.get(no_dur, store) == 300)
check('percent is zero without a duration', rs.percent(no_dur, store) == 0)

import shutil
shutil.rmtree(tmpdir, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
