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
"""Playlist download: error reporting and the player-agent retry.

"HTTPError" on its own tells a user nothing. What matters is whether the
URL is wrong (404), the subscription is refused (401/403) or the provider
is throttling (429), so the status has to survive into the message.
"""

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


def HttpErr(code, reason):
    """A real urllib HTTPError, so fetch() catches it the way it will live."""
    return m3u.HTTPError('http://test/', code, reason, {}, None)


class UrlErr(Exception):
    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


print('error_text()')
check('status and reason reported',
      m3u.error_text(HttpErr(403, 'Forbidden')) == 'HTTP 403 Forbidden',
      m3u.error_text(HttpErr(403, 'Forbidden')))
check('status alone still reported',
      m3u.error_text(HttpErr(404, '')) == 'HTTP 404',
      m3u.error_text(HttpErr(404, '')))
check('401 is distinguishable from 404',
      m3u.error_text(HttpErr(401, 'Unauthorized'))
      != m3u.error_text(HttpErr(404, 'Not Found')))
check('connection failures name the reason',
      'timed out' in m3u.error_text(UrlErr('timed out')),
      m3u.error_text(UrlErr('timed out')))
check('anything else still says something useful',
      'ValueError' in m3u.error_text(ValueError('bad')),
      m3u.error_text(ValueError('bad')))
check('the message is never empty',
      bool(m3u.error_text(Exception())))

print('')
print('player-agent retry')
_original = m3u._download
calls = []


def refuse_twice(url, timeout, agent):
    calls.append(agent)
    if len(calls) < 3:
        raise HttpErr(403, 'Forbidden')
    return PLAYLIST


m3u._download = refuse_twice
try:
    got = m3u.fetch('http://blocked.tv/list.m3u')
    check('a 403 is retried until one agent works', len(got) == 1, str(len(got)))
    check('the configured agent is tried first', calls[0] == m3u.UA, calls[0])
    check('a player agent is among the retries',
          any('VLC' in a for a in calls), str(calls[1:]))
    check('each agent is only tried once', len(calls) == len(set(calls)))
finally:
    m3u._download = _original

for status in (401, 429):
    tried = []

    def refuse_all(url, timeout, agent, _s=status, _t=tried):
        _t.append(agent)
        raise HttpErr(_s, 'refused')

    m3u._download = refuse_all
    try:
        raised = ''
        try:
            m3u.fetch('http://blocked.tv/list.m3u')
        except Exception as exc:
            raised = m3u.error_text(exc)
        check('%d retries every agent' % status,
              len(tried) == len(set(m3u.PLAYER_AGENTS) | set([m3u.UA])),
              str(len(tried)))
        check('%d finally propagates with its status' % status,
              str(status) in raised, raised)
    finally:
        m3u._download = _original

tried404 = []


def not_found(url, timeout, agent):
    tried404.append(agent)
    raise HttpErr(404, 'Not Found')


m3u._download = not_found
try:
    raised = ''
    try:
        m3u.fetch('http://gone.tv/list.m3u')
    except Exception as exc:
        raised = m3u.error_text(exc)
    check('a 404 is not retried', len(tried404) == 1, str(len(tried404)))
    check('a 404 keeps its status', raised == 'HTTP 404 Not Found', raised)
finally:
    m3u._download = _original

first_try = []


def works_immediately(url, timeout, agent):
    first_try.append(agent)
    return PLAYLIST


m3u._download = works_immediately
try:
    got = m3u.fetch('http://fine.tv/list.m3u')
    check('a working playlist needs one request', len(first_try) == 1)
    check('and parses normally', len(got) == 1 and got[0].name == 'Channel One')
finally:
    m3u._download = _original

print('')
print('errors reach the user through load_all')
import tempfile
import shutil

tmp = tempfile.mkdtemp(prefix='farsihttp')
listfile = os.path.join(tmp, 'm3u.txt')
with open(listfile, 'wb') as fh:
    fh.write(b'Blocked = http://blocked.tv/a.m3u\n')


def always_403(url, timeout, agent):
    raise HttpErr(403, 'Forbidden')


m3u._download = always_403
try:
    items, errors = m3u.load_all('', paths=[listfile])
    check('nothing loads', items == [])
    check('the status reaches the message',
          errors and 'HTTP 403' in errors[0], str(errors))
    check('the playlist name is in the message',
          errors and 'Blocked' in errors[0], str(errors))
finally:
    m3u._download = _original
    shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
