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
"""Saved servers: the store, the screens over it, and the two carousels.

The reference plugin's front door is a provider chooser backed by three
JSON files, not a single set of credentials in the settings, and these
check that this one behaves the same way.
"""

import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(PKG))

import enigma_stub
enigma_stub.install()

from enigma_stub import Session, OPENED
from PIIP.utils import servers
from PIIP.utils.compat import native

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + (' :: ' + str(extra) if extra else ''))
    if not cond:
        FAIL.append(name)


TMP = tempfile.mkdtemp(prefix='farsi_servers_')
servers.DIR = TMP

XTREAM = {'type': 'xtream', 'name': 'Home', 'host': 'http://tv.example:8080',
          'user': 'bob', 'password': 'hunter2'}
M3U = {'type': 'm3u', 'name': 'Free', 'url': 'http://iptv-org/index.m3u'}
STALKER = {'type': 'stalker', 'name': 'Portal',
           'portal': 'http://portal.tv:8080/c/', 'mac': '00:1A:79:11:22:33'}

# ---------------------------------------------------------------- the store

print('an empty store')
for kind in servers.TYPES:
    check('%s starts empty' % kind, servers.load(kind) == [])
check('load_all is empty too', servers.load_all() == [])
check('a blank entry has every field',
      set(servers.blank('xtream')) ==
      {'type', 'name', 'host', 'user', 'password'})

print('')
print('saving and reading back')
for entry in (XTREAM, M3U, STALKER):
    check('%s saves without error' % entry['type'],
          servers.upsert(entry['type'], entry) == '')
for entry in (XTREAM, M3U, STALKER):
    back = servers.load(entry['type'])
    check('%s reads back one entry' % entry['type'], len(back) == 1,
          str(back))
    check('%s keeps every field' % entry['type'],
          all(back[0].get(k) == v for k, v in entry.items()), str(back[0]))
check('load_all returns all three', len(servers.load_all()) == 3)
check('load_all is ordered by type',
      [e['type'] for e in servers.load_all()] == list(servers.TYPES))

print('')
print('an edit replaces the server it edits, never its namesakes')
servers.upsert('xtream', dict(XTREAM, host='http://moved:8080'), replaces=XTREAM)
back = servers.load('xtream')
check('editing the address replaces rather than appends', len(back) == 1, str(back))
check('the replacement won', back[0]['host'] == 'http://moved:8080')
moved = back[0]
servers.upsert('xtream', dict(moved, name='Renamed'), replaces=moved)
check('renaming keeps one entry',
      [e['name'] for e in servers.load('xtream')] == ['Renamed'])
servers.upsert('xtream', dict(moved, name='Home'), replaces=dict(moved, name='Renamed'))
servers.upsert('xtream', dict(XTREAM, name='Second'))
check('a different account is a second server', len(servers.load('xtream')) == 2)
check('entries are sorted by name',
      [e['name'] for e in servers.load('xtream')] == ['Home', 'Second'])
servers.upsert('xtream', dict(moved, name='HOME'))
check('saving the same connection again does not duplicate it',
      len(servers.load('xtream')) == 2,
      str([e['name'] for e in servers.load('xtream')]))

print('')
print('portals sharing a name are never wiped')
for mac in ('00:1A:79:00:00:01', '00:1A:79:00:00:02', '00:1A:79:00:00:03'):
    servers.upsert('stalker', {'name': 'shared.tv:80', 'portal': 'http://shared.tv/c/',
                               'mac': mac})


def shared_count():
    return len([e for e in servers.load('stalker') if e['name'] == 'shared.tv:80'])


check('every MAC imported under one host name is kept', shared_count() == 3,
      str(shared_count()))
servers.upsert('stalker', {'name': 'shared.tv:80', 'portal': 'http://shared.tv/c/',
                           'mac': '00:1A:79:00:00:02'})
check('connecting one MAC of a shared portal removes none of the others',
      shared_count() == 3, str(shared_count()))
