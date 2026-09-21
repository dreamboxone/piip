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
"""Every screen's skin must be well-formed and use the shared palette.

A malformed skin is not a Python error: Enigma2 silently falls back or draws
nothing, so it only shows up as a blank screen on the receiver. The colour
convention matters just as much - the first byte is transparency, and getting
it backwards paints over the video layer.
"""

import importlib
import io
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(PKG))

import enigma_stub
enigma_stub.install()

from PIIP.utils import skin as sk
from PIIP import main as main_mod
from PIIP import plugin as plugin_mod

def source_of(module):
    """The .py text of a module.

    Python 2 sets __file__ to the .pyc once one exists, and reading that as
    UTF-8 blows up - which is exactly what happened on the receiver.
    """
    path = module.__file__
    if path.endswith(('.pyc', '.pyo')):
        path = path[:-1]
    return io.open(path, encoding='utf-8').read()


FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


SCREENS = [
    ('main', 'PIIP.main', ()),
    ('channels', 'PIIP.screens.channels', ()),
    ('vod', 'PIIP.screens.vod', ('Movies',)),
    ('bouquets', 'PIIP.screens.bouquets', ()),
    ('diagnose', 'PIIP.screens.diagnose', ()),
    ('downloads', 'PIIP.screens.downloadmanager', ()),
    ('epg', 'PIIP.screens.epgscreen', ()),
    ('subtitles', 'PIIP.screens.subtitlepicker', ()),
    ('settings', 'PIIP.screens.setup', ()),
    ('zaplist', 'PIIP.screens.zaplist', ()),
    ('serverlist', 'PIIP.screens.serverlist', ()),
    ('serversetup', 'PIIP.screens.serversetup', ()),
    ('iptvorg', 'PIIP.screens.iptvorg', ()),
    ('home', 'PIIP.screens.home', ()),
    ('player', 'PIIP.screens.player', ()),
]

print('every screen produces well-formed XML')
built = {}
for label, module, args in SCREENS:
    xml = importlib.import_module(module).build_skin(*args)
    built[label] = xml
    try:
        ET.fromstring(xml)
        ok, why = True, '%d widgets' % xml.count('<widget')
    except Exception as exc:
        ok, why = False, str(exc)
    check('%s skin parses' % label, ok, why)

print('')
print('the video layer is not painted over')
for label in ('player',):
    root = ET.fromstring(built[label])
    bg = root.get('backgroundColor', '')
    check('%s screen is fully transparent' % label, bg == sk.TRANSPARENT, bg)
    check('%s has no border' % label, root.get('flags') == 'wfNoBorder')
    check('%s covers the whole screen' % label,
          root.get('position') == '0,0', root.get('position'))

print('')
print('the main menu hides the running channel')
# A full-screen window with wfNoBorder is an overlay: its ground is never
# painted and whatever the tuner is showing comes straight through. The
# reference plugin uses a plain window on opaque black, with the dim sheet
# behind the artwork rather than over it.
root = ET.fromstring(built['main'])
check('main menu ground is opaque black',
      root.get('backgroundColor') == sk.OPAQUE, root.get('backgroundColor'))
check('main menu is not a borderless overlay',
      root.get('flags') is None, root.get('flags'))
scrims = [e for e in root.iter('eLabel')
          if e.get('backgroundColor') == sk.SCRIM]
check('the main menu has one dim sheet', len(scrims) == 1)
if scrims:
    check('the dim sheet sits behind the artwork',
          scrims[0].get('zPosition') == '-1', scrims[0].get('zPosition'))
bgs = [w for w in root.iter('widget') if w.get('name') == 'bg']
check('the background pixmap is present', len(bgs) == 1)
if bgs:
    check('the background is drawn in front of the dim sheet',
          int(bgs[0].get('zPosition')) > -1, bgs[0].get('zPosition'))

print('')
print('nothing runs through the row of chips')
# The status line sat at y=1040 and the chips start at 996: on the receiver
# the text ran straight through them.
for label in ('main', 'home'):
    root = ET.fromstring(built[label])
    chips = [e for e in root.iter('eLabel') if e.get('cornerRadius')]
    top = min(int(e.get('position').split(',')[1]) for e in chips)
    for w in root.iter('widget'):
        if w.get('name') == 'bg':          # the wallpaper is meant to be under
            continue
        pos = w.get('position') or '0,0'
        y = int(pos.split(',')[1])
        h = int((w.get('size') or '0,0').split(',')[1])
        check('%s: %s clears the chips' % (label, w.get('name')),
              y + h <= top or y >= top, '%d..%d vs chips at %d'
              % (y, y + h, top))

