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
"""Behavioural tests for the audio core (runs on the dev box, not the STB)."""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate import mixer as mx

FAIL = []
BPS = mx.OUT_BPS                      # 192000 bytes/s = 48 kHz stereo s16


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


def tone(n_samples, freq, rate, amp=10000, channels=1):
    out = bytearray()
    for i in range(n_samples):
        v = int(amp * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            out += struct.pack('<h', v)
    return bytes(out)


def samples(pcm):
    return struct.unpack('<%dh' % (len(pcm) // 2), pcm) if pcm else ()


def peak(pcm):
    v = samples(pcm)
    return max(abs(x) for x in v) if v else 0


def srange(pcm):
    v = samples(pcm)
    return (min(v), max(v)) if v else (0, 0)


def no_wrap(src, out):
    """Overflow would flip a sample's sign; saturation preserves it."""
    return all((x >= 0) == (y >= 0) for x, y in zip(samples(src), samples(out)))


print('backend: %s' % mx._backend)
print('')
# ------------------------------------------------------------------- scale
print('scale()')
src = tone(1000, 440, 48000, amp=10000)
check('gain 1.0 is identity', mx.scale(src, 1.0) == src)
check('gain 0.0 silences', peak(mx.scale(src, 0.0)) == 0)
half = peak(mx.scale(src, 0.5))
check('gain 0.5 halves peak', 4800 <= half <= 5200, 'peak=%d' % half)
loud = mx.scale(src, 8.0)
lo, hi = srange(loud)
check('gain saturates inside int16', -32768 <= lo and hi <= 32767,
      'range=(%d,%d)' % (lo, hi))
check('gain never wraps sign', no_wrap(src, loud))

# --------------------------------------------------------------------- add
print('\nadd()')
a = tone(1000, 440, 48000, amp=10000)
check('sum of equals doubles', 19000 <= peak(mx.add(a, a)) <= 20100)
big = tone(1000, 440, 48000, amp=30000)
summed = mx.add(big, big)
lo, hi = srange(summed)
check('sum saturates inside int16', -32768 <= lo and hi <= 32767,
      'range=(%d,%d)' % (lo, hi))
check('sum never wraps sign', no_wrap(big, summed))
check('mismatched lengths truncate', len(mx.add(a, a[:100])) == 100)

# --------------------------------------------------------------- Resampler
print('\nResampler 24k mono -> 48k stereo')
r = mx.Resampler()
mono = tone(2400, 300, 24000, amp=8000)                  # 100 ms
out = r(mono)
check('length is 2x rate and stereo', abs(len(out) - 2400 * 8) <= 64,
      'got %d want ~%d' % (len(out), 2400 * 8))
check('amplitude preserved', 7000 <= peak(out) <= 9000, 'peak=%d' % peak(out))
check('empty input is safe', r(b'') == b'')

# --------------------------------------------------------------- ByteDelay
print('\nByteDelay')
tenth = b'\x01\x02' * (BPS // 10 // 2)                    # exactly 100 ms
check('test fixture is 100 ms', len(tenth) == BPS // 10, '%d bytes' % len(tenth))
d = mx.ByteDelay(BPS, 1.0)                                # 1 s = 192000 bytes
for _ in range(5):
    d.write(tenth)                                        # 0.5 s buffered
check('withholds until delay met', d.read(1920) is None)
for _ in range(6):
    d.write(tenth)                                        # 1.1 s buffered
check('releases once past delay', d.read(1920) is not None)
d0 = mx.ByteDelay(BPS, 0.0)
d0.write(tenth)
check('zero delay passes straight through', d0.read(1920) is not None)

# -------------------------------------------------------- TranslationBuffer
print('\nTranslationBuffer')
tb = mx.TranslationBuffer(max_backlog=1.0)
tb.write(b'\x00\x01' * 4800)
check('pads short reads with silence', len(tb.read(96000)) == 96000)
tb2 = mx.TranslationBuffer(max_backlog=1.0)
for _ in range(30):
    tb2.write(tenth)                                      # 3 s into a 1 s cap
check('backlog capped, drops oldest', tb2.backlog_seconds() <= 1.05,
      'backlog=%.2fs' % tb2.backlog_seconds())
check('drop counter records loss', tb2.dropped_bytes > 0)
check('empty buffer yields silence', mx.TranslationBuffer().read(960) == b'\0' * 960)

# -------------------------------------------------------------------- Mixer
print('\nMixer end-to-end')
m = mx.Mixer(0.5, max_backlog=6.0)
m.gain_original, m.gain_translated = 1.0, 0.0
check('nothing out while delay fills', m.pull(1920) is None)
for _ in range(12):
    m.feed_original(tone(4800, 440, 48000, amp=10000, channels=2))
got = m.pull(1920)
check('produces audio once filled', got is not None and len(got) == 1920)
check('original audible at gain 1.0', peak(got) > 1000, 'peak=%d' % peak(got))

m.gain_original = 0.0
check('original returns while translation is absent', peak(m.pull(1920)) > 1000)

m.gain_translated = 1.0
m.feed_translated(tone(2400, 300, 24000, amp=9000))
mixed = m.pull(1920)
check('translated audible with original muted', peak(mixed) > 1000,
      'peak=%d' % peak(mixed))
for _ in range(15):
    m.feed_translated(tone(2400, 300, 24000, amp=9000))
    m.pull(1920)
check('original fades toward configured gain while dub is present',
      m.active_original_gain < 0.2,
      'gain=%.2f' % m.active_original_gain)

m.gain_original = 1.0
both = m.pull(1920)
check('both tracks mix together', peak(both) > 1000, 'peak=%d' % peak(both))

tb3 = mx.TranslationBuffer(max_backlog=12.0)
tb3.write(tone(4800, 300, 48000, amp=9000, channels=2))
tb3.read(3840)  # establish the normal startup reserve
tb3.write(tone(48000 * 3, 300, 48000, amp=9000, channels=2))
for _ in range(100):
    tb3.read(3840)
check('translation catch-up is bounded to 1.08x',
      1.001 < tb3.speed <= 1.0801, 'tempo=%.4f' % tb3.speed)

print('')
print('Translation follows the programme position')
ts = mx.TranslationBuffer(max_backlog=20.0, max_late=8.0)
ts.write(tone(4800, 300, 48000, amp=9000, channels=2), not_before=5.0)
out, played = ts.read_with_presence(1920, position=4.0)
check('speech waits for its place in the programme', not played and peak(out) == 0)
check('waiting is reported', ts.waiting)
out, played = ts.read_with_presence(1920, position=5.0)
check('speech plays once the programme reaches it', played and peak(out) > 1000)
ts2 = mx.TranslationBuffer(max_backlog=20.0, max_late=8.0)
ts2.write(tone(4800, 300, 48000, amp=9000, channels=2), not_before=1.0)
out, played = ts2.read_with_presence(1920, position=20.0)
check('speech too late for the picture is dropped unheard',
      not played and ts2.late_dropped_bytes > 0)
ts4 = mx.TranslationBuffer(max_backlog=60.0, max_late=8.0)
ts4.write(struct.pack('<h', 10000) * (BPS * 20 // 2), not_before=0.0)  # a 20 s sentence
pos, played_all = 0.0, True
while pos < 17.0:
    out, played = ts4.read_with_presence(3840, position=pos)
    played_all = played_all and played
    pos += 0.02
check('a long sentence that is playing is never dropped as late',
      played_all and ts4.late_dropped_bytes == 0,
      'late dropped %d' % ts4.late_dropped_bytes)

ts3 = mx.TranslationBuffer(max_backlog=20.0)
ts3.write(tone(4800, 300, 48000, amp=9000, channels=2), not_before=2.0)
ts3.write(tone(4800, 300, 48000, amp=9000, channels=2), not_before=2.05)
check('continuing speech joins the same utterance', len(ts3._segs) == 1)
ts3.write(tone(4800, 300, 48000, amp=9000, channels=2), not_before=9.0)
check('a later sentence is scheduled separately', len(ts3._segs) == 2)

mt = mx.Mixer(0.0, max_backlog=30.0)
speech = tone(4800, 300, 24000, amp=9000)                 # 200 ms of 24 kHz
gap = bytes(bytearray(24000 * 2))                      # 1 s of silence
mt.feed_translated(speech)
mt.feed_translated(gap)
mt.feed_translated(speech)
queued = mt.translated.backlog_seconds()
check('long pauses inside translated speech are shortened',
      0.55 <= queued <= 0.70, 'queued %.2fs' % queued)
check('pause trimming is counted', mt.pause_trimmed > 0)

bd = mx.ByteDelay(BPS, 0.0)
chunk = bytes(bytearray(range(256)) * 15)             # 3840 bytes, a pattern
for _ in range(400):
    bd.write(chunk)
same = all(bd.read(3840) == chunk for _ in range(400))
check('delay line stays exact across compaction', same)
check('delay line reports the programme position',
      abs(bd.position() - 400 * 3840 / float(BPS)) < 1e-9)

m.set_delay(3.0)
check('delay is adjustable at runtime', abs(m.original.seconds - 3.0) < 1e-9)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all %d checks passed' % 0 if FAIL else 'all checks passed')
