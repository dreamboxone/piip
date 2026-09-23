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
"""What differs between receiver images, and must not stop the plugin.

Two field failures on one image: a python3 build with no sqlite3 module,
where importing the catalogue cache killed every list screen, and an older
Tools.LoadPixmap whose signature has no `size`, where the whole interface
came up without a single picture.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

import enigma_stub                                            # noqa: E402
enigma_stub.install()

FAIL = []
RUN = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name +
          (' :: ' + extra if extra else ''))
    RUN.append(name)
    if not cond:
        FAIL.append(name)


# ------------------------------------------------ an image without sqlite3
class NoSqlite(object):
    """Make `import sqlite3` fail the way a minimal image does."""

    def find_module(self, name, path=None):                   # Python 2
        return self if name == 'sqlite3' else None

    def load_module(self, name):
        raise ImportError('No module named sqlite3')

    def find_spec(self, name, path=None, target=None):        # Python 3
        if name == 'sqlite3':
            raise ImportError('No module named sqlite3')
        return None


for name in ('sqlite3', 'PIIP.utils.sqldb'):
    sys.modules.pop(name, None)
sys.meta_path.insert(0, NoSqlite())
try:
    from PIIP.utils import sqldb
    imported = True
except ImportError as error:
    sqldb = None
    imported = False
    print('   import failed: %s' % error)
finally:
    sys.meta_path.pop(0)

check('the cache module imports on an image without sqlite3', imported)

if imported:
    check('it reports the cache as unavailable', not sqldb.available())
    check('a path can still be named, so callers can test for a copy',
          sqldb.path('id', 'live').endswith('.db'))
    failed_cleanly = False
    try:
        sqldb.connect('id', 'live')
    except ImportError:
        failed_cleanly = False
    except Exception:
        # Callers wrap this in except Exception and fall back to the network.
        failed_cleanly = True
    check('connecting raises an ordinary error the callers already catch',
          failed_cleanly)

# sqlite3 is back for everyone else. The package keeps its own reference to
# the module it imported, so that has to go as well as the sys.modules entry.
import importlib                                               # noqa: E402
import PIIP.utils                                              # noqa: E402
for name in ('sqlite3', 'PIIP.utils.sqldb'):
    sys.modules.pop(name, None)
if hasattr(PIIP.utils, 'sqldb'):
    del PIIP.utils.sqldb
real_sqldb = importlib.import_module('PIIP.utils.sqldb')
check('the cache is available again on a normal image',
      real_sqldb.available())

# ------------------------------------------- an image whose LoadPixmap
# --------------------------------------------- takes no size argument
from PIIP.utils import backdrop                                # noqa: E402

calls = []


def old_load_pixmap(path, *args, **kwargs):
    calls.append(dict(kwargs))
    if 'size' in kwargs:
        raise TypeError("LoadPixmap() got an unexpected keyword argument 'size'")
    return 'pixmap:' + path


backdrop.LoadPixmap = old_load_pixmap
check('a picture still loads where size is not accepted',
      backdrop.pixmap('/icons/bg.png', (100, 50)) == 'pixmap:/icons/bg.png')
check('it only falls back after trying the sized call',
      len(calls) == 2 and 'size' in calls[0] and 'size' not in calls[1])


def new_load_pixmap(path, *args, **kwargs):
    calls.append(dict(kwargs))
    return 'sized:' + path


del calls[:]
backdrop.LoadPixmap = new_load_pixmap
check('the size is still passed where the image accepts it',
      backdrop.pixmap('/icons/bg.png', (100, 50)) == 'sized:/icons/bg.png' and
      calls[0].get('size') == (100, 50))

del calls[:]
check('no size is invented when the widget has none',
      backdrop.pixmap('/icons/bg.png') == 'sized:/icons/bg.png' and
      'size' not in calls[0])

# --------------------------------- an image with an older MultiContent,
# ------------------------------------ where one unknown argument in a
# ------------------------------------ template empties the whole list
import types                                                   # noqa: E402

from PIIP.utils import skin as sk                              # noqa: E402
from PIIP.screens import m3ugroups                             # noqa: E402

del sk._MULTICONTENT[:]
modern = sk._multicontent()
check('a current image gets the colour and the stretch',
      modern[0] and 'SCALE_STRETCH' in modern[1])
check('the stretch is resolved inside the converter namespace',
      '__import__("enigma")' in modern[1])

current = sys.modules['Components.MultiContent']
enigma = sys.modules['enigma']


def older_image(pixmap, colour, stretch):
    """Stand in an image whose MultiContent is missing these."""
    module = types.ModuleType('Components.MultiContent')
    module.MultiContentEntryText = current.MultiContentEntryText
    if pixmap == 'flags':
        def entry(pos=None, size=None, png=None, flags=None):
            return (pos, size, png, flags)
    elif pixmap == 'none':
        def entry(pos=None, size=None, png=None):
            return (pos, size, png)
    else:
        entry = current.MultiContentEntryPixmapAlphaTest
    module.MultiContentEntryPixmapAlphaTest = entry
    if colour:
        module.MultiContentTemplateColor = current.MultiContentTemplateColor
    sys.modules['Components.MultiContent'] = module
    del sk._MULTICONTENT[:]                  # the probe result is cached
    if stretch:
        enigma.SCALE_STRETCH = 1
    elif hasattr(enigma, 'SCALE_STRETCH'):
        del enigma.SCALE_STRETCH


try:
    older_image('flags', colour=False, stretch=False)
    old = sk._multicontent()
    check('no colour argument is written where the helper is missing',
          old[0] is False and sk.template_color('white') == '')
    check('an older pixmap entry falls back to the flags it does have',
          'BT_SCALE' in old[1])

    older_image('none', colour=False, stretch=False)
    check('a pixmap entry with neither takes no scaling argument',
          sk.template_scale() == '')

    # The template is only built where the image has a List source, which
    # every receiver has and the stub does not.
    had_source = m3ugroups.E2ListSource
    m3ugroups.E2ListSource = type('ListSource', (object,), {})
    try:
        xml = m3ugroups.folder_list_skin(
            'X', 'T', buttons=[('BACK', sk.BTN_RED)], hint='',
            backdrop='bg_m3u.png')
    finally:
        m3ugroups.E2ListSource = had_source
    check('the list becomes a templated listbox on a real receiver',
          'render="Listbox"' in xml and 'TemplatedMultiContent' in xml)
    check('the category list template carries nothing the image refuses',
          'MultiContentTemplateColor' not in xml and
          'scale_flags' not in xml and 'SCALE_STRETCH' not in xml)
    check('and still draws the folder, the name and the count',
          'MultiContentEntryPixmapAlphaTest' in xml and
          xml.count('MultiContentEntryText') == 2)
finally:
    sys.modules['Components.MultiContent'] = current
    enigma.SCALE_STRETCH = 1
    del sk._MULTICONTENT[:]

# ------------------------------- a Python with no audioop and no numpy,
# ---------------------------------- which is every image from 3.13 on
import math                                                    # noqa: E402
from array import array                                        # noqa: E402


def raw(values):
    """array -> bytes, on both Pythons."""
    block = array('h', values)
    return (getattr(block, 'tobytes', None) or block.tostring)()


def samples(data):
    block = array('h')
    (getattr(block, 'frombytes', None) or block.fromstring)(data)
    return block

from PIIP.translate import mixer as mx                          # noqa: E402

had_backend = mx._backend
mx._backend = 'python'
try:
    check('a gain halves the samples',
          samples(mx.scale(raw([1000, -1000]), 0.5)).tolist() == [500, -500])
    check('a sum stops at the ceiling instead of wrapping',
          samples(mx.add(raw([30000]), raw([30000]))).tolist() == [32767])
    check('the level of a flat signal is the signal',
          mx.rms(raw([1000] * 100)) == 1000)
    check('silence has no level', mx.rms(b'') == 0)

    tone = array('h', [int(12000 * math.sin(2 * math.pi * 1000 * n / 24000.0))
                       for n in range(2400)])
    resampler = mx.Resampler()
    out = array('h')
    for start in range(0, len(tone), 480):            # 20 ms at a time
        out.extend(samples(resampler(raw(tone[start:start + 480]))))
    check('24 kHz mono becomes 48 kHz stereo, sample for sample',
          len(out) == len(tone) * 4)
    check('both ears carry the same mono signal',
          out[0::2] == out[1::2])
    left = out[0::2]
    check('the tone keeps its amplitude',
          abs(max(abs(v) for v in left) - 12000) < 200)
    # A click at a chunk join shows up as a step far larger than the tone's.
    check('chunk boundaries carry no click',
          max(abs(left[i + 1] - left[i]) for i in range(len(left) - 1)) < 2000)

    check('the mixer builds without audioop or numpy',
          mx.Mixer(4.0, 6.0) is not None)
finally:
    mx._backend = had_backend

# --------------------------- passthrough asks for no audio backend at all
mx_backend = mx._backend
mx._backend = None                       # the worst case: nothing available
try:
    raised = False
    try:
        mx.Mixer(4.0, 6.0)
    except mx.AudioUnavailable:
        raised = True
    check('a mixer without any backend still refuses loudly', raised)

    from PIIP.translate import engine as engine_mod                # noqa: E402
    cfg = dict(engine_mod.DEFAULTS)
    cfg.update({'url': 'http://example.invalid/x.ts', 'passthrough': True,
                'translate': False})
    built = None
    try:
        built = engine_mod.Engine(cfg)
    except Exception as error:
        print('   passthrough engine raised: %s' % error)
    check('passthrough builds an engine with no audio backend present',
          built is not None and built.mixer is None)
finally:
    mx._backend = mx_backend

# ----------------------------- artwork the image cannot draw, and posters
# ------------------------------- whose address lies about their format
from PIIP.utils import image as image_cache                    # noqa: E402

png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
jpeg = b'\xff\xd8\xff\xe0' + b'0' * 32
webp = b'RIFF' + b'0000' + b'WEBP' + b'0' * 32

check('a PNG is recognised whatever it was called',
      image_cache.sniff(png) == '.png')
check('a JPEG is recognised', image_cache.sniff(jpeg) == '.jpg')
check('a WebP poster is refused rather than cached undrawable',
      image_cache.sniff(webp) is None)
check('an SVG is recognised', image_cache.sniff(b'<svg xmlns=...') == '.svg')
check('rubbish is refused', image_cache.sniff(b'not a picture at all') is None)
check('an address with no usable extension still names a jpg',
      image_cache.suffix('http://x/poster') == '.jpg' and
      image_cache.suffix('http://x/a.webp') == '.jpg')
check('.jpeg and .jpg name the same file',
      image_cache.suffix('http://x/a.jpeg') == '.jpg')
check('a png address keeps its own name',
      image_cache.suffix('http://x/a.png?v=2') == '.png')

# --------------------------- which FFmpeg output graph this image wants
from PIIP.translate import dub                                 # noqa: E402

real_exists, real_id = os.path.exists, dub.image_id


def pretend(paths, distro=''):
    present = set(paths)
    os.path.exists = lambda path: path in present or real_exists(path)
    dub.image_id = lambda: distro


try:
    # The receiver this was found on: dpkg everywhere, plus a stray opkg
    # binary left in /usr/bin, which is not a package database.
    pretend(['/usr/bin/opkg', '/var/lib/dpkg/status'], 'opendreambox')
    check('a DreamOS box with a stray opkg binary is still DreamOS',
          dub.is_oe_alliance() is False)

    pretend(['/var/lib/dpkg/status'], 'opendreambox')
    check('DreamOS is recognised by its own name',
          dub.is_oe_alliance() is False)

    pretend(['/var/lib/opkg/status', '/etc/opkg', '/usr/bin/opkg'], 'openatv')
    check('an OE-Alliance image is recognised by its package database',
          dub.is_oe_alliance() is True)

    pretend(['/etc/opkg'], '')
    check('the opkg configuration alone is enough',
          dub.is_oe_alliance() is True)

    pretend([], '')
    check('nothing recognisable falls back to the proven DreamOS graph',
          dub.is_oe_alliance() is False)
finally:
    os.path.exists = real_exists
    dub.image_id = real_id

print('\n%d checks, %d failed' % (len(RUN), len(FAIL)))
sys.exit(1 if FAIL else 0)
