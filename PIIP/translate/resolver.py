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
"""Local resolver behind every bouquet entry.

Enigma2 zaps to http://127.0.0.1:<port>/play/<key>. This server looks the
key up in the bouquet map and answers with a redirect:

  * Stalker    -> create_link is called now, because the portal's links are
                  single-use and expire within minutes.
  * translated -> the translation engine is started for that URL and the box
                  is redirected to it, so an ordinary zap gets Persian audio.
  * otherwise  -> straight redirect to the provider URL.

It only ever issues redirects, so no video passes through this process and
the Enigma2 main loop stays free.
"""

import json
import threading
import time

from . import redact

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:                                    # Python 2 images
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn

LOG = '/tmp/piip_resolver.log'

_state = {
    'server': None,
    'thread': None,
    'engine': None,
    'stalker': None,
    'stalker_at': 0.0,
    'last_key': None,
}
_lock = threading.Lock()

# Config injected by plugin.py so this module stays importable off-box.
_ctx = {
    'map_file': '/etc/enigma2/piip_map.json',
    'port': 8903,
    'engine_config': None,      # callable(url, item, start_at) -> dict
    'stalker_factory': None,    # callable() -> Stalker
}

STALKER_TTL = 600               # re-handshake after this many seconds


def log(*parts):
    try:
        with open(LOG, 'a') as fh:
            fh.write('%s %s\n' % (time.strftime('%H:%M:%S'),
                                  redact.text(' '.join(str(p) for p in parts))))
    except Exception:
        pass


def configure(**kw):
    _ctx.update(kw)


def _load_map():
    try:
        with open(_ctx['map_file'], 'r') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _stalker():
    """One portal session, re-handshaken when it goes stale."""
    factory = _ctx.get('stalker_factory')
    if factory is None:
        raise RuntimeError('no Stalker configured')
    now = time.time()
    s = _state['stalker']
    if s is not None and now - _state['stalker_at'] < STALKER_TTL:
        return s
    s = factory()
    s.connect()
    _state['stalker'] = s
    _state['stalker_at'] = now
    return s


def resolve_key(key):
    """-> (url, translate) for a bouquet key."""
    entry = _load_map().get(key)
    if not entry:
        raise KeyError('unknown key %s' % key)

    url = entry.get('url') or ''
    if entry.get('provider') == 'stalker':
        cmd = entry.get('cmd') or ''
        try:
            url = _stalker().create_link(cmd, series=0)
        except Exception:
            # A stale token is the usual cause; drop it and try once more.
            _state['stalker'] = None
            url = _stalker().create_link(cmd, series=0)
    if not url:
        raise KeyError('no url for %s' % key)
    return url, bool(entry.get('translate')), entry


def _start_engine(url, entry):
    from .control import EngineHandle
    maker = _ctx.get('engine_config')
    if maker is None:
        raise RuntimeError('no engine config factory')
    cfg = maker(url, None, 0.0)
    with _lock:
        old = _state['engine']
        if old is not None:
            old.stop()
        handle = EngineHandle(cfg)
        _state['engine'] = handle
    if not handle.start():
        raise RuntimeError('engine failed to start')
    return handle.url


def stop_engine():
    with _lock:
        h = _state['engine']
        _state['engine'] = None
    if h is not None:
        h.stop()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, fmt, *args):
        pass                                    # never touch stderr in enigma2

    def _redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, message):
        body = message.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split('?', 1)[0]

        if path == '/status':
            eng = _state['engine']
            return self._json({
                'ok': True,
                'entries': len(_load_map()),
                'engine_running': bool(eng and eng.alive()),
                'last_key': _state['last_key'],
            })

        if path == '/stop':
            stop_engine()
            return self._json({'ok': True})

        if not path.startswith('/play/'):
            return self._error(404, 'not found')

        key = path[len('/play/'):].strip('/')
        try:
            url, translate, entry = resolve_key(key)
        except KeyError as e:
            log('[play] unknown key:', e)
            return self._error(404, 'unknown channel')
        except Exception as e:
            log('[play] resolve failed:', e)
            return self._error(502, 'could not resolve channel: %s' % e)

        _state['last_key'] = key
        if not translate:
            log('[play]', key, '-> direct')
            return self._redirect(url)

        try:
            local = _start_engine(url, entry)
        except Exception as e:
            log('[play] engine failed, falling back to direct:', e)
            return self._redirect(url)
        log('[play]', key, '-> translated')
        return self._redirect(local)


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(port=None):
    """Start the resolver once; safe to call repeatedly."""
    with _lock:
        if _state['server'] is not None:
            return _state['port'] if 'port' in _state else _ctx['port']
        port = int(port or _ctx['port'])
        srv = _Server(('127.0.0.1', port), _Handler)
        t = threading.Thread(target=srv.serve_forever, name='farsi-resolver')
        t.daemon = True
        t.start()
        _state['server'] = srv
        _state['thread'] = t
    log('[resolver] listening on 127.0.0.1:%d' % port)
    return port


def stop():
    stop_engine()
    with _lock:
        srv = _state['server']
        _state['server'] = None
        _state['thread'] = None
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass


def running():
    return _state['server'] is not None
