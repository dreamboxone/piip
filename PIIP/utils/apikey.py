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
"""Locate the Gemini API key.

The key is looked up in several places so that it can be dropped in as a
plain file rather than typed on a remote control. First hit wins:

  1. the GEMINI_API_KEY environment variable
  2. /root/apikey.txt or /home/root/apikey.txt (root's home: DreamOS or OE)
  3. /etc/enigma2/piip_apikey.txt    (survives plugin reinstalls)
  4. apikey.txt next to the plugin
  5. apikey.txt one level above the plugin
  6. whatever was typed into the plugin settings

The file may contain comment lines starting with '#'; the first non-empty,
non-comment line is used. Leading/trailing whitespace and a UTF-8 BOM are
stripped, because copy-pasting a key into a file on Windows adds both.
"""

import os

from .compat import in_root_homes, native

ENV_VAR = 'GEMINI_API_KEY'

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEARCH_PATHS = list(in_root_homes('apikey.txt')) + [
    '/etc/enigma2/piip_apikey.txt',
    os.path.join(_HERE, 'apikey.txt'),
    os.path.join(os.path.dirname(_HERE), 'apikey.txt'),
]


def _parse(text):
    """First meaningful line of a key file, or ''."""
    if text.startswith(u'﻿'):
        text = text[1:]
    for line in text.splitlines():
        line = line.strip().strip('"').strip("'")
        if line and not line.startswith('#'):
            return line
    return ''


def read_file(path):
    try:
        with open(path, 'rb') as fh:
            return native(_parse(fh.read().decode('utf-8', 'replace')))
    except (IOError, OSError):
        return ''


def find(configured=''):
    """Return (key, source) with source describing where it came from."""
    env = os.environ.get(ENV_VAR, '').strip()
    if env:
        return env, 'environment (%s)' % ENV_VAR

    for path in SEARCH_PATHS:
        key = read_file(path)
        if key:
            return key, path

    configured = (configured or '').strip()
    if configured:
        return configured, 'plugin settings'
    return '', ''


def describe(configured=''):
    """One line for the UI: where the key came from, without revealing it."""
    key, source = find(configured)
    if not key:
        return 'no API key found (looked in %s)' % ', '.join(SEARCH_PATHS)
    return 'key from %s (%s, %d chars)' % (source, mask(key), len(key))


def mask(key):
    if not key:
        return ''
    if len(key) <= 8:
        return '*' * len(key)
    return '%s...%s' % (key[:4], key[-4:])
