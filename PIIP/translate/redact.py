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
"""Strip account secrets out of anything written to a log.

The logs live in /tmp, get pasted into chats and attached to bug reports,
and the lines worth logging - an ffmpeg command, a stream URL - carry the
MAC, play token, bearer token or Xtream password that unlocks the account.

Standalone on purpose: the engine runs as its own process and imports
this without the plugin package around it.
"""

import re

MASK = '***'

# key=value in a query string, a cookie or a header block.
_PARAMS = re.compile(
    r'(?i)\b(mac|play_token|token|password|passwd|pass|pwd|username|user|'
    r'api_key|apikey|key|auth|signature|sn|device_id2?)(=|%3D)([^&\s;"\'|#]+)')
# Authorization: Bearer XXXX
_BEARER = re.compile(r'(?i)\b(Bearer)(\s+|%20)[A-Za-z0-9._~+/=-]+')
# A MAC written with colons or their URL-encoding; the vendor prefix stays
# so a log still shows which kind of box it was.
_MAC = re.compile(r'(?i)\b([0-9a-f]{2}(?::|%3A)[0-9a-f]{2}(?::|%3A)[0-9a-f]{2})'
                  r'((?::|%3A)[0-9a-f]{2}){3}\b')
# Xtream puts the account in the path: /live/USER/PASS/123.ts
_XTREAM_PATH = re.compile(r'(?i)(/(?:live|movie|series|timeshift)/)'
                          r'([^/\s]+)/([^/\s]+)/')
# Google API keys (the Gemini key).
_GOOGLE_KEY = re.compile(r'AIza[0-9A-Za-z_-]{20,}')


def text(value):
    """`value` as a string with every recognised secret replaced."""
    try:
        line = value if isinstance(value, str) else str(value)
    except Exception:
        return MASK
    line = _PARAMS.sub(lambda m: m.group(1) + m.group(2) + MASK, line)
    line = _BEARER.sub(lambda m: m.group(1) + m.group(2) + MASK, line)
    line = _MAC.sub(lambda m: m.group(1) + ':**:**:**', line)
    line = _XTREAM_PATH.sub(lambda m: m.group(1) + MASK + '/' + MASK + '/',
                            line)
    line = _GOOGLE_KEY.sub('AIza' + MASK, line)
    return line