one = [e for e in servers.load('stalker') if e['mac'] == '00:1A:79:00:00:03'][0]
servers.delete('stalker', one['name'], entry=one)
check('deleting one of them deletes only that one', shared_count() == 2)
for e in [e for e in servers.load('stalker') if e['name'] == 'shared.tv:80']:
    servers.delete('stalker', e['name'], entry=e)

print('')
print('deleting')
servers.delete('xtream', 'second')
check('delete ignores case too',
      [e['name'] for e in servers.load('xtream')] == ['HOME'])
servers.delete('xtream', 'nothing here')
check('deleting something absent is harmless',
      len(servers.load('xtream')) == 1)

print('')
print('a damaged file is never fatal')
open(servers.path('m3u'), 'w').write('{ not json at all')
check('unparseable json reads as empty', servers.load('m3u') == [])
open(servers.path('m3u'), 'w').write('{"not": "a list"}')
check('a json object reads as empty', servers.load('m3u') == [])
open(servers.path('m3u'), 'w').write('[1, 2, "three"]')
check('non-dict members are skipped', servers.load('m3u') == [])
servers.upsert('m3u', M3U)

print('')
print('every value is a native str')
# json gives unicode back on Python 2 and the SWIG widgets reject it.
for entry in servers.load_all():
    for key, value in entry.items():
        check('%s/%s is str' % (entry['name'], key), isinstance(value, str),
              type(value).__name__)

print('')
print('missing fields are named, not just counted')
check('a blank xtream lists all four',
      len(servers.missing('xtream', servers.blank('xtream'))) == 4)
check('http:// on its own counts as empty',
      'Playlist URL' in servers.missing('m3u', {'name': 'x',
                                                'url': 'http://'}))
check('a complete entry is missing nothing',
      servers.missing('xtream', XTREAM) == [])
check('whitespace does not count as filled in',
      servers.missing('m3u', {'name': ' ', 'url': ' '}) ==
      ['Playlist name', 'Playlist URL'])

print('')
print('labels are safe to put on screen')
for entry in servers.load_all():
    text = servers.label(entry)
    check('%s label is a str' % entry['name'], isinstance(text, str))
    check('%s label names the server' % entry['name'],
          entry['name'] in text, text)
    check('%s label names the type' % entry['name'],
          entry['type'].upper() in text, text)
creds = servers.label({'type': 'm3u', 'name': 'x',
                       'url': 'http://h:8080/get.php?password=secret'})
check('a label does not carry the password', 'secret' not in creds, creds)

# ------------------------------------------------------------- activation

print('')
print('connecting copies the server into the config')
import PIIP.plugin            # builds config.plugins.piip
from Components.config import config as cfg
servers.activate(XTREAM, cfg)
_c = cfg.plugins.piip
check('the source type follows', _c.source.value == 'xtream')
check('the host follows', _c.xtream_host.value == XTREAM['host'])
check('the user follows', _c.xtream_user.value == XTREAM['user'])
check('the password follows', _c.xtream_pass.value == XTREAM['password'])
check('the name is remembered', _c.active_server.value == 'Home')

servers.activate(STALKER, cfg)
check('switching type follows', _c.source.value == 'stalker')
check('the portal follows', _c.stalker_portal.value == STALKER['portal'])
check('the mac follows', _c.stalker_mac.value == STALKER['mac'])

back = servers.active(cfg)
check('the active server round-trips', back['portal'] == STALKER['portal']
      and back['mac'] == STALKER['mac'] and back['name'] == 'Portal',
      str(back))

servers.activate(M3U, cfg)
check('m3u activation follows', _c.source.value == 'm3u'
      and _c.m3u_url.value == M3U['url'])

# ----------------------------------------------------------------- screens

print('')
print('the screens over the store')
from PIIP.screens import serverlist, serversetup, home
from PIIP import main as main_mod

for label, module, args in (('server list', serverlist, ()),
                            ('server setup', serversetup, ()),
                            ('home', home, ()),
                            ('main', main_mod, ())):
    xml = module.build_skin(*args)
    try:
        ET.fromstring(xml)
        ok, why = True, '%d widgets' % xml.count('<widget')
    except Exception as exc:
        ok, why = False, str(exc)
    check('%s skin parses' % label, ok, why)

