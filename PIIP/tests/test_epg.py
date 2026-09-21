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
"""Tests for the programme guide and the EPGImport export."""
import base64
import calendar
import gzip
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import epg
from providers.models import MediaItem, LIVE
from utils import epgexport

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


UTC_1830 = calendar.timegm((2026, 9, 8, 18, 30, 0, 0, 0, 0))

# --------------------------------------------------------------- time parsing
print('time parsing')
check('xmltv UTC', epg.parse_xmltv_time('20260908183000 +0000') == UTC_1830,
      str(epg.parse_xmltv_time('20260908183000 +0000')))
check('xmltv positive offset shifts back',
      epg.parse_xmltv_time('20260908203000 +0200') == UTC_1830)
check('xmltv negative offset shifts forward',
      epg.parse_xmltv_time('20260908153000 -0300') == UTC_1830)
check('xmltv without offset is treated as UTC',
      epg.parse_xmltv_time('20260908183000') == UTC_1830)
check('xmltv junk is zero', epg.parse_xmltv_time('not a time') == 0)
check('xmltv empty is zero', epg.parse_xmltv_time('') == 0)
check('sql time', epg.parse_sql_time('2026-09-08 18:30:00') == UTC_1830)
check('sql time with T', epg.parse_sql_time('2026-09-08T18:30:00') == UTC_1830)
check('sql junk is zero', epg.parse_sql_time('nope') == 0)

# ---------------------------------------------------------------- programme
print('\nProgramme')
p = epg.Programme('c1', UTC_1830, UTC_1830 + 1800, 'News', 'Headlines')
check('duration computed', p.duration == 1800)
check('running inside the window', p.running_at(UTC_1830 + 10) is True)
check('not running before', p.running_at(UTC_1830 - 1) is False)
check('not running at the stop time', p.running_at(UTC_1830 + 1800) is False)
check('progress at half way', p.progress_at(UTC_1830 + 900) == 50)
check('progress clamped below', p.progress_at(UTC_1830 - 500) == 0)
check('progress clamped above', p.progress_at(UTC_1830 + 9000) == 100)
zero = epg.Programme('c', 0, 0, 'x')
check('zero-length programme has no progress', zero.progress_at(1) == 0)
check('zero-length programme has no span', zero.span() == '')

# -------------------------------------------------------------------- xmltv
print('\nXMLTV')
XML = (u'<?xml version="1.0"?>\n<tv>\n'
       u'<channel id="bbc1"><display-name>BBC One</display-name></channel>\n'
       u'<channel id="itv"><display-name>ITV</display-name></channel>\n'
       u'<programme start="20260908190000 +0000" stop="20260908200000 +0000" '
       u'channel="bbc1"><title>Late</title><desc>D2</desc></programme>\n'
       u'<programme start="20260908183000 +0000" stop="20260908190000 +0000" '
       u'channel="bbc1"><title>News</title><desc>D1</desc></programme>\n'
       u'<programme start="20260908183000 +0000" stop="20260908190000 +0000" '
       u'channel="itv"><title>Other</title></programme>\n'
       u'</tv>\n').encode('utf-8')

data, names = epg.parse_xmltv(XML)
check('both channels parsed', sorted(data) == ['bbc1', 'itv'], str(sorted(data)))
check('display names captured', names['bbc1'] == 'BBC One')
check('programmes sorted by start',
      [x.title for x in data['bbc1']] == ['News', 'Late'],
      str([x.title for x in data['bbc1']]))
check('description captured', data['bbc1'][0].desc == 'D1')
check('times decoded', data['bbc1'][0].start == UTC_1830)

buf = io.BytesIO()
# The gzip trailer is only written on close, and Python 2 will not close
# the object for us in time.
gz_writer = gzip.GzipFile(fileobj=buf, mode='wb')
gz_writer.write(XML)
gz_writer.close()
gz = buf.getvalue()
gzdata, _ = epg.parse_xmltv(gz)
check('gzipped xmltv accepted', sorted(gzdata) == ['bbc1', 'itv'])

filtered, _ = epg.parse_xmltv(XML, wanted={'bbc1'})
check('channel filter applied', list(filtered) == ['bbc1'], str(list(filtered)))

check('url-tvg extracted',
      epg.xmltv_url(u'#EXTM3U url-tvg="http://x/epg.xml.gz"\n#EXTINF...')
      == 'http://x/epg.xml.gz')
check('x-tvg-url extracted',
      epg.xmltv_url(u'#EXTM3U x-tvg-url="http://y/e.xml"') == 'http://y/e.xml')
check('first of several urls used',
      epg.xmltv_url(u'#EXTM3U url-tvg="http://a/1.xml,http://b/2.xml"')
      == 'http://a/1.xml')
check('missing attribute gives empty', epg.xmltv_url(u'#EXTM3U\n') == '')

# ------------------------------------------------------------ provider feeds
print('\nXtream feed')
xt = {'epg_listings': [
    {'title': base64.b64encode(b'Evening News').decode(),
     'description': base64.b64encode(b'Today').decode(),
     'start_timestamp': str(UTC_1830), 'stop_timestamp': str(UTC_1830 + 1800),
     'channel_id': '55'},
    {'title': 'Plain Title', 'description': '',
     'start': '2026-09-08 19:00:00', 'end': '2026-09-08 20:00:00'},
]}
progs = epg.from_xtream(xt, '55')
check('two programmes parsed', len(progs) == 2)
check('base64 title decoded', progs[0].title == 'Evening News', progs[0].title)
check('base64 description decoded', progs[0].desc == 'Today')
check('timestamps used', progs[0].start == UTC_1830)
check('plain title left alone', progs[1].title == 'Plain Title')
check('sql fallback times parsed', progs[1].start == UTC_1830 + 1800)
check('empty payload is safe', epg.from_xtream({}, '1') == [])

