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
"""Export channels into Enigma2 bouquets so they can be zapped normally.

Bouquet entries never point at the provider directly. They point at the
local resolver, for two reasons:

  * Stalker links are single-use and expire, so they must be created at the
    moment of zapping, not at the moment of export.
  * It lets a bouquet carry translated audio: the resolver starts the
    translation engine and redirects the box to it.

The map file is what turns a bouquet entry back into something playable.
"""

import hashlib
import json
import os

from .compat import replace_file

ENIGMA_DIR = '/etc/enigma2'
BOUQUETS_TV = os.path.join(ENIGMA_DIR, 'bouquets.tv')
MAP_FILE = os.path.join(ENIGMA_DIR, 'piip_map.json')
PREFIX = 'userbouquet.piip_'

DIRECT = 'direct'
TRANSLATED = 'translated'


def _key(item, provider):
    seed = '%s|%s|%s' % (provider, item.item_id or '', item.url or item.name)
    return hashlib.md5(seed.encode('utf-8')).hexdigest()[:12]


def encode_url(url):
    """Enigma2 service references use ':' as a field separator."""
    return url.replace(':', '%3a')


def service_ref(url, name, service_type=4097):
    return '#SERVICE %d:0:1:0:0:0:0:0:0:0:%s:%s' % (
        int(service_type), encode_url(url), name.replace(':', ' '))


# ------------------------------------------------------------------- map

def load_map(path=MAP_FILE):
    try:
        with open(path, 'r') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def save_map(data, path=MAP_FILE):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as fh:
            json.dump(data, fh)
        replace_file(tmp, path)
        return True
    except (IOError, OSError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def build_map(items, provider, translate, existing=None):
    """{key: entry} for the resolver, keeping entries from other bouquets."""
    data = dict(existing or {})
    keys = []
    for item in items:
        k = _key(item, provider)
        data[k] = {
            'provider': provider,
            'name': item.name,
            'url': item.url or '',
            # Stalker's create_link token; older items kept it in .plot
            'cmd': ((getattr(item, 'cmd', '') or item.plot)
                    if provider == 'stalker' else ''),
            'translate': bool(translate),
            'kind': item.kind,
            'item_id': item.item_id or '',
        }
        keys.append(k)
    return data, keys


# --------------------------------------------------------------- bouquets

def bouquet_filename(slug):
    safe = ''.join(c if c.isalnum() or c in '_-' else '_' for c in slug.lower())
    return '%s%s.tv' % (PREFIX, safe or 'live')


def write_bouquet(filename, title, lines, enigma_dir=ENIGMA_DIR):
    path = os.path.join(enigma_dir, filename)
    body = ['#NAME %s' % title]
    body.extend(lines)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as fh:
            fh.write('\n'.join(body) + '\n')
        replace_file(tmp, path)
        return path
    except (IOError, OSError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


def register(filename, bouquets_tv=BOUQUETS_TV):
    """Add the bouquet to bouquets.tv unless it is already listed."""
    line = ('#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "%s" '
            'ORDER BY bouquet' % filename)
    try:
        with open(bouquets_tv, 'r') as fh:
            content = fh.read()
    except (IOError, OSError):
        content = ''
    if filename in content:
        return False
    try:
        with open(bouquets_tv, 'a') as fh:
            if content and not content.endswith('\n'):
                fh.write('\n')
            fh.write(line + '\n')
        return True
    except (IOError, OSError):
        return False


def unregister(filename, bouquets_tv=BOUQUETS_TV, enigma_dir=ENIGMA_DIR):
    try:
        with open(bouquets_tv, 'r') as fh:
            lines = fh.readlines()
    except (IOError, OSError):
        return False
    kept = [ln for ln in lines if filename not in ln]
    if len(kept) == len(lines):
        removed = False
    else:
        try:
            with open(bouquets_tv, 'w') as fh:
                fh.writelines(kept)
            removed = True
        except (IOError, OSError):
            return False
    try:
        os.remove(os.path.join(enigma_dir, filename))
    except OSError:
        pass
    return removed


def list_exported(enigma_dir=ENIGMA_DIR):
    try:
        return sorted(f for f in os.listdir(enigma_dir)
                      if f.startswith(PREFIX) and f.endswith('.tv'))
    except (IOError, OSError):
        return []


# ----------------------------------------------------------------- export

def export(items, title, provider, resolver_port, translate=False,
           service_type=4097, slug=None, enigma_dir=ENIGMA_DIR,
           bouquets_tv=None, map_file=MAP_FILE):
    """Write one bouquet and the resolver map. Returns a summary dict."""
    if bouquets_tv is None:
        bouquets_tv = os.path.join(enigma_dir, 'bouquets.tv')

    data, keys = build_map(items, provider, translate, load_map(map_file))
    save_map(data, map_file)

    lines = []
    for item, key in zip(items, keys):
        url = 'http://127.0.0.1:%d/play/%s' % (int(resolver_port), key)
        lines.append(service_ref(url, item.name, service_type))
        lines.append('#DESCRIPTION %s' % item.name)

    filename = bouquet_filename(slug or provider)
    path = write_bouquet(filename, title, lines, enigma_dir)
    added = register(filename, bouquets_tv) if path else False
    return {
        'path': path,
        'filename': filename,
        'count': len(items),
        'registered': added,
        'translated': bool(translate),
    }


def reload_services(port=80, timeout=5):
    """Ask Enigma2 to re-read the bouquet files."""
    try:
        from enigma import eDVBDB
        db = eDVBDB.getInstance()
        db.reloadServicelist()
        db.reloadBouquets()
        return 'eDVBDB'
    except Exception:
        pass
    try:
        try:
            from urllib.request import urlopen
        except ImportError:
            from urllib2 import urlopen
        urlopen('http://127.0.0.1:%d/web/servicelistreload?mode=2' % port,
                timeout=timeout).close()
        return 'OpenWebif'
    except Exception as e:
        return 'failed: %s' % e
