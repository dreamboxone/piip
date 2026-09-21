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
"""Tests for the /root/m3u.txt playlist list."""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

from utils import playlists as pl
from providers import m3u

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


tmp = tempfile.mkdtemp(prefix='farsipl')


def write(name, text):
    p = os.path.join(tmp, name)
    with open(p, 'wb') as fh:
        fh.write(text.encode('utf-8'))
    return p


print('parsing')
entries = pl.parse(u'''# a comment
http://one.tv/get.php?username=u&password=p&type=m3u_plus

Sports = http://two.tv/playlist.m3u
   http://three.tv/list.m3u8
/media/hdd/local.m3u
# another comment
''')
check('all playlists parsed', len(entries) == 4, str(len(entries)))
check('comments ignored', all('#' not in e.url for e in entries))
check('blank lines ignored', all(e.url for e in entries))
check('whitespace trimmed', entries[2].url == 'http://three.tv/list.m3u8')
check('explicit name honoured', entries[1].name == 'Sports', entries[1].name)
check('named url kept whole',
      entries[1].url == 'http://two.tv/playlist.m3u', entries[1].url)
check('host used when unnamed', entries[0].name == 'one.tv', entries[0].name)
check('query string is not mistaken for a name',
      entries[0].url.endswith('type=m3u_plus'), entries[0].url)
check('local path accepted', entries[3].url == '/media/hdd/local.m3u')
check('local path gets a filename label',
      entries[3].name == 'local.m3u', entries[3].name)

check('empty text gives nothing', pl.parse(u'') == [])
check('only comments gives nothing', pl.parse(u'# just this\n') == [])
check('bytes input accepted', len(pl.parse(b'http://x.tv/a.m3u')) == 1)

dupes = pl.parse(u'http://x.tv/a.m3u\nhttp://x.tv/a.m3u\n')
check('duplicates dropped', len(dupes) == 1)

creds = pl.parse(u'http://user:pass@host.tv:8080/get.php')
check('credentials stripped from the label',
      creds[0].name == 'host.tv', creds[0].name)

print('\nnative strings')
check('name is native str', isinstance(entries[0].name, str))
check('url is native str', isinstance(entries[0].url, str))

print('\nfile discovery')
missing = os.path.join(tmp, 'nope.txt')
check('no file means no entries', pl.load([missing]) == [])
check('no file means no path', pl.path([missing]) is None)

listfile = write('m3u.txt', u'http://a.tv/1.m3u\nNamed = http://b.tv/2.m3u\n')
check('file found', pl.path([missing, listfile]) == listfile)
check('file loaded', len(pl.load([missing, listfile])) == 2)
check('first existing file wins',
      pl.path([listfile, write('other.txt', u'http://c.tv/3.m3u')]) == listfile)

print('\nensure()')
target = os.path.join(tmp, 'created.txt')
check('template created', pl.ensure(target) == target)
check('file exists afterwards', os.path.exists(target))
check('creating twice is a no-op', pl.ensure(target) is None)
body = open(target).read()
check('template is all comments so it parses as empty',
      pl.parse(body) == [])
check('template explains the format', 'Name = url' in body, body[:60])
check('unwritable location returns None',
      pl.ensure(os.path.join(tmp, 'no', 'such', 'dir', 'x.txt')) is None)

print('\nadd()')
check('appending works', pl.add('http://new.tv/4.m3u', 'New', target) is True)
check('entry is readable back',
      any(e.url == 'http://new.tv/4.m3u' for e in pl.load([target])))
check('name survives',
      [e.name for e in pl.load([target])] == ['New'])
check('the same url is not added twice',
      pl.add('http://new.tv/4.m3u', 'Again', target) is False)
check('unnamed append works', pl.add('http://five.tv/5.m3u', '', target) is True)
check('both entries present', len(pl.load([target])) == 2)

print('\ndescribe()')
check('describe names the file', listfile in pl.describe([listfile]))
check('describe counts entries', '2 playlist' in pl.describe([listfile]),
      pl.describe([listfile]))
check('describe says when nothing is there',
      'no playlist list' in pl.describe([missing]))

print('\nmerging playlists')
PL_A = (u'#EXTM3U\n#EXTINF:-1 group-title="News",A One\n'
        u'http://a.tv/live/1.ts\n')
PL_B = (u'#EXTM3U\n#EXTINF:-1 group-title="Sport",B One\n'
        u'http://b.tv/live/2.ts\n')
file_a = write('a.m3u', PL_A)
file_b = write('b.m3u', PL_B)

single = write('one.txt', file_a)
items, errors = m3u.load_all('', paths=[single])
check('one playlist loads', len(items) == 1 and not errors)
check('single playlist keeps its own group',
      items[0].group == 'News', items[0].group)

both = write('two.txt', u'Alpha = %s\nBeta = %s\n' % (file_a, file_b))
items, errors = m3u.load_all('', paths=[both])
check('both playlists merged', len(items) == 2, str(len(items)))
check('groups prefixed with the playlist name',
      sorted(i.group for i in items) == ['Alpha / News', 'Beta / Sport'],
      str(sorted(i.group for i in items)))

mixed = write('mixed.txt', u'Good = %s\nBad = /does/not/exist.m3u\n' % file_a)
items, errors = m3u.load_all('', paths=[mixed])
check('a broken playlist does not hide the others', len(items) == 1)
check('the failure is reported', len(errors) == 1 and 'Bad' in errors[0],
      str(errors))

items, errors = m3u.load_all('http://', paths=[single])
check('the placeholder settings url is ignored', len(items) == 1)

items, errors = m3u.load_all(file_a, paths=[os.path.join(tmp, 'none.txt')])
check('settings url alone still works', len(items) == 1 and not errors)

items, errors = m3u.load_all('', paths=[os.path.join(tmp, 'none.txt')])
check('nothing configured gives nothing', items == [] and errors == [])

shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
