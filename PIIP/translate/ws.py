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
"""Minimal RFC 6455 WebSocket client over TLS.

Deliberately dependency-free: Enigma2 images vary wildly in what Python
packages they ship, and the receiver may have no working pip. Everything
here uses only the standard library.

Only what the Gemini Live API needs is implemented: a client handshake,
masked text/binary frames, continuation frames, ping/pong and close.
"""

import base64
import errno
import json
import os
import socket
import ssl
import struct
import threading

try:                                     # inside the plugin package
    from ..utils.compat import to_bytes, byte_values
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import to_bytes, byte_values

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WSError(Exception):
    pass


def _read_would_block(error):
    """Recognize Python 2.7/OpenSSL's several timeout/EAGAIN forms."""
    if isinstance(error, socket.timeout):
        return True
    number = getattr(error, 'errno', None)
    if number is None and getattr(error, 'args', None):
        number = error.args[0]
    if number in (errno.EAGAIN, errno.EWOULDBLOCK):
        return True
    if isinstance(error, ssl.SSLError):
        message = str(error).lower()
        return ('timed out' in message or 'read operation timed out' in message
                or 'did not complete (read)' in message
                or 'want read' in message)
    return False


class WebSocket(object):
    """Blocking WebSocket client. send() is thread-safe; recv() is not."""

    def __init__(self, host, path, port=443, timeout=30.0, origin=None):
        self.host = host
        self.path = path
        self.port = port
        self._sendlock = threading.Lock()
        self._buf = b''
        self.closed = False

        raw = socket.create_connection((host, port), timeout=timeout)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=host)
        self._handshake(origin)

    # ---------------------------------------------------------------- setup

    def _handshake(self, origin):
        key = base64.b64encode(os.urandom(16)).decode()
        req = [
            'GET %s HTTP/1.1' % self.path,
            'Host: %s' % self.host,
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Sec-WebSocket-Key: %s' % key,
            'Sec-WebSocket-Version: 13',
            'User-Agent: PIIP/1.0',
        ]
        if origin:
            req.append('Origin: %s' % origin)
        self.sock.sendall(('\r\n'.join(req) + '\r\n\r\n').encode())

        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError('connection closed during handshake')
            head += chunk
            if len(head) > 65536:
                raise WSError('handshake response too large')
        head, _, rest = head.partition(b'\r\n\r\n')
        self._buf = rest
        status = head.split(b'\r\n', 1)[0].decode('latin-1')
        if '101' not in status:
            raise WSError('handshake failed: %s' % status)

    # ------------------------------------------------------------------ io

    def _read(self, n):
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(65536)
            except Exception as error:
                if _read_would_block(error) and not self.closed:
                    continue
                raise
            if not chunk:
                self.closed = True
                raise WSError('connection closed')
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _frame(self, opcode, payload):
        head = bytearray()
        head.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack('>H', n)
        else:
            head.append(0x80 | 127)
            head += struct.pack('>Q', n)
        mask = os.urandom(4)
        head += mask
        # bytearray indexes to ints on both Pythons; a plain byte string
        # gives one-character strs on Python 2 and the XOR would fail.
        key = byte_values(mask)
        masked = bytearray(payload)
        for i in range(n):
            masked[i] ^= key[i & 3]
        return bytes(head) + bytes(masked)

    def send(self, data, opcode=OP_TEXT):
        # On Python 2 str is already bytes, so only text needs encoding.
        data = to_bytes(data)
        with self._sendlock:
            if self.closed:
                raise WSError('socket closed')
            self.sock.sendall(self._frame(opcode, data))

    def send_json(self, obj):
        self.send(json.dumps(obj), OP_TEXT)

    def recv(self):
        """Return one complete application message, or None if closed."""
        chunks = []
        first_op = None
        while True:
            b0, b1 = struct.unpack('>BB', self._read(2))
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            key = byte_values(self._read(4)) if masked else None
            payload = self._read(n) if n else b''
            if key:
                pa = bytearray(payload)
                for i in range(len(pa)):
                    pa[i] ^= key[i & 3]
                payload = bytes(pa)

            if opcode == OP_PING:
                self.send(payload, OP_PONG)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                self.closed = True
                try:
                    self.send(payload[:2], OP_CLOSE)
                except Exception:
                    pass
                return None

            if opcode != OP_CONT:
                first_op = opcode
            chunks.append(payload)
            if fin:
                data = b''.join(chunks)
                if first_op == OP_TEXT:
                    return data.decode('utf-8', 'replace')
                return data

    def recv_json(self):
        msg = self.recv()
        if msg is None:
            return None
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', 'replace')
        try:
            return json.loads(msg)
        except ValueError:
            return None

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.send(struct.pack('>H', 1000), OP_CLOSE)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def connect(url, timeout=30.0):
    """connect('wss://host/path?query') -> WebSocket"""
    if not url.startswith('wss://'):
        raise WSError('only wss:// is supported')
    rest = url[len('wss://'):]
    hostport, _, path = rest.partition('/')
    host, _, port = hostport.partition(':')
    return WebSocket(host, '/' + path, int(port or 443), timeout=timeout)