print('\nStalker feed')
sk = {'js': [
    {'ch_id': '7', 'name': 'Film', 'descr': 'Nice',
     'start_timestamp': UTC_1830, 'stop_timestamp': UTC_1830 + 3600},
    {'ch_id': '7', 'name': 'After', 'time': '2026-09-08 19:30:00',
     'time_to': '2026-09-08 20:00:00'},
]}
sp = epg.from_stalker(sk, '7')
check('stalker programmes parsed', len(sp) == 2)
check('stalker title', sp[0].title == 'Film')
check('stalker description', sp[0].desc == 'Nice')
check('stalker string times parsed', sp[1].start == UTC_1830 + 3600)
check('stalker empty payload is safe', epg.from_stalker({}, '1') == [])

# -------------------------------------------------------------------- index
print('\nEPGIndex')
idx = epg.EPGIndex()
idx.put('bbc1', data['bbc1'])
check('length counts programmes', len(idx) == 2)
check('channels listed', idx.channels() == ['bbc1'])

now, nxt = idx.now_next('bbc1', UTC_1830 + 60)
check('now found', now is not None and now.title == 'News')
check('next found', nxt is not None and nxt.title == 'Late', str(nxt))

now, nxt = idx.now_next('bbc1', UTC_1830 - 3600)
check('before the first programme there is no now', now is None)
check('before the first programme next is the first',
      nxt is not None and nxt.title == 'News')

now, nxt = idx.now_next('bbc1', UTC_1830 + 99999)
check('after everything both are empty', now is None and nxt is None)
check('unknown channel is safe', idx.now_next('nope') == (None, None))

check('upcoming filters the past',
      [p.title for p in idx.upcoming('bbc1', UTC_1830 + 2000)] == ['Late'])
check('upcoming honours the limit',
      len(idx.upcoming('bbc1', 0, limit=1)) == 1)

tmp = tempfile.mkdtemp(prefix='farsiepg')
cache = os.path.join(tmp, 'epg.json')
check('index saves', idx.save(cache) is True)
back = epg.EPGIndex.load(cache)
check('index loads back', back is not None and len(back) == 2)
check('titles survive the round trip',
      [p.title for p in back.get('bbc1')] == ['News', 'Late'])
check('stale cache is rejected', epg.EPGIndex.load(cache, ttl=-1) is None)
check('missing cache is None',
      epg.EPGIndex.load(os.path.join(tmp, 'no.json')) is None)
open(os.path.join(tmp, 'bad.json'), 'w').write('{oops')
check('corrupt cache is None',
      epg.EPGIndex.load(os.path.join(tmp, 'bad.json')) is None)

# --------------------------------------------------------------- epgexport
print('\nEPGImport export')
items = [
    MediaItem('BBC One', 'http://s:8080/live/1.ts', kind=LIVE, tvg_id='bbc1'),
    MediaItem('No Guide', 'http://s:8080/live/2.ts', kind=LIVE, tvg_id=''),
]
body, written = epgexport.build_channels(
    [(i.tvg_id, i.url, i.name) for i in items])
check('only channels with an xmltv id are written', written == 1, str(written))
check('channel element present', '<channel id="bbc1">' in body)
check('service reference embedded', '4097:0:1:0:0:0:0:0:0:0:' in body)
check('url colons escaped in the reference', 's%3a8080' in body)
check('name kept as a comment', '<!-- BBC One -->' in body)
check('xml declaration first', body.startswith('<?xml'))

esc, _ = epgexport.build_channels([('a&b<c', 'http://x/1', 'N&me')])
check('xml special characters escaped',
      'a&amp;b&lt;c' in esc and 'N&amp;me' in esc)

src = epgexport.build_sources('http://x/epg.xml.gz')
check('sources references the channels file',
      'channels="%s"' % epgexport.CHANNELS_FILE in src)
check('url wrapped in CDATA', '<![CDATA[http://x/epg.xml.gz]]>' in src)

epgdir = os.path.join(tmp, 'epgimport')
check('missing directory reported',
      epgexport.export(items, 8903, directory=epgdir)['ok'] is False)
os.makedirs(epgdir)
check('directory detected', epgexport.available(epgdir) is True)

res = epgexport.export(items, 8903, xmltv_url='http://x/e.xml',
                       directory=epgdir, keys=['k1', 'k2'])
check('export succeeded', res['ok'] is True)
check('one channel mapped, one skipped',
      res['mapped'] == 1 and res['skipped'] == 1)
check('channels file written', os.path.exists(res['channels']))
check('sources file written', os.path.exists(res['sources']))
written_body = open(res['channels']).read()
check('reference points at the resolver key',
      '127.0.0.1%3a8903/play/k1' in written_body, written_body[:200])

res2 = epgexport.export(items, 8903, directory=epgdir)
check('no sources file without an xmltv url', res2['sources'] is None)

check('remove deletes both files', epgexport.remove(epgdir) >= 1)
check('files are gone', not os.path.exists(
    os.path.join(epgdir, epgexport.CHANNELS_FILE)))
check('removing twice is safe', epgexport.remove(epgdir) == 0)

shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
