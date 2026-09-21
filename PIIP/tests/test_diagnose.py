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
"""URL masking, error bodies, and the per-playlist probe."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

from providers import m3u

FAIL = []

PLAYLIST = (b'#EXTM3U\n'
            b'#EXTINF:-1 group-title="News",Channel One\n'
            b'http://x.tv/live/1.ts\n')


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


class Body(object):
    """An error object that carries a response body, like HTTPError does."""

    def __init__(self, code, reason, body):
        self.code = code
        self.reason = reason
        self._body = body

    def read(self):
        return self._body


print('mask_url()')
u = 'http://p.tv:8080/get.php?username=bob&password=s3cret&type=m3u_plus'
masked = m3u.mask_url(u)
check('password hidden', 's3cret' not in masked, masked)
check('username kept, it is not a secret', 'username=bob' in masked)
check('host and path kept', 'p.tv:8080/get.php' in masked)
check('the rest of the query survives', 'type=m3u_plus' in masked)
check('token is hidden too',
      'abc' not in m3u.mask_url('http://x/?token=abc'))
check('api_key is hidden too',
      'zzz' not in m3u.mask_url('http://x/?api_key=zzz'))
check('a url without secrets is unchanged',
      m3u.mask_url('http://x/list.m3u') == 'http://x/list.m3u')
check('result is native str', isinstance(masked, str))

print('')
print('server_says()')
check('plain body returned',
      m3u.server_says(Body(403, 'Forbidden', b'Account expired'))
      == 'Account expired')
check('html is stripped',
      m3u.server_says(Body(403, 'x', b'<html><body>Max connections</body></html>'))
      == 'Max connections',
      m3u.server_says(Body(403, 'x', b'<html><body>Max connections</body></html>')))
check('whitespace collapsed',
      m3u.server_says(Body(403, 'x', b'  too\n\n  many   lines  '))
      == 'too many lines')
check('long bodies truncated',
      m3u.server_says(Body(403, 'x', b'y' * 500)).endswith('...'))
check('empty body gives nothing', m3u.server_says(Body(403, 'x', b'')) == '')
check('object without read() is safe',
      m3u.server_says(ValueError('nope')) == '')


class Exploding(object):
    code = 403
    reason = 'x'

    def read(self):
        raise IOError('connection already closed')


check('a body that cannot be read is safe',
      m3u.server_says(Exploding()) == '')

print('')
print('error_text() with a body')
withbody = m3u.error_text(Body(403, 'Forbidden', b'Subscription expired'))
check('status kept', 'HTTP 403 Forbidden' in withbody, withbody)
check('server explanation included', 'Subscription expired' in withbody)
check('without a body it stays short',
      m3u.error_text(Body(404, 'Not Found', b'')) == 'HTTP 404 Not Found')

print('')
print('probe()')
_original = m3u._download

m3u._download = lambda url, timeout, agent: PLAYLIST
try:
    note = m3u.probe('http://good.tv/a.m3u')
    check('a working playlist reports its channel count',
          note.startswith('OK') and '1 channels' in note, note)
finally:
    m3u._download = _original

seen = []


def refuse_then_serve(url, timeout, agent):
    seen.append(agent)
    if len(seen) == 1:
        raise m3u.HTTPError(url, 403, 'Forbidden', {}, None)
    return PLAYLIST


m3u._download = refuse_then_serve
try:
    note = m3u.probe('http://picky.tv/a.m3u')
    check('a retry is reported so the cause is obvious',
          note.startswith('OK') and 'needed' in note, note)
finally:
    m3u._download = _original


def always_404(url, timeout, agent):
    raise m3u.HTTPError(url, 404, 'Not Found', {}, None)


m3u._download = always_404
try:
    check('404 is reported without retrying',
          m3u.probe('http://gone.tv/a.m3u') == 'HTTP 404 Not Found',
          m3u.probe('http://gone.tv/a.m3u'))
finally:
    m3u._download = _original

m3u._download = lambda url, timeout, agent: b'<html>not a playlist</html>'
try:
    note = m3u.probe('http://wrong.tv/a.m3u')
    check('a page that is not a playlist is called out',
          'no channels' in note, note)
finally:
    m3u._download = _original


def refused(url, timeout, agent):
    raise m3u.URLError('Connection refused')


m3u._download = refused
try:
    note = m3u.probe('http://down.tv/a.m3u')
    check('a connection failure is reported',
          'refused' in note.lower(), note)
finally:
    m3u._download = _original

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