print('')
print('the main menu frees the tuner')
main_src = source_of(importlib.import_module('PIIP.main'))
backdrop_src = source_of(
    importlib.import_module('PIIP.utils.backdrop'))
check('artwork is loaded with LoadPixmap',
      'LoadPixmap(' in backdrop_src
      and '.setPixmapFromFile(' not in backdrop_src)
# One loader, so a fault in it cannot hide in seven other copies.
for mod in ('PIIP.screens.carousel', 'PIIP.screens.channels',
            'PIIP.screens.serverlist', 'PIIP.main'):
    src = source_of(importlib.import_module(mod))
    check('%s does not load pixmaps itself' % mod.split('.')[-1],
          'LoadPixmap' not in src)
check('the running service is stopped on entry',
      'nav.stopService()' in main_src)
check('the running service is restored on exit',
      'self.onClose.append(self.restoreService)' in main_src)

LIST_SCREENS = ('channels', 'vod', 'bouquets', 'diagnose', 'epg',
                'subtitles', 'serverlist', 'serversetup')

print('')
print('browsing screens are full-screen, over wallpaper')
# The reference plugin's list screens are the whole screen on opaque black
# with a picture behind them, not a floating panel.
for label in LIST_SCREENS:
    root = ET.fromstring(built[label])
    check('%s sits on the opaque ground' % label,
          root.get('backgroundColor') == sk.OPAQUE,
          root.get('backgroundColor'))
    check('%s is not a borderless overlay' % label,
          root.get('flags') is None, root.get('flags'))
    bgs = [w for w in root.iter('widget') if w.get('name') == 'bg']
    check('%s has a wallpaper widget' % label, len(bgs) == 1)
    scrims = [e for e in root.iter('eLabel')
              if e.get('backgroundColor') == sk.LIST_SCRIM]
    check('%s dims its wallpaper' % label, len(scrims) == 1)
    if scrims:
        check('%s dim sheet is behind the picture' % label,
              scrims[0].get('zPosition') == '-1', scrims[0].get('zPosition'))
    lists = [w for w in root.iter('widget') if w.get('name') == 'list']
    check('%s has a list widget' % label, len(lists) == 1)
    if lists:
        w = lists[0]
        check('%s list uses the shared selection colour' % label,
              w.get('backgroundColorSelected') == sk.LIST_BG_SEL,
              w.get('backgroundColorSelected'))
        check('%s list uses the shared ground' % label,
              w.get('backgroundColor') == sk.LIST_BG)

print('')
print('nothing overlaps in the top-right corner')
# Two right-aligned texts in the same corner is well-formed XML and
# unreadable on a television, which is exactly what happened.
for label in LIST_SCREENS:
    root = ET.fromstring(built[label])
    right = []
    for el in list(root.iter('widget')) + list(root.iter('eLabel')):
        if el.get('halign') != 'right':
            continue
        try:
            y = int((el.get('position') or '0,9999').split(',')[1])
        except ValueError:
            continue
        if y < 100:                       # inside the header band
            right.append(el)
    expected = 0 if label == 'serversetup' else 1
    check('%s has the expected header corner content' % label,
          len(right) == expected,
          str([(e.get('name') or e.get('text')) for e in right]))

print('')
print('a chip never claims a colour it is not')
# "GREEN Save" printed on a gold chip is how this looked on the receiver.
KEYS = ('RED', 'GREEN', 'YELLOW', 'BLUE')
for label in LIST_SCREENS:
    root = ET.fromstring(built[label])
    named = [e.get('text') for e in root.iter('eLabel')
             if e.get('text') and e.get('cornerRadius')
             and any(k in e.get('text').split() for k in KEYS)
             and 'EXIT' not in e.get('text')]
    # The key hints live in the one pale tab, which is allowed to name them.
    hints = [t for t in named if ' - ' not in t]
    check('%s chips carry the action, not the key' % label, not hints,
          str(hints))
