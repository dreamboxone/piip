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
"""Tests for bouquet export and the local resolver."""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers.models import MediaItem, LIVE
from utils import bouquet as bq
from translate import resolver

try:
    from urllib.request import urlopen, Request, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, Request, build_opener, HTTPRedirectHandler, HTTPError

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


tmp = tempfile.mkdtemp(prefix='farsibq')
BQ_TV = os.path.join(tmp, 'bouquets.tv')
MAP = os.path.join(tmp, 'map.json')
open(BQ_TV, 'w').write('#NAME Bouquets (TV)\n')

items = [
    MediaItem('BBC One', 'http://s:8080/live/u/p/1.ts', kind=LIVE, item_id='1'),
    MediaItem('Sky: News', '', kind=LIVE, item_id='2'),
]
items[1].plot = 'ffmpeg http://portal/ch2'

# ------------------------------------------------------------ service refs
print('service references')
ref = bq.service_ref('http://s:8080/live/1.ts', 'BBC One')
check('colons in the url are escaped', '%3a8080' in ref and ':8080' not in ref, ref)
check('reference starts with the service type', ref.startswith('#SERVICE 4097:0:1:'))
check('name is the last field', ref.endswith(':BBC One'), ref[-20:])
check('colons in the name are removed',
      bq.service_ref('http://x/1', 'A: B').endswith(':A  B'))
check('service type is honoured',
      bq.service_ref('http://x/1', 'n', 5002).startswith('#SERVICE 5002:'))

# -------------------------------------------------------------------- map
print('\nchannel map')
data, keys = bq.build_map(items, 'stalker', True)
check('one key per item', len(keys) == 2 and len(data) == 2)
check('keys are stable',
      bq.build_map(items, 'stalker', True)[1] == keys)
check('provider recorded', data[keys[0]]['provider'] == 'stalker')
check('translate flag recorded', data[keys[0]]['translate'] is True)
check('stalker cmd carried over',
      data[keys[1]]['cmd'] == 'ffmpeg http://portal/ch2')
check('direct url carried over',
      data[keys[0]]['url'] == 'http://s:8080/live/u/p/1.ts')

d2, _ = bq.build_map(items, 'xtream', False)
check('cmd only kept for stalker', d2[list(d2)[1]]['cmd'] == '')
check('different providers give different keys',
      set(bq.build_map(items, 'xtream', False)[1]) != set(keys))

merged, _ = bq.build_map(items, 'm3u', False, existing={'old': {'x': 1}})
check('existing entries are preserved', 'old' in merged)

check('map saves', bq.save_map(data, MAP) is True)
check('map loads back', bq.load_map(MAP) == data)
check('missing map loads empty', bq.load_map(os.path.join(tmp, 'no.json')) == {})
open(MAP + '.bad', 'w').write('{ oops')
check('corrupt map loads empty', bq.load_map(MAP + '.bad') == {})

# ----------------------------------------------------------------- export
print('\nexport')
res = bq.export(items, 'PIIP — Stalker', 'stalker', 8903,
                translate=False, enigma_dir=tmp, bouquets_tv=BQ_TV,
                map_file=MAP)
check('bouquet written', res['path'] and os.path.exists(res['path']))
check('count reported', res['count'] == 2)
check('registered in bouquets.tv', res['registered'] is True)

body = open(res['path']).read()
check('bouquet has a name header', body.startswith('#NAME PIIP'))
check('one service line per channel', body.count('#SERVICE 4097:') == 2)
check('descriptions written', body.count('#DESCRIPTION') == 2)
check('entries point at the resolver, not the provider',
      '127.0.0.1%3a8903' in body and 's%3a8080' not in body)

tv = open(BQ_TV).read()
check('bouquets.tv references the file', res['filename'] in tv)
check('bouquets.tv line is well formed',
      'FROM BOUQUET "%s" ORDER BY bouquet' % res['filename'] in tv)

again = bq.export(items, 'T', 'stalker', 8903, enigma_dir=tmp,
                  bouquets_tv=BQ_TV, map_file=MAP)
check('re-export does not duplicate the registration',
      again['registered'] is False and tv.count(res['filename']) == 1)

check('exported bouquets are listed',
      res['filename'] in bq.list_exported(tmp))

res2 = bq.export(items, 'T2', 'xtream', 8903, enigma_dir=tmp,
                 bouquets_tv=BQ_TV, map_file=MAP, slug='xtream')
check('a second provider gets its own file',
      res2['filename'] != res['filename'])
check('both bouquets listed', len(bq.list_exported(tmp)) == 2)
check('map now holds both providers', len(bq.load_map(MAP)) == 4)

check('unregister removes the file',
      bq.unregister(res2['filename'], BQ_TV, tmp) is True
      and not os.path.exists(os.path.join(tmp, res2['filename'])))
check('unregister strips the bouquets.tv line',
      res2['filename'] not in open(BQ_TV).read())
check('unregistering something absent is safe',
      bq.unregister('userbouquet.piip_nope.tv', BQ_TV, tmp) is False)

print('\nfilenames')
check('slug is sanitised',
      bq.bouquet_filename('My Portal!') == 'userbouquet.piip_my_portal_.tv',
      bq.bouquet_filename('My Portal!'))
check('empty slug falls back', bq.bouquet_filename('') == 'userbouquet.piip_live.tv')

# --------------------------------------------------------------- resolver
print('\nresolver')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


opener = build_opener(NoRedirect)


def get(url):
    """-> (status, location header, body)"""
    try:
        r = opener.open(url, timeout=5)
        return r.getcode(), r.headers.get('Location'), r.read()
    except HTTPError as e:
        return e.code, e.headers.get('Location'), e.read()


class FakeStalker(object):
    calls = []

    def connect(self):
        return 'T'

    def create_link(self, cmd, series=0):
        FakeStalker.calls.append(cmd)
        return 'http://real/from-portal?token=abc'


direct_key, stalker_key = None, None
m = {}
d, k = bq.build_map([items[0]], 'm3u', False)
m.update(d)
direct_key = k[0]
d, k = bq.build_map([items[1]], 'stalker', False)
m.update(d)
stalker_key = k[0]
bq.save_map(m, MAP)

port = free_port()
resolver.configure(map_file=MAP, port=port,
                   stalker_factory=lambda: FakeStalker(),
                   engine_config=None)
resolver.start(port)
time.sleep(0.4)
base = 'http://127.0.0.1:%d' % port

check('resolver reports running', resolver.running() is True)

code, loc, _ = get('%s/play/%s' % (base, direct_key))
check('direct entry redirects', code == 302, str(code))
check('redirect points at the provider url',
      loc == 'http://s:8080/live/u/p/1.ts', str(loc))

code, loc, _ = get('%s/play/%s' % (base, stalker_key))
check('stalker entry redirects', code == 302, str(code))
check('link was created on demand',
      loc == 'http://real/from-portal?token=abc', str(loc))
check('create_link received the stored cmd',
      FakeStalker.calls == ['ffmpeg http://portal/ch2'], str(FakeStalker.calls))

code, _, _ = get('%s/play/deadbeef' % base)
check('unknown key gives 404', code == 404, str(code))

code, _, _ = get('%s/nothing' % base)
check('unknown path gives 404', code == 404, str(code))

code, _, body = get('%s/status' % base)
st = json.loads(body.decode())
check('status is JSON', code == 200 and st['ok'] is True)
check('status counts map entries', st['entries'] == len(m), str(st['entries']))
check('status reports no engine', st['engine_running'] is False)

resolver.stop()
time.sleep(0.2)
check('resolver stops', resolver.running() is False)

shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
