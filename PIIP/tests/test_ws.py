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
"""Frame-level tests for the hand-written WebSocket client."""
import json
import errno
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate import ws

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


class FakeSock(object):
    """Serves canned bytes to recv(); records what the client sends."""

    def __init__(self, inbound=b''):
        self.inbound = inbound
        self.sent = b''

    def recv(self, n):
        if not self.inbound:
            return b''
        out, self.inbound = self.inbound[:n], self.inbound[n:]
        return out

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


def client(inbound=b''):
    c = ws.WebSocket.__new__(ws.WebSocket)
    c.sock = FakeSock(inbound)
    c._buf = b''
    c.closed = False
    import threading
    c._sendlock = threading.Lock()
    return c


def server_frame(opcode, payload, fin=True):
    """Build an UNMASKED frame, the way a server sends one."""
    if not isinstance(payload, bytes):
        payload = payload.encode('utf-8')
    head = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        head.append(n)
    elif n < 65536:
        head.append(126)
        head += struct.pack('>H', n)
    else:
        head.append(127)
        head += struct.pack('>Q', n)
    return bytes(head) + payload


def unmask_client_frame(data):
    """Decode a frame produced by our client (must be masked)."""
    # Indexing bytes gives ints on Python 3 but one-character strs on
    # Python 2; bytearray gives ints on both.
    raw = bytearray(data)
    b0, b1 = raw[0], raw[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    n = b1 & 0x7F
    i = 2
    if n == 126:
        n = struct.unpack('>H', data[i:i + 2])[0]
        i += 2
    elif n == 127:
        n = struct.unpack('>Q', data[i:i + 8])[0]
        i += 8
    assert masked, 'client frames MUST be masked'
    mask = bytearray(data[i:i + 4])
    i += 4
    payload = bytearray(data[i:i + n])
    for j in range(n):
        payload[j] ^= mask[j & 3]
    return opcode, bytes(payload)


# --------------------------------------------------------------- receiving
print('recv()')
c = client(server_frame(ws.OP_TEXT, 'hello'))
check('short text frame', c.recv() == 'hello')

mid = 'x' * 300
c = client(server_frame(ws.OP_TEXT, mid))
check('16-bit length frame (300 B)', c.recv() == mid)

big = 'y' * 70000
c = client(server_frame(ws.OP_TEXT, big))
check('64-bit length frame (70 kB)', c.recv() == big)

blob = os.urandom(5000)
c = client(server_frame(ws.OP_BIN, blob))
got = c.recv()
check('binary frame stays bytes', isinstance(got, bytes) and got == blob)

frag = (server_frame(ws.OP_TEXT, 'Hello, ', fin=False) +
        server_frame(ws.OP_CONT, 'World', fin=True))
c = client(frag)
check('fragmented message reassembles', c.recv() == 'Hello, World')

# ping must be answered and then transparently skipped
c = client(server_frame(ws.OP_PING, b'pingpayload') +
           server_frame(ws.OP_TEXT, 'after-ping'))
check('ping is skipped, next message returned', c.recv() == 'after-ping')
op, pay = unmask_client_frame(c.sock.sent)
check('ping was answered with pong', op == ws.OP_PONG and pay == b'pingpayload')

c = client(server_frame(ws.OP_CLOSE, struct.pack('>H', 1000)))
check('close frame returns None', c.recv() is None)
check('close sets closed flag', c.closed is True)

c = client(server_frame(ws.OP_TEXT, json.dumps({'setupComplete': {}})))
check('recv_json decodes', c.recv_json() == {'setupComplete': {}})

c = client(server_frame(ws.OP_TEXT, 'not json'))
check('recv_json tolerates junk', c.recv_json() is None)

class TransientSock(FakeSock):
    def __init__(self, inbound):
        FakeSock.__init__(self, inbound)
        self.once = True

    def recv(self, n):
        if self.once:
            self.once = False
            raise OSError(errno.EAGAIN, 'temporarily unavailable')
        return FakeSock.recv(self, n)

c = client()
c.sock = TransientSock(server_frame(ws.OP_TEXT, 'after-eagain'))
check('Python 2 SSL EAGAIN does not reconnect a healthy session',
      c.recv() == 'after-eagain')

# ---------------------------------------------------------------- sending
print('\nsend()')
c = client()
c.send('ping-text')
op, pay = unmask_client_frame(c.sock.sent)
check('text frame round-trips', op == ws.OP_TEXT and pay == b'ping-text')

c = client()
payload = os.urandom(200000)
c.send(payload, ws.OP_BIN)
op, pay = unmask_client_frame(c.sock.sent)
check('200 kB binary frame round-trips', op == ws.OP_BIN and pay == payload)

c = client()
c.send_json({'realtimeInput': {'audio': {'mimeType': 'audio/pcm;rate=16000'}}})
op, pay = unmask_client_frame(c.sock.sent)
check('send_json emits valid JSON',
      json.loads(pay.decode())['realtimeInput']['audio']['mimeType']
      == 'audio/pcm;rate=16000')

c = client()
c.send(u'\u0641\u0627\u0631\u0633\u06cc')
op, pay = unmask_client_frame(c.sock.sent)
check('unicode is sent as UTF-8', pay.decode('utf-8') == u'\u0641\u0627\u0631\u0633\u06cc')

# masking must actually randomise
c1, c2 = client(), client()
c1.send('same'); c2.send('same')
check('mask key is random per frame', c1.sock.sent != c2.sock.sent)

# ------------------------------------------------------------------ errors
print('\nerrors')
c = client(b'')
try:
    c.recv()
    ok = False
except ws.WSError:
    ok = True
check('truncated stream raises WSError', ok)

try:
    ws.connect('http://example.com/x')
    ok = False
except ws.WSError:
    ok = True
check('non-wss URL rejected', ok)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