check('server setup SAVE chip is yellow',
      'text="SAVE"' in built['serversetup'] and
      ('backgroundColor="%s"' % sk.ACCENT_WARM) in built['serversetup'])

print('')
print('every screen has a footer of coloured chips')
for label in ('channels', 'vod', 'bouquets', 'diagnose', 'settings'):
    check('%s draws chips' % label, 'cornerRadius' in built[label])

print('')
print('plugin identity')
check('main menu title omits the software version',
      main_mod.FarsiMain.TITLE == 'PIIP', main_mod.FarsiMain.TITLE)
plugin_src = source_of(plugin_mod)
check('plugin browser uses the requested description',
      "description='Xtream / M3U /Stalker IPTV Player with translation'"
      in plugin_src)

print('')
print('VOD visual modes reconstructed from the auxiliary binaries')
vod_mod = importlib.import_module('PIIP.screens.vod')
old_style = vod_mod._c.skin_style.value
mode_skins = {}
for style in ('default', 'hybrid', 'cover', 'cover2d'):
    vod_mod._c.skin_style.value = style
    mode_skins[style] = vod_mod.build_skin('Movies')
    root = ET.fromstring(mode_skins[style])
    names = set(w.get('name') for w in root.iter('widget'))
    check('%s mode includes poster, backdrop and rating' % style,
          {'poster', 'art', 'rating'}.issubset(names))
vod_mod._c.skin_style.value = old_style
check('cover mode has distinct geometry',
      mode_skins['cover'] != mode_skins['hybrid'])
check('2D cover mode uses the portable cover geometry',
      mode_skins['cover2d'] == mode_skins['cover'])
check('no bare DreamOS-incompatible SCALE_STRETCH expression',
      all('scale_flags=SCALE_STRETCH' not in xml
          for xml in mode_skins.values()))
cover_skin = mode_skins.get('cover', '')
check('cover mode uses the real Enigma2 grid renderer',
      'mode="grid"' in cover_skin and 'TemplatedMultiContent' in cover_skin)
check('grid resolves SCALE_STRETCH outside the broken converter namespace',
      '__import__("enigma").SCALE_STRETCH' in cover_skin)
check('grid keeps Hybrid zoom and wrap behaviour',
      'selectionZoom="1.05"' in cover_skin and
      'enableWrapAround="1"' in cover_skin)

print('')
print('reported layout regressions')
bouquet_root = ET.fromstring(built['bouquets'])
bouquet_info = next(w for w in bouquet_root.iter('widget')
                    if w.get('name') == 'info')
check('bouquet summary is tall enough for all six lines',
      int(bouquet_info.get('size').split(',')[1]) >= 200,
      bouquet_info.get('size'))
check('bouquet summary stays above the footer',
      int(bouquet_info.get('position').split(',')[1]) +
      int(bouquet_info.get('size').split(',')[1]) < 980)

downloads_root = ET.fromstring(built['downloads'])
download_status = next(w for w in downloads_root.iter('widget')
                       if w.get('name') == 'status')
check('download count follows Hybrid in the top-right header',
      int(download_status.get('position').split(',')[1]) == 15,
      download_status.get('position'))

player_mod = importlib.import_module('PIIP.screens.player')
player_root = ET.fromstring(player_mod.build_skin())
player_state = next(w for w in player_root.iter('widget')
                    if w.get('name') == 'state')
check('player state never wraps translating/buffering',
      player_state.get('noWrap') == '1')
check('player state has room for translation status',
      int(player_state.get('size').split(',')[0]) >= sk.scale(300),
      player_state.get('size'))

import struct
with open(os.path.join(PKG, 'icon.png'), 'rb') as icon_file:
    icon_head = icon_file.read(24)
icon_w, icon_h = struct.unpack('>II', icon_head[16:24])
check('plugin browser logo matches the other plugins (100x40)',
      (icon_w, icon_h) == (100, 40), '%dx%d' % (icon_w, icon_h))

print('')
print('escaping')
esc = sk.chip('< > & "quoted"', 0, 0, sk.BTN_RED)
check('angle brackets escaped', '&lt;' in esc and '&gt;' in esc)
check('ampersand escaped', '&amp;' in esc)
check('quotes escaped', '&quot;' in esc)
ET.fromstring('<r>%s</r>' % esc)
check('the escaped chip is parseable', True)

