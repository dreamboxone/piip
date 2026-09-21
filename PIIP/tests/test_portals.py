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
"""Stalker portal lists: parsing them, and the screen that imports them.

These lists are hand-edited and pasted between people, so the parser has to
survive anything: blank lines, comments, duplicates, MACs written in either
case, portals written with or without their /c/ suffix.
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

from enigma_stub import Session
import PIIP.plugin                      # builds config.plugins.piip
from PIIP.utils import portalconf, servers

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + (' :: ' + str(extra) if extra else ''))
    if not cond:
        FAIL.append(name)


SAMPLE = """
# a portal list as they are actually shared
http://4y-ott.online:8080/c/mac=00:1A:79:63:5F:84
http://700730.org:8080/c/mac=00:1a:79:22:46:52

; another comment
http://portal.example.com:80/c/  00:1A:79:B1:0A:13
http://portal.example.com:80/stalker_portal/  00:1A:79:B1:0A:25
http://4y-ott.online:8080/c/mac=00:1A:79:63:5F:84
this line has no url at all
http://nomac.example.com:8080/c/
"""

print('parsing a shared portal list')
entries = portalconf.parse(SAMPLE)
check('every good line is found', len(entries) == 4, str(len(entries)))
check('the mac comes off the url',
      entries[0] == {'portal': 'http://4y-ott.online:8080/c/',
                     'mac': '00:1A:79:63:5F:84'}, str(entries[0]))
check('a lowercase mac is normalised',
      entries[1]['mac'] == '00:1A:79:22:46:52', entries[1]['mac'])
check('a whitespace-separated line works too',
      entries[2]['portal'] == 'http://portal.example.com:80/c/',
      entries[2]['portal'])
check('a /stalker_portal/ suffix is normalised the same way',
      entries[3]['portal'] == 'http://portal.example.com:80/c/',
      entries[3]['portal'])
check('a repeated portal is not listed twice',
      [e['mac'] for e in entries].count('00:1A:79:63:5F:84') == 1)
check('a line without a mac is skipped',
      not any('nomac' in e['portal'] for e in entries))
check('comments are skipped', not any('#' in e['portal'] for e in entries))

print('')
print('every parsed value is a native str')
for entry in entries:
    for key, value in entry.items():
        check('%s is str' % key, isinstance(value, str),
              type(value).__name__)

print('')
print('normalising a portal')
for given, wanted in (
        ('http://h:8080', 'http://h:8080/c/'),
        ('http://h:8080/', 'http://h:8080/c/'),
        ('http://h:8080/c/', 'http://h:8080/c/'),
        ('http://h:8080/c/mac=00:1A:79:00:00:00', 'http://h:8080/c/'),
        ('http://h:8080/stalker_portal/server/load.php', 'http://h:8080/c/'),
        ('http://h:8080/portal.php', 'http://h:8080/c/')):
    check('%s -> %s' % (given, wanted),
          portalconf.normalise_portal(given) == wanted,
          portalconf.normalise_portal(given))

print('')
print('the hostname is what goes on screen')
check('a portal reduces to its host',
      portalconf.hostname('http://4y-ott.online:8080/c/')
      == '4y-ott.online:8080')
check('an empty portal is an empty host', portalconf.hostname('') == '')
check('a bare host is left alone', portalconf.hostname('h:80') == 'h:80')

print('')
print('rubbish input is never fatal')
for junk in ('', '   ', '\\n\\n', 'not a list at all',
             '<html><body>404</body></html>', b'\\x00\\x01\\x02binary'):
    got = portalconf.parse(junk)
    check('%r parses to nothing' % (junk[:20],), got == [], str(got))

print('')
print('a local list is found where receivers keep one')
TMP = tempfile.mkdtemp(prefix='farsi_portals_')
missing = os.path.join(TMP, 'nothing.conf')
present = os.path.join(TMP, 'stalkerclient.conf')
open(present, 'w').write(SAMPLE)
check('no file means no path', portalconf.local_path([missing]) == '')
check('the first existing file wins',
     portalconf.local_path([missing, present]) == present)
found, path = portalconf.load_local([missing, present])
check('a local list loads', len(found) == 4, str(len(found)))
check('and reports where it came from', path == present)
check('a missing list is empty, not an error',
      portalconf.load_local([missing]) == ([], ''))

print('')
print('fetching without an address says so instead of failing')
got, why = portalconf.fetch('')
check('an empty url is refused', got == [] and 'no list address' in why, why)

print('')
print('the importer screen')
from PIIP.screens import portalloader, serverlist

xml = portalloader.build_skin()
try:
    ET.fromstring(xml)
    ok, why = True, '%d widgets' % xml.count('<widget')
except Exception as exc:
    ok, why = False, str(exc)
check('the skin parses', ok, why)
check('it is titled the way the reference titles it',
      'STALKER - IMPORT PORTALS' in xml)
for label in ('IMPORT', 'LOAD ONLINE', 'CHECK'):
    check('the %s chip is there' % label, '"%s"' % label in xml, label)

import re
in_skin = set(re.findall(r'<widget name="(\\w+)"', xml))
src_path = portalloader.__file__
if src_path.endswith(('.pyc', '.pyo')):
    src_path = src_path[:-1]
import io as _io
created = set(re.findall(r"self\\['(\\w+)'\\]\\s*=",
                         _io.open(src_path, encoding='utf-8').read()))
created -= {'actions'}
check('every widget it builds is in the skin',
      not sorted(created - in_skin), str(sorted(created - in_skin)))

print('')
print('it opens, lists and imports')
servers.DIR = TMP
session = Session()
screen = portalloader.FarsiPortalLoader(session)
screen.applySkin()
screen.layoutFinished()
check('an empty receiver lists nothing', screen.portals == [])
check('and says what to do about it',
      'YELLOW' in screen['note'].getText(), screen['note'].getText())
check('nothing can be imported from an empty list',
      screen.selected() is None)

screen.portals = portalconf.parse(SAMPLE)
screen.refresh()
check('every portal gets a row',
      len(screen['list'].list) == 4, str(screen['list'].list))
check('a row is numbered, hosted and MACed',
      screen['list'].list[0]
      == 'Server 01  4y-ott.online:8080  |  00:1A:79:63:5F:84',
      screen['list'].list[0])
check('rows are native str',
      all(isinstance(r, str) for r in screen['list'].list))

screen['list'].moveToIndex(0)
screen.keyImport()
saved = servers.load('stalker')
check('importing writes a saved server', len(saved) == 1, str(saved))
check('it keeps the portal and the mac',
      saved and saved[0]['portal'] == 'http://4y-ott.online:8080/c/'
      and saved[0]['mac'] == '00:1A:79:63:5F:84', str(saved))
check('and says which one it took',
      "Imported '4y-ott.online:8080'" in screen['note'].getText(),
      screen['note'].getText())

screen.keyImport()
check('importing the same one twice is not a duplicate',
      len(servers.load('stalker')) == 1)

print('')
print('CHECK actually reaches the provider')
# The name was wrong here and nothing caught it until the receiver did:
# the failure only happens once the worker thread runs.
screen['list'].moveToIndex(0)
ok, err = True, ''
try:
    screen.handshake(screen.portals[0])
except AttributeError as exc:      # a wrong name, not a dead portal
    ok, err = False, str(exc)
except Exception as exc:           # no network here, which is expected
    err = '%s (network, fine)' % type(exc).__name__
check('handshake finds the provider class', ok, err)

print('')
print('the check button reports both outcomes without raising')
screen.onChecked(True, '')
check('a live portal reads WORKING', 'WORKING' in screen['note'].getText(),
      screen['note'].getText())
screen.onChecked(False, '')
check('a dead one reads DEAD', 'DEAD' in screen['note'].getText(),
      screen['note'].getText())
screen.onChecked(None, 'timed out')
check('an error says what went wrong',
      'DEAD' in screen['note'].getText()
      and 'timed out' in screen['note'].getText(),
      screen['note'].getText())

print('')
print('a download that fails does not empty the list')
before = list(screen.portals)
screen.onDownloaded(None, 'no route to host')
check('the portals survive a failed fetch', screen.portals == before)
check('and the failure is on screen',
      'Download error' in screen['note'].getText(),
      screen['note'].getText())
screen.onDownloaded(([], 'found no portals in it'), '')
check('an empty download is reported, not accepted',
      screen.portals == before
      and 'No portals found' in screen['note'].getText(),
      screen['note'].getText())

print('')
print('INFO on the stalker picker is what opens it')
session = Session()
picker = serverlist.FarsiServerPicker(session, 'stalker')
picker.applySkin()
picker.layoutFinished()
check('the picker binds info', 'info' in picker.keymap())
check('and says so in its footer',
      'INFO' in serverlist.build_skin('stalker', picker=True))
picker.openPortals()
check('INFO opens the importer',
      any(isinstance(d, portalloader.FarsiPortalLoader)
          for d in session.dialogs), str(session.dialogs))

session = Session()
other = serverlist.FarsiServerPicker(session, 'm3u')
other.applySkin()
other.layoutFinished()
other.openPortals()
check('the other types explain why they have no portal list',
      'Stalker' in other['status'].getText(), other['status'].getText())

shutil.rmtree(TMP, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