print('')
print('the setup screen edits, saves and connects')
for kind in servers.TYPES:
    session = Session()
    screen = serversetup.FarsiServerSetup(session, kind)
    screen.applySkin()
    screen.layoutFinished()
    check('%s setup lists every field' % kind,
          len(screen['list'].list) == len(servers.FIELDS[kind]),
          str(screen['list'].list))
    check('%s setup rows are str' % kind,
          all(isinstance(r, str) for r in screen['list'].list))
    check('%s setup loads its provider logo' % kind,
          screen['logo'].filename is not None)
    # An empty form must refuse to save and say what is missing.
    screen.entry = servers.blank(kind)
    check('%s refuses to save empty' % kind, screen.saveEntry() is False)
    check('%s says what is missing' % kind,
          'Still empty' in screen['status'].getText(),
          screen['status'].getText())

print('')
print('a password is never shown in the clear')
session = Session()
screen = serversetup.FarsiServerSetup(session, 'xtream', XTREAM)
screen.applySkin()
screen.layoutFinished()
rows = '\n'.join(screen['list'].list)
check('the password row is starred', 'hunter2' not in rows, rows)
check('the username is not', 'bob' in rows)

print('')
print('provider setup pages match the HybridIPTV entry screens')
skins = dict((kind, serversetup.build_skin(kind)) for kind in servers.TYPES)
check('M3U has all four footer actions',
      all(('text="%s"' % label) in skins['m3u'] for label in
          ('LOAD', 'SAVE', 'SERVERS LOCAL', 'SERVERS Online')))
check('Stalker title is only the setup title',
      'STALKER PORTAL - SETUP' in skins['stalker'] and
      'name="head"' not in skins['stalker'])
check('Xtream uses the requested login title',
      'XTREAM CODES-LOGIN' in skins['xtream'])
check('all setup skins declare the provider logo',
      all('name="logo"' in xml for xml in skins.values()))
check('setup headers have no duplicate right-hand title',
      all('halign="right"' not in xml.split('<eLabel position="0,')[0]
          for xml in skins.values()))

print('')
print('provider setup actions match HybridIPTV')
for kind in servers.TYPES:
    action_screen = serversetup.FarsiServerSetup(Session(), kind)
    actions = action_screen['actions'].actions
    check('%s blue opens saved servers' % kind,
          actions.get('blue').wrapped == action_screen.importSaved)
    check('%s yellow saves the entry' % kind,
          actions.get('yellow').wrapped == action_screen.saveEntry)
    check('%s green connects or loads' % kind,
          actions.get('green').wrapped == action_screen.connect)
check('M3U INFO opens the online playlist browser',
      serversetup.FarsiServerSetup(Session(), 'm3u')['actions']
      .actions.get('info').wrapped.__name__ == 'openOnline')

main_actions = main_mod.FarsiMain(Session())['actions'].actions
check('main yellow opens the complete settings page',
      main_actions.get('yellow').wrapped.__name__ == 'openSettings')

print('')
print('connecting from setup saves first')
servers.delete('xtream', 'Fresh')
session = Session()
screen = serversetup.FarsiServerSetup(session, 'xtream',
                                      dict(XTREAM, name='Fresh'))
screen.applySkin()
screen.layoutFinished()
screen.connect()
check('the server was saved on connect',
      any(e['name'] == 'Fresh' for e in servers.load('xtream')))
check('connecting made it active', _c.active_server.value == 'Fresh')

print('')
print('the saved server list')
session = Session()
screen = serverlist.FarsiServerList(session)
screen.applySkin()
screen.layoutFinished()
count = len(servers.load_all())
check('every saved server is listed', len(screen['list'].list) == count,
      '%d != %d' % (len(screen['list'].list), count))
check('the count is on screen', str(count) in screen['status'].getText(),
      screen['status'].getText())
screen['list'].moveToIndex(0)
screen.choose()
check('OK activates the highlighted server',
      _c.active_server.value == servers.load_all()[0]['name'],
      _c.active_server.value)

