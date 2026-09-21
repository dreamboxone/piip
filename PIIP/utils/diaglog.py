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
"""Where playback diagnostics are written, and how.

Every translated playback gets its own folder on the hard disk, so the
evidence of a failed test survives a lost SSH session, an Enigma2 restart
and a reboot (/tmp is a RAM disk on these boxes). The folder collects

    engine.jsonl   one line per second from the translation engine
    engine.log     the engine's own log (ffmpeg, Gemini, pipes)
    player.jsonl   one line per second from Enigma2's decoder
    events.log     Enigma2 service events (start, EOF, buffering, errors)
    system.jsonl   CPU, memory and network, when a watch is running
    frames/        small video-plane grabs, when a watch is running
    output.ts      the exact stream handed to the decoder, when tapping
    report.txt     the analysis (translate/diagreport.py)

Standalone: imported by the engine process and the command-line tool as
well as by the plugin, so nothing here may import Enigma2.
"""

import json
import os
import shutil
import threading
import time

ROOTS = ('/media/hdd/piip_diag', '/media/usb/piip_diag', '/tmp/piip_diag')
# A running watch (translate/diag.py start) announces itself here. The
# marker is in /tmp on purpose: it must not outlive the boot it belongs to.
MARKER = '/tmp/piip_diag.active'
KEEP = 25


def _writable(folder):
    try:
        if not os.path.isdir(folder):
            parent = os.path.dirname(folder)
            if not os.path.isdir(parent):
                return False
            os.makedirs(folder)
        probe = os.path.join(folder, '.probe')
        with open(probe, 'w') as fh:
            fh.write('ok')
        os.remove(probe)
        return True
    except Exception:
        return False


def root():
    for folder in ROOTS:
        if _writable(folder):
            return folder
    return '/tmp'


def active_watch():
    """The running watch's settings, or None."""
    try:
        with open(MARKER) as fh:
            data = json.load(fh)
        if data.get('until') and time.time() > float(data['until']) + 120:
            return None
        if data.get('dir') and os.path.isdir(data['dir']):
            return data
    except Exception:
        pass
    return None


def new_dir(kind='play', label=''):
    """A fresh session folder; the oldest ones are pruned."""
    watch = active_watch()
    if watch:
        # Everything played during a watch lands in the watch's folder, so
        # one report covers the whole test.
        return watch['dir']
    base = root()
    stamp = time.strftime('%Y%m%d-%H%M%S')
    safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_'
                   for ch in (label or ''))[:32]
    path = os.path.join(base, '%s-%s%s' % (kind, stamp,
                                           '-' + safe if safe else ''))
    first, n = path, 1
    while os.path.exists(path):
        n += 1
        path = '%s.%d' % (first, n)
    try:
        os.makedirs(path)
    except Exception:
        return None
    prune(base)
    return path


def prune(base, keep=KEEP):
    try:
        names = sorted(n for n in os.listdir(base)
                       if os.path.isdir(os.path.join(base, n)))
    except Exception:
        return
    watch = active_watch() or {}
    for name in names[:-keep] if len(names) > keep else []:
        path = os.path.join(base, name)
        if path != watch.get('dir'):
            shutil.rmtree(path, ignore_errors=True)


def latest(kind=None):
    base = root()
    try:
        names = sorted(n for n in os.listdir(base)
                       if os.path.isdir(os.path.join(base, n)) and
                       (kind is None or n.startswith(kind + '-')))
    except Exception:
        return None
    return os.path.join(base, names[-1]) if names else None


class JsonLines(object):
    """Append-only, line-buffered JSON lines; never raises."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.fh = None
        if path:
            try:
                self.fh = open(path, 'a', 1)
            except Exception:
                self.fh = None

    def write(self, record):
        if self.fh is None:
            return
        try:
            line = json.dumps(record, sort_keys=True) + '\n'
        except Exception:
            return
        with self._lock:
            try:
                self.fh.write(line)
            except Exception:
                pass

    def close(self):
        with self._lock:
            try:
                if self.fh is not None:
                    self.fh.close()
            except Exception:
                pass
            self.fh = None


def append_text(path, line):
    try:
        with open(path, 'a') as fh:
            fh.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), line))
    except Exception:
        pass
