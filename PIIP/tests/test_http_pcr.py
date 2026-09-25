# -*- coding: utf-8 -*-
"""The receiver-facing transport follows MPEG-TS time through HLS bursts."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..',
                                'translate', 'e2dub'))
from e2dub_http import PcrPacer                         # noqa: E402


def packet(seconds=None):
    data = bytearray([0x47, 0x01, 0x00, 0x10]) + bytearray(184)
    if seconds is not None:
        ticks = int(seconds * 90000)
        data[3:6] = bytearray([0x30, 7, 0x10])
        data[6:12] = bytearray([
            (ticks >> 25) & 255, (ticks >> 17) & 255,
            (ticks >> 9) & 255, (ticks >> 1) & 255,
            (ticks & 1) << 7, 0,
        ])
    return bytes(data)


stream = (packet(0) + packet() * 99 + packet(.1) +
          packet() * 99 + packet(.2) + packet() * 99 +
          packet(.3) + packet() * 99 + packet(.4) +
          packet() * 99 + packet(.5) + packet() * 99 + packet(.6))
clock = PcrPacer()
clock.feed(10.0, stream[:277])
clock.feed(10.0, stream[277:])
assert len(clock.anchors) == 7, list(clock.anchors)
print('  PASS  PCR is found across split TS packets')
assert clock.budget(11.5, len(stream)) == 0
print('  PASS  an HLS pause does not flush the startup reservoir')
assert 27000 < clock.budget(13.8, len(stream)) < 29000
print('  PASS  decoder receives 150 ms of media after startup buffering')
assert clock.budget(13.9, len(stream)) > clock.budget(13.8, len(stream))
print('  PASS  decoder lead stays ahead of the wall clock')
assert clock.budget(14.1, len(stream)) > clock.budget(13.9, len(stream))
print('  PASS  packet budget advances with PCR time')
