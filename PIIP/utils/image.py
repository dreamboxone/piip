# -*- coding: utf-8 -*-
"""Artwork URL resolution and bounded disk cache."""

import hashlib
import os
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urljoin
except ImportError:
    from urllib2 import Request, urlopen
    from urlparse import urljoin

from .compat import native

UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3'


def resolve(url, base=''):
    value = native(url or '').strip()
    return urljoin(base.rstrip('/') + '/', value) if value and base else value


def cache_path(url, directory, extension='.jpg'):
    raw = native(url or '').encode('utf-8')
    name = hashlib.md5(raw).hexdigest() + extension
    return os.path.join(directory, name)


def download(url, directory, base='', timeout=20):
    url = resolve(url, base)
    if not url:
        return ''
    if not os.path.isdir(directory):
        os.makedirs(directory)
    ext = os.path.splitext(url.split('?', 1)[0])[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        ext = '.jpg'
    target = cache_path(url, directory, ext)
    if os.path.exists(target) and os.path.getsize(target) > 32:
        return target
    req = Request(url, headers={'User-Agent': UA})
    handle = urlopen(req, timeout=timeout)
    try:
        data = handle.read()
    finally:
        handle.close()
    if len(data) < 32:
        return ''
    temp = target + '.tmp'
    with open(temp, 'wb') as output:
        output.write(data)
    os.rename(temp, target)
    return target


def prune(directory, max_files=500, max_age=30 * 86400):
    try:
        paths = [os.path.join(directory, name) for name in os.listdir(directory)]
    except OSError:
        return 0
    files = [path for path in paths if os.path.isfile(path)]
    files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    removed, now = 0, time.time()
    for index, path in enumerate(files):
        if index >= int(max_files) or now - os.path.getmtime(path) > max_age:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed
