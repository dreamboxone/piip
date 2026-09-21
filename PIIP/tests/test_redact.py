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
"""Nothing that unlocks an account may reach a log file."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate import redact

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


# The line the receiver actually wrote before masking existed.
LEAK = ('[ingest] ffmpeg -user_agent Mozilla/5.0 -headers Authorization: Bearer '
        'DDCB596188A989CAB9449D958876B790\r\nReferer: http://45.1.2.3:2095/c/ '
        '-i http://45.1.2.3:2095/play/live.php?mac=00:1A:79:A9:F3:A7&stream=34198'
        '&extension=ts&play_token=YH6LpSB4ol -map 0:v:0')
out = redact.text(LEAK)
for secret in ('DDCB596188A989CAB9449D958876B790', 'A9:F3:A7', 'YH6LpSB4ol'):
    check('%s removed' % secret[:8], secret not in out, out)
check('stream id kept for diagnosis', 'stream=34198' in out)
check('portal host kept for diagnosis', '45.1.2.3:2095' in out)
check('mac parameter masked', 'mac=***' in out, out)
check('a bare MAC keeps only its vendor prefix', redact.text('box 00:1A:79:A9:F3:A7 up') == 'box 00:1A:79:**:**:** up')

x = redact.text('http://panel.tv:8080/live/alice/s3cret/123.ts')
check('xtream path credentials masked',
      'alice' not in x and 's3cret' not in x and x.endswith('/123.ts'), x)
t = redact.text('http://p/timeshift/bob/pw/60/2026-09-14:10-00/5.ts')
check('timeshift credentials masked', 'bob' not in t and '/pw/' not in t, t)
q = redact.text('http://p/get.php?username=u1&password=p%402&type=m3u_plus')
check('query credentials masked', 'u1' not in q and 'p%402' not in q
      and 'type=m3u_plus' in q, q)
check('url-encoded cookie mac masked',
      'B5%3A4C%3AB3' not in redact.text('Cookie=mac%3D00%3A1A%3A79%3AB5%3A4C%3AB3'))
check('gemini key masked', 'AIzaSyD' not in
      redact.text('key AIzaSyD-abcdefghijklmnopqrstuvwxyz012345'))
check('ordinary text untouched',
      redact.text('[probe] audio=yes rc=0 monkey=1') == '[probe] audio=yes rc=0 monkey=1')
check('non-strings are safe', redact.text(12345) == '12345')

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
