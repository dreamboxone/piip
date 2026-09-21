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
"""Generate the plugin menu icon without needing an image library.

Enigma2 plugin icons are small PNGs; writing one by hand is less trouble
than depending on Pillow being available wherever this gets built.
"""

import struct
import sys
import zlib

W, H = 200, 100

BG = (14, 18, 28)
BAR = (255, 204, 102)          # the accent used across the plugin screens
TEXT = (255, 255, 255)
DOT = (128, 255, 128)

# 5x7 bitmap font, only the glyphs this icon needs.
GLYPHS = {
    'F': ('11111', '10000', '10000', '11110', '10000', '10000', '10000'),
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'I': ('11111', '00100', '00100', '00100', '00100', '00100', '11111'),
    'P': ('11110', '10001', '10001', '11110', '10000', '10000', '10000'),
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'V': ('10001', '10001', '10001', '10001', '10001', '01010', '00100'),
    ' ': ('00000', '00000', '00000', '00000', '00000', '00000', '00000'),
}


def blank(w, h, colour):
    return [[colour for _ in range(w)] for _ in range(h)]


def rect(px, x0, y0, x1, y1, colour):
    for y in range(max(0, y0), min(len(px), y1)):
        for x in range(max(0, x0), min(len(px[0]), x1)):
            px[y][x] = colour


def text(px, s, x0, y0, colour, scale=3):
    cx = x0
    for ch in s.upper():
        glyph = GLYPHS.get(ch)
        if glyph is None:
            cx += 6 * scale
            continue
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == '1':
                    rect(px, cx + col * scale, y0 + row * scale,
                         cx + (col + 1) * scale, y0 + (row + 1) * scale, colour)
        cx += 6 * scale
    return cx


def write_png(path, px):
    h, w = len(px), len(px[0])
    raw = bytearray()
    for row in px:
        raw.append(0)                       # filter type: none
        for r, g, b in row:
            raw += bytes((r, g, b))

    def chunk(tag, data):
        out = struct.pack('>I', len(data)) + tag + data
        return out + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as fh:
        fh.write(png)
    return len(png)


def build(path):
    px = blank(W, H, BG)
    rect(px, 0, 0, W, 4, BAR)               # top rule
    rect(px, 0, H - 4, W, H, BAR)           # bottom rule
    end = text(px, 'FARSI', 14, 20, TEXT, scale=3)
    text(px, 'IPTV', 14, 52, BAR, scale=3)
    # a small "on air" dot next to the wordmark
    rect(px, end + 10, 26, end + 22, 38, DOT)
    return write_png(path, px)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'icon.png'
    print('wrote %s (%d bytes)' % (target, build(target)))