head = sk.header('A < B', 'x & y')
ET.fromstring('<r>%s</r>' % head)
check('header text is escaped too', '&lt;' in head and '&amp;' in head)

print('')
print('colour convention')
check('transparent is ff, not 00', sk.TRANSPARENT.startswith('#ff'))
check('the panel is translucent', sk.PANEL.startswith('#d0'))
check('the header bar is opaque', not sk.HEADER.startswith('#ff'))
check('accent matches the reference plugin', sk.ACCENT == '#00d4ff')
check('list selection matches the reference', sk.LIST_BG_SEL == '#1e5799')
check('zap list ground matches the reference', sk.ZAP_GROUND == '#d0000000')

print('')
print('720p scaling')
# 1920 -> 1280 is exactly two thirds.
check('scale is two thirds', sk.scale(900) == 600, str(sk.scale(900)))
check('a full width scales to the 720p width', sk.scale(1920) == 1280)
check('a full height scales to the 720p height', sk.scale(1080) == 720)
check('scale of zero is zero', sk.scale(0) == 0)

print('')
print('IPTV-org sources screen follows HybridIPTV')
# Reported from the receiver: no wallpaper, left-aligned small text and no
# M3U emblem, where the reference shows all three.
root = ET.fromstring(built['iptvorg'])
names = set(w.get('name') for w in root.iter('widget'))
check('iptvorg has wallpaper, emblem and list',
      {'bg', 'logo', 'list'}.issubset(names), str(sorted(names)))
logo = next(w for w in root.iter('widget') if w.get('name') == 'logo')
lx, ly = [int(v) for v in logo.get('position').split(',')]
lw, lh = [int(v) for v in logo.get('size').split(',')]
check('emblem is centred like the reference', lx + lw // 2 == 960 and ly == 80,
      logo.get('position'))
check('emblem is the reference 450px square', (lw, lh) == (450, 450))
lst = next(w for w in root.iter('widget') if w.get('name') == 'list')
check('sources list sits where the reference puts it',
      lst.get('position') == '460,550' and lst.get('size') == '1000,420',
      '%s %s' % (lst.get('position'), lst.get('size')))
check('a pane is drawn behind the sources list',
      any(e.get('position') == '460,550' and e.get('size') == '1000,420'
          for e in list(root.iter('eLabel')) + list(root.iter('ePixmap'))))
check('the hint names BLUE search as the reference does',
      'BLUE - Search' in built['iptvorg'])
iptv_src = source_of(importlib.import_module('PIIP.screens.iptvorg'))
check('iptvorg paints bg_m3u.png and the m3u emblem',
      "backdrop(self, 'bg_m3u.png')" in iptv_src and
      "'logo', 'emblem_m3u.png'" in iptv_src)
textlist_mod = importlib.import_module('PIIP.utils.textlist')
old_rich = textlist_mod.E2ListSource
textlist_mod.E2ListSource = object
try:
    rich_xml = importlib.import_module('PIIP.screens.iptvorg').build_skin()
finally:
    textlist_mod.E2ListSource = old_rich
ET.fromstring(rich_xml)
check('receiver listbox centres 40px rows',
      'RT_HALIGN_CENTER' in rich_xml and 'gFont(&quot;Regular&quot;,40)' in rich_xml
      and 'render="Listbox"' in rich_xml, rich_xml[-400:])
setup_root = ET.fromstring(built['serversetup'])
setup_list = next(w for w in setup_root.iter('widget') if w.get('name') == 'list')
check('m3u setup pane is exactly its two rows',
      setup_list.get('size') == '1000,140', setup_list.get('size'))

print('')
print('every widget a screen creates exists in its skin')
# Enigma2 raises SkinError for a widget that is missing from the skin, and
# the screen then never opens at all.
import re
for label, module, args in SCREENS:
    mod = importlib.import_module(module)
    in_skin = set(re.findall(r'<widget name="(\w+)"', built[label]))
    source = source_of(mod)
    created = set(re.findall(r"self\['(\w+)'\]\s*=", source))
    created -= {'actions', 'numbers', 'config'}
    missing = sorted(created - in_skin)
    check('%s declares every widget it builds' % label, not missing,
          str(missing))

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