print('')
print('the picker hands an entry back without touching the config')
_c.active_server.value = 'untouched'
session = Session()
picker = serverlist.FarsiServerPicker(session, 'm3u')
picker.applySkin()
picker.layoutFinished()
check('the picker shows only its own type',
      len(picker['list'].list) == len(servers.load('m3u')))
picker['list'].moveToIndex(0)
picker.choose()
check('picking does not activate', _c.active_server.value == 'untouched',
      _c.active_server.value)

print('')
print('an empty list says so instead of looking broken')
for kind in servers.TYPES:
    servers.save(kind, [])
session = Session()
screen = serverlist.FarsiServerList(session)
screen.applySkin()
screen.layoutFinished()
# The emptiness has to be visible in the list, not only in a status line
# under it: an empty screen over an identical one reads as a dead key.
check('an empty list says so in the list itself',
      screen['list'].list == [serverlist.EMPTY], str(screen['list'].list))
check('and the status line says what to do next',
      'GREEN' in screen['status'].getText(), screen['status'].getText())
check('nothing can be chosen from it', screen.selected() is None)

print('')
print('the picker names its own type, so it cannot be mistaken for the '
      'screen under it')
for kind in servers.TYPES:
    xml = serverlist.build_skin(kind, picker=True)
    check('%s picker is titled for its type' % kind,
          '%s SAVED SERVERS' % kind.upper() in xml, xml[:200])
    session = Session()
    pk = serverlist.FarsiServerPicker(session, kind)
    pk.applySkin()
    pk.layoutFinished()
    check('%s picker paints its own wallpaper' % kind,
          pk['bg'].filename is not None
          and pk['bg'].filename.endswith(serverlist.WALLPAPER[kind]),
          str(pk['bg'].filename))
check('the all-types list keeps the plain title',
      'SAVED SERVERS' in serverlist.build_skin()
      and 'STALKER' not in serverlist.build_skin())

print('')
print('the two carousels')
session = Session()
menu = main_mod.FarsiMain(session)
menu.applySkin()
menu.layoutFinished()
check('the main menu offers exactly the three provider types',
      [i[1] for i in menu.ITEMS] == list(servers.TYPES),
      str([i[1] for i in menu.ITEMS]))
for item in menu.ITEMS:
    check('%s has its own wallpaper' % item[1],
          os.path.exists(os.path.join(PKG, 'icons', item[4])), item[4])
    for suffix in ('.png', '_s.png'):
        art = os.path.join(PKG, 'icons', item[2] + suffix)
        check('artwork %s%s exists' % (item[2], suffix), os.path.exists(art),
              art)

session = Session()
hs = home.FarsiHome(session)
hs.applySkin()
hs.layoutFinished()
check('the home carousel includes downloads',
      [i[1] for i in hs.ITEMS] ==
      ['channels', 'movies', 'series', 'bouquets', 'downloads'],
      str([i[1] for i in hs.ITEMS]))
for item in hs.ITEMS:
    for suffix in ('.png', '_s.png'):
        art = os.path.join(PKG, 'icons', item[2] + suffix)
        check('home artwork %s%s exists' % (item[2], suffix),
              os.path.exists(art), art)
check('the home title is a str', isinstance(hs['title'].getText(), str))
check('the home status is a str', isinstance(hs['status'].getText(), str))

print('')
print('every widget the new screens build exists in their skins')
import re
for label, module, cls, args in (
        ('serverlist', serverlist, 'FarsiServerList', ()),
        ('serversetup', serversetup, 'FarsiServerSetup', ()),
        ('home', home, 'FarsiHome', ())):
    xml = module.build_skin(*args)
    in_skin = set(re.findall(r'<widget name="(\w+)"', xml))
    path = module.__file__
    if path.endswith(('.pyc', '.pyo')):
        path = path[:-1]
    import io as _io
    src = _io.open(path, encoding='utf-8').read()
    created = set(re.findall(r"self\['(\w+)'\]\s*=", src))
    created -= {'actions', 'numbers', 'config'}
    missing = sorted(created - in_skin)
    check('%s declares every widget it builds' % label, not missing,
          str(missing))

shutil.rmtree(TMP, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
