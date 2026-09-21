# -*- coding: utf-8 -*-
"""Focused checks for the reconstructed Hybrid parity features."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.models import MediaItem, LIVE, SERIES, EPISODE
from providers import iptvorg
from providers import stalker as st
from providers.xtream import Xtream
from utils import content, downloads, tmdb
from utils import sqldb

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


check('adult title detected', content.is_adult(MediaItem('XXX Cinema')))
check('adult group detected', content.is_adult(MediaItem('Movie', group='Adult 18+')))
check('ordinary title allowed', not content.is_adult(MediaItem('BBC News')))
check('adult hidden', len(content.allowed([MediaItem('BBC'), MediaItem('Porn HD')])) == 1)
check('adult option restores all', len(content.allowed([MediaItem('BBC'), MediaItem('Porn HD')], True)) == 2)

check('IPTV-org country URL', iptvorg.country_url('IR').endswith('/countries/ir.m3u'))
check('IPTV-org global URL', iptvorg.all_url().endswith('/index.m3u'))
check('TMDB strips quality', tmdb.clean_title('US| Example Movie 2024 4K UHD') == 'Example Movie')
check('TMDB image expands', tmdb.image('/abc.jpg').endswith('/w500/abc.jpg'))
art_item = MediaItem('Film', backdrop='http://img/backdrop.jpg')
check('backdrop retained on media item', art_item.backdrop.endswith('backdrop.jpg'))

x = Xtream('http://host', 'user', 'pass')
cu = x.catchup_url('99', 0, 125)
check('Xtream catchup path', '/timeshift/user/pass/3/' in cu, cu)
check('Xtream catchup stream id', cu.endswith('/99.ts'), cu)

rows = st.Stalker._episode_rows({'seasons': [
    {'season': 2, 'episodes': [{'id': 7, 'name': 'Seven', 'cmd': 'ffmpeg http://x/7'}]}
]})
check('nested Stalker episode flattened', len(rows) == 1)
check('nested season retained', rows[0].get('_season') == 2, str(rows))
check('nested cmd retained', rows[0].get('_cmd', '').endswith('/7'), str(rows))


class Portal(st.Stalker):
    def _call(self, **params):
        if params.get('action') == 'get_categories':
            return {'js': [{'id': 4, 'title': 'Drama'}]}
        if params.get('type') == 'series' and params.get('category') == '*':
            return {'js': {'data': [{'id': 10, 'name': 'Show', 'category_id': 4}]}}
        return {'js': {'data': [{'id': 11, 'name': 'Pilot', 'season': 1,
                                 'episode_num': 1, 'cmd': 'ffmpeg http://x/e1'}]}}


p = Portal('http://portal/c/', '00:1A:79:00:00:01')
series = p.all_series()
check('Stalker series parsed', len(series) == 1 and series[0].kind == SERIES)
check('Stalker series category named', series[0].group == 'Drama', series[0].group)
episodes = p.series_episodes('10')
check('Stalker episode parsed', len(episodes) == 1 and episodes[0].kind == EPISODE)
check('Stalker episode numbering', episodes[0].season == 1 and episodes[0].episode == 1)

tmp = tempfile.mkdtemp(prefix='piip-download-test-')
old_store = downloads.STORE
try:
    downloads.STORE = os.path.join(tmp, 'queue.json')
    item = downloads.enqueue('http://example.test/video.mp4', 'A: Movie?', tmp)
    check('download queued', item['status'] == 'queued')
    base = os.path.basename(item['path'])
    check('download filename sanitised', ':' not in base and '?' not in base, base)
    check('download queue persisted', len(downloads.load()) == 1)
    downloads.remove(item['id'])
    check('download queue remove', downloads.load() == [])
finally:
    downloads.STORE = old_store
    shutil.rmtree(tmp)

old_db_root = sqldb.ROOT
db_tmp = tempfile.mkdtemp(prefix='piip-db-test-')
try:
    sqldb.ROOT = db_tmp
    db = sqldb.connect('server|user', 'movies')
    sqldb.sync_categories(db, [('Drama', 'Drama')])
    sqldb.sync_streams(db, [MediaItem('Cached film', kind='movie',
                                      item_id='77', group='Drama',
                                      backdrop='http://img/bg.jpg')])
    cached = sqldb.streams(db, 'Drama')
    check('catalogue database stores streams', len(cached) == 1)
    check('catalogue database retains backdrop',
          cached[0].get('backdrop', '').endswith('bg.jpg'))
    db.close()
finally:
    sqldb.ROOT = old_db_root
    shutil.rmtree(db_tmp)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
