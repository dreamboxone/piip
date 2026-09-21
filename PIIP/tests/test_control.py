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
"""End-to-end test of the engine control socket and its client."""
import os
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate.engine import Engine
from translate.control import EngineHandle

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
eng = Engine({
    'url': 'http://example.invalid/none.ts',
    'translate': False,
    'delay': 4.0,
    'gain_original': 0.25,
    'gain_translated': 1.0,
    'control_port': PORT,
    'http_port': free_port(),
    'log': os.path.join(tempfile.gettempdir(), 'piip_engine_test.log'),
})

t = threading.Thread(target=eng._control_server, name='ctl')
t.daemon = True
t.start()

# wait for the listener
for _ in range(60):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close()
        break
    except Exception:
        time.sleep(0.05)

h = EngineHandle({'control_port': PORT, 'http_port': 9999})

print('control protocol')
st = h.status()
check('status responds', st is not None and st.get('ok') is True)
check('status reports initial delay', abs(st['delay'] - 4.0) < 1e-9,
      str(st.get('delay')))
check('status reports initial gains',
      abs(st['gain_original'] - 0.25) < 1e-9 and
      abs(st['gain_translated'] - 1.0) < 1e-9)

r = h.set_gain(original=0.6, translated=0.4)
check('set_gain acknowledged', r and r.get('ok') is True)
check('gains applied to the live mixer',
      abs(eng.mixer.gain_original - 0.6) < 1e-9 and
      abs(eng.mixer.gain_translated - 0.4) < 1e-9,
      '%.2f/%.2f' % (eng.mixer.gain_original, eng.mixer.gain_translated))

h.set_gain(translated=0.9)
check('single-sided gain leaves the other alone',
      abs(eng.mixer.gain_original - 0.6) < 1e-9 and
      abs(eng.mixer.gain_translated - 0.9) < 1e-9)

# Volume is a share of the source, so unity is the ceiling: anything above
# it would only clip the mix.
h.set_gain(original=99.0, translated=-5.0)
check('gain never exceeds unity',
      eng.mixer.gain_original == 1.0 and eng.mixer.gain_translated == 0.0,
      '%.2f/%.2f' % (eng.mixer.gain_original, eng.mixer.gain_translated))
h.set_gain(original=1.5)
check('even 150% is held at 100%', eng.mixer.gain_original == 1.0,
      '%.2f' % eng.mixer.gain_original)

r = h.set_delay(7.5)
check('set_delay acknowledged', r and abs(r.get('delay') - 7.5) < 1e-9)
check('delay applied to audio line', abs(eng.mixer.original.seconds - 7.5) < 1e-9)
check('delay applied to video line', abs(eng.video.seconds - 7.5) < 1e-9)

h.set_delay(999)
check('delay is clamped', eng.mixer.original.seconds == 15.0,
      str(eng.mixer.original.seconds))

bad = h.try_command({'cmd': 'nonsense'})
check('unknown command rejected cleanly',
      bad is not None and bad.get('ok') is False and 'error' in bad)

malformed = None
try:
    s = socket.create_connection(('127.0.0.1', PORT), 2.0)
    s.sendall(b'{not json\n')
    malformed = s.recv(4096)
    s.close()
except Exception as e:
    malformed = b'exception: %s' % str(e).encode()
check('malformed JSON does not kill the server', b'ok' in (malformed or b''),
      repr(malformed)[:80])
check('server still alive after bad input', h.status() is not None)

print('\nURL helper')
h2 = EngineHandle({'http_port': 8901, 'control_port': 8902})
check('stream url is loopback only',
      h2.url == 'http://127.0.0.1:8901/live.ts', h2.url)

print('\nsupervision')
h3 = EngineHandle({'control_port': free_port(), 'http_port': free_port()})
check('alive() false before start', h3.alive() is False)
check('stop() on a dead handle is safe', h3.stop() is None)
check('commands to nothing return None, not an exception', h3.status() is None)
check('wait_ready times out instead of hanging',
      h3.wait_ready(timeout=0.6) is False)

eng.stopping.set()
print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
