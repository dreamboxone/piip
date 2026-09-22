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

print('\n%d checks, %d failed' % (len(RUN), len(FAIL)))
sys.exit(1 if FAIL else 0)
