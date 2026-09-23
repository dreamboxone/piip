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


# Enigma2 refuses a picture by its extension before it looks inside, and
# it has no WebP loader at all: "Neither .png nor .jpg nor .svg, please fix
# file extension".
DRAWABLE = ('.png', '.jpg', '.svg')


def sniff(data):
    """The extension for what these bytes actually are, or None if useless."""
    head = data[:16]
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if head.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return None                                  # nothing can draw it
    stripped = head.lstrip()
    if stripped[:4] == b'<svg' or stripped[:5] == b'<?xml':
        return '.svg'
    return None


def suffix(url):
    """The extension a cached copy of this address would have."""
    ext = os.path.splitext(url.split('?', 1)[0])[1].lower()
    if ext == '.jpeg':
        return '.jpg'
    return ext if ext in DRAWABLE else '.jpg'


def download(url, directory, base='', timeout=20):
    url = resolve(url, base)
    if not url:
        return ''
    if not os.path.isdir(directory):
        os.makedirs(directory)
    target = cache_path(url, directory, suffix(url))
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
    # What it really is, not what the address claimed: providers serve PNG
    # from .jpg addresses, and WebP from both. Enigma2 draws neither WebP
    # nor anything whose extension disagrees with its content.
    kind = sniff(data)
    if kind is None:
        return ''
    target = cache_path(url, directory, kind)
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
