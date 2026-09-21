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
"""Everything that can reach a widget must be the native str type.

This is the class of bug that crashed a receiver: on Python 2 json.loads,
file decoding and socket payloads all produce unicode, and Enigma2's SWIG
widgets accept only native str. Coercion happens at the model boundary, so
these tests pin that behaviour down by feeding non-str values in.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

from providers.models import MediaItem, human_duration
from providers.epg import Programme, from_xtream, from_stalker
from providers.subtitles import Candidate
from utils import apikey as ak
from utils import srt as srtmod
from utils.compat import native

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


def is_native(value):
    return isinstance(value, str)


print('MediaItem')
item = MediaItem(name=b'Channel', url=b'http://x/1.ts', group=b'News',
                 logo=b'l.png', kind=b'live', item_id=b'7', plot=b'p',
                 tvg_id=b'c1', tvg_name=b'Chan', ext=b'ts',
                 rating=b'8', year=b'2020', series_id=b'3')
for field in ('name', 'url', 'group', 'logo', 'kind', 'item_id', 'plot',
              'tvg_id', 'tvg_name', 'ext', 'rating', 'year', 'series_id'):
    value = getattr(item, field)
    check('MediaItem.%s is native str' % field, is_native(value),
          type(value).__name__)
check('MediaItem.label() is native str', is_native(item.label()))
check('MediaItem.resume_key() is native str', is_native(item.resume_key()))

nones = MediaItem(name=None, url=None)
check('None fields become empty strings',
      nones.name == '' and nones.url == '')

numeric = MediaItem(name=123, url=456, item_id=789)
check('numeric fields are stringified',
      numeric.name == '123' and numeric.item_id == '789')

ep = MediaItem(name=b'Pilot', kind=b'episode', season=2, episode=7)
check('episode label is native str', is_native(ep.label()))
check('season and episode stay integers',
      isinstance(ep.season, int) and isinstance(ep.episode, int))

check('human_duration returns native str', is_native(human_duration(3600)))
check('human_duration of junk returns native str', is_native(human_duration('x')))

print('\nProgramme')
prog = Programme(b'c1', 0, 1800, b'Title', b'Desc')
for field in ('channel', 'title', 'desc'):
    check('Programme.%s is native str' % field, is_native(getattr(prog, field)))
check('Programme.clock() is native str', is_native(prog.clock()))
check('Programme.span() is native str', is_native(prog.span()))

empty = Programme(None, 0, 0, None, None)
check('Programme tolerates None', empty.title == '' and empty.desc == '')

print('\nprovider feeds produce native strings')
xt = from_xtream({'epg_listings': [
    {'title': 'RXZlbmluZyBOZXdz', 'description': 'VG9kYXk=',
     'start_timestamp': '100', 'stop_timestamp': '200', 'channel_id': '5'}]},
    '5')
check('xtream programmes decode to native str',
      xt and is_native(xt[0].title) and is_native(xt[0].desc),
      xt[0].title if xt else '')

sk = from_stalker({'js': [{'ch_id': '7', 'name': 'Film', 'descr': 'Nice',
                           'start_timestamp': 1, 'stop_timestamp': 2}]}, '7')
check('stalker programmes are native str',
      sk and is_native(sk[0].title) and is_native(sk[0].desc))

print('\nsubtitles')
cue = srtmod.Cue(0, 1000, b'Subtitle line')
check('Cue.text is native str', is_native(cue.text))

FA = u'فارسی'
parsed = srtmod.parse(u'1\n00:00:01,000 --> 00:00:02,000\n%s\n' % FA)
check('parsed cue is native str', parsed and is_native(parsed[0].text))
check('persian text survives parsing',
      parsed and native(FA) == parsed[0].text, parsed[0].text if parsed else '')

parsed_bytes = srtmod.parse((u'1\n00:00:01,000 --> 00:00:02,000\n%s\n' % FA)
                            .encode('utf-8'))
check('utf-8 bytes parse to native str',
      parsed_bytes and is_native(parsed_bytes[0].text))

subs = srtmod.Subtitles(parsed)
check('Subtitles.text_at is native str', is_native(subs.text_at(1500)))
check('empty lookup is native str', is_native(subs.text_at(999999)))

cand = Candidate(b'SubDL', b'file.srt', b'fa', 3, b'/x.zip')
for field in ('source', 'name', 'language', 'release'):
    check('Candidate.%s is native str' % field, is_native(getattr(cand, field)))
check('Candidate.label() is native str', is_native(cand.label()))

print('\napi key')
check('describe() is native str', is_native(ak.describe('')))
check('mask() is native str', is_native(ak.mask('AIzaEXAMPLEKEY1234')))
check('mask() of empty is native str', is_native(ak.mask('')))
check('find() returns native str', is_native(ak.find('')[0]))

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
