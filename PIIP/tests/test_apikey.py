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
"""Tests for API key discovery."""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import apikey

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


tmp = tempfile.mkdtemp(prefix='farsikey')


def write(name, text, encoding='utf-8'):
    p = os.path.join(tmp, name)
    with open(p, 'wb') as fh:
        fh.write(text.encode(encoding))
    return p


KEY = 'AIzaSyDUMMYKEYFORTESTINGONLY1234567890x'

print('file parsing')
check('plain key', apikey.read_file(write('a.txt', KEY)) == KEY)
check('trailing newline stripped',
      apikey.read_file(write('b.txt', KEY + '\n')) == KEY)
check('windows line ending stripped',
      apikey.read_file(write('c.txt', KEY + '\r\n')) == KEY)
check('surrounding whitespace stripped',
      apikey.read_file(write('d.txt', '   ' + KEY + '  \n')) == KEY)
check('comments skipped',
      apikey.read_file(write('e.txt', '# put key below\n\n' + KEY + '\n')) == KEY)
check('double quotes stripped',
      apikey.read_file(write('f.txt', '"%s"' % KEY)) == KEY)
check('single quotes stripped',
      apikey.read_file(write('g.txt', "'%s'" % KEY)) == KEY)
check('utf-8 BOM stripped',
      apikey.read_file(write('h.txt', u'﻿' + KEY)) == KEY)
check('only the first real line is used',
      apikey.read_file(write('i.txt', KEY + '\nsecond-line\n')) == KEY)
check('comment-only file yields nothing',
      apikey.read_file(write('j.txt', '# nothing here\n#\n\n')) == '')
check('empty file yields nothing', apikey.read_file(write('k.txt', '')) == '')
check('missing file yields nothing',
      apikey.read_file(os.path.join(tmp, 'nope.txt')) == '')

print('\nlookup order')
saved_env = os.environ.pop(apikey.ENV_VAR, None)
saved_paths = list(apikey.SEARCH_PATHS)

apikey.SEARCH_PATHS = [os.path.join(tmp, 'nope.txt')]
key, src = apikey.find('')
check('nothing configured, nothing found', key == '' and src == '')

key, src = apikey.find('  typed-in-settings  ')
check('settings used as last resort', key == 'typed-in-settings', key)
check('settings reported as the source', src == 'plugin settings', src)

first = write('first.txt', 'from-file')
apikey.SEARCH_PATHS = [first]
key, src = apikey.find('typed-in-settings')
check('file beats the settings field', key == 'from-file', key)
check('source names the file', src == first)

apikey.SEARCH_PATHS = [os.path.join(tmp, 'nope.txt'), first]
key, src = apikey.find('')
check('missing paths are skipped', key == 'from-file')

os.environ[apikey.ENV_VAR] = 'from-env'
key, src = apikey.find('typed-in-settings')
check('environment wins over everything', key == 'from-env', key)
check('source names the env var', apikey.ENV_VAR in src, src)
os.environ.pop(apikey.ENV_VAR, None)

print('\nmasking (keys must never be printed in full)')
check('long key masked', apikey.mask(KEY) == 'AIza...890x', apikey.mask(KEY))
check('short key fully hidden', apikey.mask('abc') == '***')
check('empty key masks to empty', apikey.mask('') == '')

apikey.SEARCH_PATHS = [first]
d = apikey.describe('')
check('describe reveals source, not the key',
      'from-file' not in d and first in d, d)
apikey.SEARCH_PATHS = [os.path.join(tmp, 'nope.txt')]
check('describe says when nothing was found',
      'no API key' in apikey.describe(''), apikey.describe(''))

print('\nthe shipped template')
apikey.SEARCH_PATHS = saved_paths
template = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'apikey.txt')
if os.path.exists(template):
    check('template file is readable', True, template)
    check('template is all comments, so it reads as no key',
          apikey.read_file(template) == '')
    check('template mentions where to get a key',
          # open() has no encoding argument on Python 2.
          'aistudio.google.com' in
          io.open(template, encoding='utf-8').read())
else:
    # Only present in the source tree; the package does not ship it.
    print('  SKIP  template not present here (%s)' % template)

if saved_env is not None:
    os.environ[apikey.ENV_VAR] = saved_env
shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
