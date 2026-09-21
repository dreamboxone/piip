# -*- coding: utf-8 -*-
"""Lightweight PIIP web configuration and status server."""

import json
import threading

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from urllib.parse import parse_qs
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn
    from urlparse import parse_qs

from . import servers
from .portalconf import fetch

_state = {'server': None, 'thread': None, 'port': 0}
_lock = threading.RLock()
_ctx = {'config': None, 'free_url': ''}

HTML = '''<!doctype html><html><head><meta charset="utf-8"><title>PIIP Web Config</title>
<style>body{background:#091018;color:#eee;font:16px sans-serif;max-width:960px;margin:30px auto}
h1{color:#20d8ef}button,input,select{padding:9px;margin:4px;background:#162433;color:#fff;border:1px solid #278ca0}
table{width:100%%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #263746;text-align:left}
.nav a{display:inline-block;padding:10px 14px;margin:3px;color:#fff;background:#173047;text-decoration:none;border-radius:5px}</style></head>
<body><h1>PIIP Web Config</h1><div class="nav"><a href="add.html">Add Server</a><a href="edit.html">Edit / Remove Servers</a><a href="free_list.html">Free Portals</a><a href="settings.html">Settings</a></div><p id="status">Loading…</p><table><thead><tr><th>Name</th><th>Type</th><th>Address</th></tr></thead><tbody id="rows"></tbody></table>
<script>fetch('/api/status').then(x=>x.json()).then(x=>status.textContent='Active: '+(x.active||'none')+' | Source: '+x.source);
fetch('/api/servers').then(x=>x.json()).then(g=>{let xs=[];Object.keys(g).forEach(k=>g[k].forEach(x=>xs.push(x)));rows.innerHTML=xs.map(x=>'<tr><td>'+x.name+'</td><td>'+x.type+'</td><td>'+(x.host||x.url||x.portal||'')+'</td></tr>').join('')});</script></body></html>'''


