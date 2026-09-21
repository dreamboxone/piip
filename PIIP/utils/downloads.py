# -*- coding: utf-8 -*-
"""Persistent, receiver-friendly download queue."""

import json
import os
import re
import signal
import subprocess
import time

from .compat import native

STORE = '/etc/enigma2/piip_downloads.json'
_BAD = re.compile(r'[^A-Za-z0-9._() -]+')


def load():
    try:
        data = json.load(open(STORE, 'r'))
        return data if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def save(items):
    folder = os.path.dirname(STORE)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    temp = STORE + '.tmp'
    with open(temp, 'w') as handle:
        json.dump(list(items), handle, indent=2, sort_keys=True)
    try:
        os.rename(temp, STORE)
    except OSError:
        if os.path.exists(STORE):
            os.remove(STORE)
        os.rename(temp, STORE)


def filename(name, url):
    title = _BAD.sub('_', native(name or 'download')).strip(' ._') or 'download'
    path = native(url or '').split('?', 1)[0]
    ext = os.path.splitext(path)[1].lower()
    if not ext or len(ext) > 6 or ext == '.m3u8':
        ext = '.ts'
    return title[:120] + ext


def enqueue(url, name, directory):
    directory = native(directory or '/media/hdd/movie/').rstrip('/')
    if not os.path.isdir(directory):
        os.makedirs(directory)
    target = os.path.join(directory, filename(name, url))
    items = load()
    entry = {'id': str(int(time.time() * 1000)), 'name': native(name),
             'url': native(url), 'path': target, 'status': 'queued',
             'pid': 0, 'created': int(time.time()), 'error': ''}
    items.append(entry)
    save(items)
    return entry


def _alive(pid):
    try:
        pid = int(pid)
        # POSIX pid 0 addresses the caller's entire process group. It is the
        # sentinel stored for queued/paused jobs, never a real download PID.
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def refresh(items=None):
    items = load() if items is None else items
    changed = False
    for item in items:
        if item.get('status') == 'downloading' and not _alive(item.get('pid')):
            item['status'] = 'complete' if os.path.exists(item.get('path', '')) else 'failed'
            item['pid'] = 0
            changed = True
        try:
            item['bytes'] = os.path.getsize(item.get('path', ''))
        except OSError:
            item['bytes'] = 0
    if changed:
        save(items)
    return items


def start(entry_id):
    items = refresh()
    chosen = next((x for x in items if x.get('id') == entry_id), None)
    if not chosen:
        return False
    log = open(chosen['path'] + '.log', 'ab')
    proc = subprocess.Popen(['curl', '-L', '--fail', '--retry', '3', '-C', '-',
                             '-A', 'Mozilla/5.0', '-o', chosen['path'], chosen['url']],
                            stdout=log, stderr=log, close_fds=True)
    chosen['pid'] = proc.pid
    chosen['status'] = 'downloading'
    chosen['error'] = ''
    save(items)
    return True


def cancel(entry_id):
    items = load()
    for item in items:
        if item.get('id') == entry_id:
            pid = item.get('pid')
            if _alive(pid):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
            item['pid'], item['status'] = 0, 'paused'
    save(items)


def remove(entry_id, delete_file=False):
    items = load()
    for item in items:
        if item.get('id') == entry_id:
            cancel(entry_id)
            if delete_file:
                for path in (item.get('path', ''), item.get('path', '') + '.log'):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
    save([x for x in items if x.get('id') != entry_id])


def clear_finished():
    """Remove completed/failed queue records while retaining downloaded files."""
    items = refresh()
    kept = [x for x in items if x.get('status') not in ('complete', 'failed')]
    save(kept)
    return len(items) - len(kept)