def configure(config=None, free_url=''):
    _ctx['config'], _ctx['free_url'] = config, free_url


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        return

    def _send(self, status, payload, content_type='application/json'):
        if not isinstance(payload, bytes):
            payload = payload.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, value, status=200):
        self._send(status, json.dumps(value, sort_keys=True))

    def _body(self):
        try:
            size = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(size).decode('utf-8')) if size else {}
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html', '/add.html', '/edit.html',
                    '/free_list.html', '/settings.html'):
            return self._send(200, HTML, 'text/html')
        if path == '/api/status':
            c = _ctx['config']
            return self._json({'source': c.source.value if c else '',
                               'active': c.active_server.value if c else '',
                               'version': 'PIIP'})
        if path == '/api/servers':
            # Hybrid WebIF's edit page consumes lists grouped by provider.
            data = dict((kind, servers.load(kind)) for kind in servers.TYPES)
            return self._json(data)
        if path in ('/api/free-list', '/api/free_list'):
            items, error = fetch(_ctx['free_url'])
            return self._json({'success': not bool(error), 'servers': items,
                               'items': items, 'error': error},
                              502 if error else 200)
        if path == '/api/settings':
            c = _ctx['config']
            if not c:
                return self._json({'error': 'configuration unavailable'}, 503)
            return self._json({
                'opensubtitles_api_key': c.opensubtitles_key.value,
                'subdl_api_key': c.subdl_key.value,
                'download_dir': c.download_dir.value,
                'picon_cache_dir': c.picon_cache_dir.value,
                'sub_pos': c.sub_position.value,
                'sub_size': c.sub_size.value,
                'sub_color': c.sub_color.value,
                'vod_streamtype': c.vod_streamtype.value,
                'show_adult': bool(c.show_adult.value),
                'poster_count': str(c.poster_count.value),
                'skin_style': c.skin_style.value,
                'translation_enabled': bool(c.translate.value),
                'translation_language': c.language.value,
                'translation_delay': int(c.delay.value),
                'original_volume': int(c.vol_original.value),
                'translation_volume': int(c.vol_translated.value),
            })
        return self._json({'error': 'not found'}, 404)

    def do_POST(self):
        path, body = self.path.split('?', 1)[0], self._body()
        if path in ('/api/server', '/api/save'):
            kind = body.get('type', '')
            if kind not in servers.TYPES:
                return self._json({'error': 'invalid type'}, 400)
            # Hybrid identifies edits by list index. Preserve the old name so
            # renaming replaces, rather than duplicates, that entry.
            previous = None
            if 'index' in body:
                old = servers.load(kind)
                try:
                    previous = old[int(body['index'])]
                except (IndexError, TypeError, ValueError):
                    return self._json({'success': False,
                                       'error': 'invalid server index'}, 400)
            error = servers.upsert(kind, body, replaces=previous)
            return self._json({'ok': not bool(error), 'success': not bool(error),
                               'error': error}, 500 if error else 200)
        if path == '/api/activate':
            kind, name = body.get('type', ''), body.get('name', '')
            item = next((x for x in servers.load(kind) if x.get('name') == name), None)
            if not item:
                return self._json({'error': 'server not found'}, 404)
            servers.activate(item)
            return self._json({'ok': True})
        if path == '/api/delete':
            kind = body.get('type', '')
            name = body.get('name', '')
            target = None
            if not name and 'index' in body and kind in servers.TYPES:
                try:
                    target = servers.load(kind)[int(body['index'])]
                except (IndexError, TypeError, ValueError):
                    return self._json({'success': False,
                                       'error': 'invalid server index'}, 400)
            error = servers.delete(kind, name, entry=target)
            return self._json({'ok': not bool(error), 'success': not bool(error),
                               'error': error}, 500 if error else 200)
        if path == '/api/settings':
            c = _ctx['config']
            if not c:
                return self._json({'error': 'configuration unavailable'}, 503)
            fields = {
                'opensubtitles_api_key': 'opensubtitles_key',
                'subdl_api_key': 'subdl_key', 'download_dir': 'download_dir',
                'picon_cache_dir': 'picon_cache_dir', 'sub_pos': 'sub_position',
                'sub_size': 'sub_size', 'sub_color': 'sub_color',
                'vod_streamtype': 'vod_streamtype', 'show_adult': 'show_adult',
                'poster_count': 'poster_count', 'skin_style': 'skin_style',
                'translation_enabled': 'translate',
                'translation_language': 'language', 'translation_delay': 'delay',
                'original_volume': 'vol_original',
                'translation_volume': 'vol_translated',
            }
            try:
                for incoming, attr in fields.items():
                    if incoming in body:
                        element = getattr(c, attr)
                        element.value = body[incoming]
                        element.save()
                from Components.config import configfile
                configfile.save()
                return self._json({'success': True})
            except Exception as exc:
                return self._json({'success': False, 'error': str(exc)}, 500)
        if path == '/api/check_server':
            try:
                from ..providers.stalker import Stalker
                Stalker(body.get('portal', ''), body.get('mac', '')).connect()
                return self._json({'success': True, 'status': 'WORKING'})
            except Exception as exc:
                return self._json({'success': False, 'status': 'DEAD',
                                   'error': str(exc)}, 502)
        return self._json({'error': 'not found'}, 404)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(port=8914, host='0.0.0.0'):
    with _lock:
        if _state['server'] is not None:
            return _state['port']
        server = Server((host, int(port)), Handler)
        thread = threading.Thread(target=server.serve_forever, name='piip-webif')
        thread.daemon = True
        thread.start()
        _state.update(server=server, thread=thread, port=int(port))
    return int(port)


def stop():
    with _lock:
        server = _state['server']
        _state.update(server=None, thread=None, port=0)
    if server:
        server.shutdown()
        server.server_close()
