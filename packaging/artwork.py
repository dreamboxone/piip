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
"""Generate the plugin artwork.

Build-time only: numpy and zlib do the work here on a developer machine and
plain PNG files ship in the package, so the receiver needs nothing.

The look is deliberately in the same family as other Enigma2 IPTV skins -
near-black navy grounds, soft sweeping light ribbons, and glyphs drawn as
neon gradients inside a glass card with concentric rings behind them. Every
shape is a signed distance field, which gives clean anti-aliasing without a
drawing library.

    python packaging/artwork.py [output-dir]
"""

import math
import os
import struct
import sys
import zlib

import numpy as np

# ---------------------------------------------------------------- palette

NAVY_DEEP = (0.020, 0.027, 0.055)
NAVY_MID = (0.043, 0.071, 0.141)

ACCENTS = {
    'blue':    ((0.180, 0.500, 1.000), (0.290, 0.780, 1.000)),
    'purple':  ((0.482, 0.247, 0.894), (0.753, 0.310, 1.000)),
    'magenta': ((0.600, 0.200, 0.900), (1.000, 0.247, 0.659)),
    'teal':    ((0.102, 0.596, 0.769), (0.204, 0.910, 0.800)),
    'amber':   ((0.900, 0.450, 0.100), (1.000, 0.800, 0.400)),
    'green':   ((0.114, 0.588, 0.404), (0.400, 0.950, 0.600)),
}


# ------------------------------------------------------------------ canvas

class Canvas(object):
    """A float RGB image with an optional alpha channel."""

    def __init__(self, width, height):
        self.w = width
        self.h = height
        self.rgb = np.zeros((height, width, 3), dtype=np.float32)
        self.alpha = np.zeros((height, width), dtype=np.float32)
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
        # Centred coordinates, normalised on the short edge.
        self.scale = min(width, height) / 2.0
        self.x = (xs - width / 2.0 + 0.5) / self.scale
        self.y = (ys - height / 2.0 + 0.5) / self.scale
        self.px = 1.0 / self.scale          # one pixel in canvas units

    # -- compositing ------------------------------------------------------

    def fill(self, colour):
        self.rgb[:] = np.asarray(colour, dtype=np.float32)
        self.alpha[:] = 1.0

    def paint(self, mask, colour, opacity=1.0):
        """Alpha-blend a flat colour through a coverage mask."""
        a = np.clip(mask * opacity, 0.0, 1.0)[..., None]
        self.rgb = self.rgb * (1.0 - a) + np.asarray(colour, np.float32) * a
        self.alpha = np.clip(self.alpha + a[..., 0], 0.0, 1.0)

    def paint_rgb(self, mask, rgb, opacity=1.0):
        """Alpha-blend a full-colour layer through a coverage mask."""
        a = np.clip(mask * opacity, 0.0, 1.0)[..., None]
        self.rgb = self.rgb * (1.0 - a) + rgb * a
        self.alpha = np.clip(self.alpha + a[..., 0], 0.0, 1.0)

    def add(self, mask, colour, strength=1.0):
        """Additive light, which is what makes glow read as glow."""
        self.rgb = self.rgb + (mask[..., None] * strength
                               * np.asarray(colour, np.float32))
        self.alpha = np.clip(self.alpha + mask * strength, 0.0, 1.0)

    # -- helpers ----------------------------------------------------------

    def aa(self, sdf, softness=1.5):
        """Signed distance -> antialiased coverage (inside is negative)."""
        edge = softness * self.px
        return np.clip(0.5 - sdf / edge, 0.0, 1.0)

    def gradient(self, c0, c1, angle=55.0):
        """A linear gradient across the whole canvas."""
        rad = math.radians(angle)
        t = self.x * math.cos(rad) + self.y * math.sin(rad)
        t = (t - t.min()) / max(1e-6, (t.max() - t.min()))
        t = t[..., None]
        return (np.asarray(c0, np.float32) * (1.0 - t)
                + np.asarray(c1, np.float32) * t)


# ------------------------------------------------------- distance fields

def sd_circle(c, cx, cy, r):
    return np.hypot(c.x - cx, c.y - cy) - r


def sd_ring(c, cx, cy, r, thickness):
    return np.abs(np.hypot(c.x - cx, c.y - cy) - r) - thickness * 0.5


def sd_box(c, cx, cy, hw, hh, radius=0.0):
    dx = np.abs(c.x - cx) - (hw - radius)
    dy = np.abs(c.y - cy) - (hh - radius)
    outside = np.hypot(np.maximum(dx, 0.0), np.maximum(dy, 0.0))
    inside = np.minimum(np.maximum(dx, dy), 0.0)
    return outside + inside - radius


def sd_segment(c, x0, y0, x1, y1, thickness):
    px, py = c.x - x0, c.y - y0
    bx, by = x1 - x0, y1 - y0
    denom = max(1e-9, bx * bx + by * by)
    t = np.clip((px * bx + py * by) / denom, 0.0, 1.0)
    return np.hypot(px - bx * t, py - by * t) - thickness * 0.5


def sd_triangle(c, points):
    """Signed distance to a convex triangle, negative inside."""
    (ax, ay), (bx, by), (cx, cy) = points
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    sign = 1.0 if area >= 0 else -1.0
    edges = ((ax, ay, bx, by), (bx, by, cx, cy), (cx, cy, ax, ay))
    dist = None
    inside = np.ones_like(c.x, dtype=bool)
    for x0, y0, x1, y1 in edges:
        d = sd_segment(c, x0, y0, x1, y1, 0.0)
        dist = d if dist is None else np.minimum(dist, d)
        cross = ((x1 - x0) * (c.y - y0) - (y1 - y0) * (c.x - x0)) * sign
        inside &= cross >= 0
    return np.where(inside, -dist, dist)


def union(*fields):
    out = fields[0]
    for f in fields[1:]:
        out = np.minimum(out, f)
    return out


def subtract(a, b):
    return np.maximum(a, -b)


# --------------------------------------------------------------- effects

def blur(mask, radius, passes=3):
    """Box blur repeated a few times, which converges on a gaussian."""
    r = max(1, int(radius))
    out = mask.astype(np.float32)
    for _ in range(passes):
        pad = np.pad(out, ((r, r), (r, r)), mode='edge')
        cs = np.cumsum(np.cumsum(pad, axis=0), axis=1)
        cs = np.pad(cs, ((1, 0), (1, 0)), mode='constant')
        h, w = out.shape
        size = 2 * r + 1
        out = (cs[size:size + h, size:size + w] - cs[0:h, size:size + w]
               - cs[size:size + h, 0:w] + cs[0:h, 0:w]) / float(size * size)
    return out


def glow(c, mask, colour, radius, strength=1.0, passes=3):
    c.add(blur(mask, radius, passes), colour, strength)


def vignette(c, amount=0.55, power=1.6):
    r = np.hypot(c.x, c.y) / math.sqrt(2.0)
    fade = 1.0 - amount * np.clip(r, 0.0, 1.0) ** power
    c.rgb *= fade[..., None]


def grain(c, amount=0.006, seed=7):
    rng = np.random.RandomState(seed)
    c.rgb += (rng.rand(c.h, c.w, 1).astype(np.float32) - 0.5) * amount


def bokeh(c, count, colour, seed=1, rmin=0.03, rmax=0.16, opacity=0.05):
    rng = np.random.RandomState(seed)
    for _ in range(count):
        cx = rng.uniform(-1.6, 1.6)
        cy = rng.uniform(-1.1, 1.1)
        r = rng.uniform(rmin, rmax)
        d = np.hypot(c.x - cx, c.y - cy)
        soft = np.clip(1.0 - d / r, 0.0, 1.0) ** 2
        c.add(soft, colour, opacity * rng.uniform(0.5, 1.4))


def ribbon(c, pts, colour, width=0.02, strength=0.5, samples=140):
    """A sweeping light curve along a catmull-rom spline.

    The path is drawn as connected segments rather than a string of blobs:
    spacing a thin ribbon by point samples leaves it visibly dotted.
    """
    pts = np.asarray(pts, dtype=np.float32)
    path = []
    for i in range(samples):
        t = i / float(samples - 1) * (len(pts) - 3)
        seg = min(int(t), len(pts) - 4)
        f = t - seg
        p0, p1, p2, p3 = pts[seg:seg + 4]
        f2, f3 = f * f, f * f * f
        path.append(0.5 * ((2 * p1) + (-p0 + p2) * f
                           + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2
                           + (-p0 + 3 * p1 - 3 * p2 + p3) * f3))

    mask = np.zeros((c.h, c.w), dtype=np.float32)
    for i in range(len(path) - 1):
        (x0, y0), (x1, y1) = path[i], path[i + 1]
        # Fade both ends so the ribbon dissolves instead of stopping dead.
        taper = math.sin(math.pi * (i / float(len(path) - 2))) ** 0.6
        if taper <= 0.01:
            continue
        d = sd_segment(c, x0, y0, x1, y1, 0.0)
        mask = np.maximum(mask, np.clip(1.0 - d / width, 0.0, 1.0) * taper)

    c.add(blur(mask, max(2, int(width * c.scale * 0.6)), 2), colour, strength)
    c.add(mask ** 3, colour, strength * 0.8)


# ------------------------------------------------------------ png output

def write_png(path, rgb, alpha=None):
    """Write 8-bit RGB or RGBA without an image library."""
    h, w = rgb.shape[:2]
    # Compress only what exceeds 1.0, so saturated neon keeps its hue
    # instead of being pulled towards white by a global roll-off.
    data = np.asarray(rgb, np.float32)
    peak = data.max(axis=2, keepdims=True)
    over = peak > 1.0
    scaled = np.where(over, data / np.maximum(peak, 1e-6), data)
    knee = np.clip((peak - 1.0) / 2.0, 0.0, 1.0)
    data = scaled * (1.0 - knee) + np.minimum(data, 1.0) * knee
    data = np.clip(data, 0.0, 1.0)
    eight = (data * 255.0 + 0.5).astype(np.uint8)

    if alpha is None:
        planes, ctype = eight, 2
    else:
        a8 = (np.clip(alpha, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        planes = np.concatenate([eight, a8[..., None]], axis=2)
        ctype = 6

    stride = planes.shape[2]
    raw = np.zeros((h, w * stride + 1), dtype=np.uint8)
    raw[:, 1:] = planes.reshape(h, w * stride)
    payload = raw.tobytes()

    def chunk(tag, body):
        return (struct.pack('>I', len(body)) + tag + body
                + struct.pack('>I', zlib.crc32(tag + body) & 0xffffffff))

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(payload, 9))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as fh:
        fh.write(png)
    return len(png)


# ------------------------------------------------------------ backgrounds

def background(width=1920, height=1080, accent='blue', seed=3):
    c = Canvas(width, height)
    c.paint_rgb(np.ones((height, width), np.float32),
                c.gradient(NAVY_DEEP, NAVY_MID, angle=70))

    dark, light = ACCENTS[accent]
    rng = np.random.RandomState(seed)

    # Three sweeping ribbons of different weight, as in the reference art.
    for i, (width_, strength) in enumerate(((0.055, 0.30),
                                            (0.022, 0.45),
                                            (0.009, 0.65))):
        pts = []
        for k in range(6):
            pts.append((-2.2 + k * 0.9 + rng.uniform(-0.2, 0.2),
                        rng.uniform(-0.75, 0.75) + (0.25 if i == 1 else 0.0)))
        ribbon(c, pts, light if i == 2 else dark,
               width=width_, strength=strength, samples=200)

    bokeh(c, 14, light, seed=seed + 5, opacity=0.035)

    # Faint stars, very sparse.
    stars = (rng.rand(height, width) > 0.99965).astype(np.float32)
    c.add(blur(stars, 1, 1) * 6.0, (0.8, 0.9, 1.0), 0.30)

    vignette(c, amount=0.62, power=1.5)
    grain(c, 0.005, seed)
    return c


# ------------------------------------------------------------------ icons

def icon_base(size, accent):
    """Transparent shared furniture: glass outline and glowing rings."""
    c = Canvas(size, size)
    dark, light = ACCENTS[accent]

    # Keep only the luminous outline.  An opaque square made these icons
    # appear as black tiles on skins whose menu background is not black.
    card = sd_box(c, 0.0, 0.0, 0.70, 0.70, radius=0.10)
    border = np.abs(card) - 0.004
    c.add(c.aa(border), light, 0.38)

    # Concentric rings behind the glyph
    for i, r in enumerate((0.30, 0.365, 0.425, 0.485, 0.545)):
        ring = sd_ring(c, 0.0, 0.0, r, 0.005)
        m = c.aa(ring)
        c.add(m, light, 0.34 - 0.055 * i)
        c.add(blur(m, int(size * 0.018), 2), dark, 0.55 - 0.09 * i)
    return c


def local_gradient(c, mask, c0, c1, angle=35.0):
    """A gradient normalised over the shape's own extent.

    A canvas-wide gradient barely varies across a small glyph, which is why
    the colour has to be mapped onto the bounding box of the mask.
    """
    rad = math.radians(angle)
    t = c.x * math.cos(rad) + c.y * math.sin(rad)
    inside = mask > 0.02
    if not inside.any():
        lo, hi = t.min(), t.max()
    else:
        lo, hi = float(t[inside].min()), float(t[inside].max())
    t = np.clip((t - lo) / max(1e-6, hi - lo), 0.0, 1.0)[..., None]
    return (np.asarray(c0, np.float32) * (1.0 - t)
            + np.asarray(c1, np.float32) * t)


def draw_glyph(c, sdf, accent, bloom=1.0):
    """Fill a shape with the accent gradient and light it up."""
    dark, light = ACCENTS[accent]
    body = c.aa(sdf)
    grad = local_gradient(c, body, dark, light, angle=35)
    c.paint_rgb(body, grad)

    # Inner highlight along the upper-left edge
    edge = c.aa(np.abs(sdf) - 0.006)
    c.add(edge * body, (1.0, 1.0, 1.0), 0.20)

    # Bloom
    size = min(c.w, c.h)
    c.add(blur(body, int(size * 0.030), 3), light, 0.55 * bloom)
    c.add(blur(body, int(size * 0.075), 3), dark, 0.85 * bloom)
    return c


# ------------------------------------------------------------- glyph set

def glyph_live(c):
    """A screen with a play mark and broadcast arcs."""
    screen = sd_box(c, 0.0, 0.02, 0.34, 0.24, radius=0.05)
    inner = sd_box(c, 0.0, 0.02, 0.30, 0.20, radius=0.035)
    frame = subtract(screen, inner)
    stand = sd_box(c, 0.0, 0.30, 0.14, 0.025, radius=0.02)
    neck = sd_box(c, 0.0, 0.275, 0.03, 0.035, radius=0.01)
    play = sd_triangle(c, ((-0.07, -0.10), (-0.07, 0.14), (0.11, 0.02)))
    arcs = union(sd_ring(c, 0.0, -0.30, 0.16, 0.030),
                 sd_ring(c, 0.0, -0.30, 0.26, 0.026))
    arcs = np.maximum(arcs, c.y + 0.30)          # keep the upper half only
    return union(frame, stand, neck, play, arcs)


def glyph_movie(c):
    """A clapperboard."""
    body = sd_box(c, 0.0, 0.10, 0.36, 0.22, radius=0.05)
    top = sd_box(c, 0.0, -0.20, 0.37, 0.09, radius=0.03)
    stripes = None
    for i in range(4):
        x = -0.26 + i * 0.175
        s = sd_box(c, x, -0.20, 0.032, 0.09, radius=0.012)
        stripes = s if stripes is None else union(stripes, s)
    top = subtract(top, stripes)
    play = sd_triangle(c, ((-0.06, 0.00), (-0.06, 0.21), (0.11, 0.105)))
    return union(subtract(body, play), top)


def glyph_series(c):
    """Stacked cards, the back ones peeking out."""
    back = sd_box(c, 0.10, -0.16, 0.26, 0.18, radius=0.045)
    mid = sd_box(c, 0.05, -0.06, 0.30, 0.21, radius=0.05)
    front = sd_box(c, -0.02, 0.08, 0.34, 0.24, radius=0.055)
    play = sd_triangle(c, ((-0.08, -0.01), (-0.08, 0.19), (0.08, 0.09)))
    return union(subtract(front, play),
                 subtract(mid, sd_box(c, -0.02, 0.08, 0.36, 0.26, radius=0.06)),
                 subtract(back, sd_box(c, 0.05, -0.06, 0.32, 0.23, radius=0.055)))


def glyph_folder(c):
    """A folder with signal waves, echoing the reference m3u icon."""
    tab = sd_box(c, -0.16, -0.22, 0.18, 0.07, radius=0.03)
    body = sd_box(c, 0.0, 0.04, 0.36, 0.24, radius=0.06)
    lines = None
    for i in range(3):
        y = -0.05 + i * 0.10
        ln = sd_box(c, -0.02, y, 0.22, 0.022, radius=0.015)
        lines = ln if lines is None else union(lines, ln)
    waves = None
    for i, r in enumerate((0.10, 0.17, 0.24)):
        w = sd_ring(c, 0.30, -0.16, r, 0.028)
        w = np.maximum(w, -(0.30 - c.x))         # right-hand half only
        w = np.maximum(w, (c.y + 0.16))
        waves = w if waves is None else union(waves, w)
    return union(subtract(union(tab, body), lines), waves)


def glyph_server(c):
    """Stacked server blades with status lamps."""
    out = None
    for i in range(3):
        y = -0.24 + i * 0.24
        blade = sd_box(c, 0.0, y, 0.36, 0.09, radius=0.03)
        lamp = sd_circle(c, 0.22, y, 0.028)
        slot = sd_box(c, -0.14, y, 0.14, 0.018, radius=0.012)
        piece = subtract(blade, union(lamp, slot))
        out = piece if out is None else union(out, piece)
    return out


def glyph_box(c):
    """A set-top box with an aerial: the Stalker portal."""
    body = sd_box(c, 0.0, 0.16, 0.38, 0.13, radius=0.045)
    slot = sd_box(c, -0.16, 0.16, 0.12, 0.02, radius=0.014)
    lamp = sd_circle(c, 0.22, 0.16, 0.030)
    mast = sd_segment(c, 0.0, 0.03, 0.0, -0.12, 0.030)
    left = sd_segment(c, 0.0, -0.12, -0.20, -0.30, 0.030)
    right = sd_segment(c, 0.0, -0.12, 0.20, -0.30, 0.030)
    knob = sd_circle(c, 0.0, -0.12, 0.045)
    return union(subtract(body, union(slot, lamp)), mast, left, right, knob)


def glyph_list(c):
    """A bouquet: a list with a star."""
    rows = None
    for i in range(4):
        y = -0.21 + i * 0.15
        dot = sd_circle(c, -0.26, y, 0.035)
        bar = sd_box(c, 0.04, y, 0.24, 0.030, radius=0.020)
        row = union(dot, bar)
        rows = row if rows is None else union(rows, row)
    star = None
    for k in range(5):
        a0 = -math.pi / 2 + k * 2 * math.pi / 5
        a1 = a0 + math.pi * 2 / 5
        p0 = (0.26 + 0.13 * math.cos(a0), 0.30 + 0.13 * math.sin(a0))
        p1 = (0.26 + 0.13 * math.cos(a1), 0.30 + 0.13 * math.sin(a1))
        tri = sd_triangle(c, ((0.26, 0.30), p0, p1))
        star = tri if star is None else union(star, tri)
    return union(rows, star)


def glyph_gear(c):
    """Settings."""
    teeth = None
    for k in range(8):
        a = k * math.pi / 4.0
        cx, cy = 0.30 * math.cos(a), 0.30 * math.sin(a)
        t = sd_box(c, cx, cy, 0.075, 0.075, radius=0.025)
        teeth = t if teeth is None else union(teeth, t)
    body = sd_circle(c, 0.0, 0.0, 0.27)
    hole = sd_circle(c, 0.0, 0.0, 0.11)
    return subtract(union(body, teeth), hole)


def glyph_wave(c):
    """Translation: a speech bubble over a waveform."""
    bubble = sd_box(c, 0.0, -0.10, 0.34, 0.20, radius=0.08)
    tail = sd_triangle(c, ((-0.10, 0.08), (0.02, 0.08), (-0.04, 0.22)))
    bars = None
    heights = (0.05, 0.10, 0.15, 0.09, 0.04)
    for i, hgt in enumerate(heights):
        x = -0.20 + i * 0.10
        b = sd_box(c, x, -0.10, 0.022, hgt, radius=0.016)
        bars = b if bars is None else union(bars, b)
    return subtract(union(bubble, tail), bars)


def glyph_search(c):
    """Diagnostics: a magnifier over a pulse line."""
    lens = subtract(sd_circle(c, -0.06, -0.06, 0.26),
                    sd_circle(c, -0.06, -0.06, 0.19))
    handle = sd_segment(c, 0.12, 0.12, 0.30, 0.30, 0.075)
    pulse = union(
        sd_segment(c, -0.20, -0.06, -0.10, -0.06, 0.030),
        sd_segment(c, -0.10, -0.06, -0.05, -0.17, 0.030),
        sd_segment(c, -0.05, -0.17, 0.01, 0.05, 0.030),
        sd_segment(c, 0.01, 0.05, 0.06, -0.06, 0.030),
        sd_segment(c, 0.06, -0.06, 0.14, -0.06, 0.030))
    pulse = np.maximum(pulse, sd_circle(c, -0.06, -0.06, 0.19))
    return union(lens, handle, pulse)


GLYPHS = {
    'live': (glyph_live, 'blue'),
    'movies': (glyph_movie, 'magenta'),
    'series': (glyph_series, 'purple'),
    'bouquets': (glyph_list, 'amber'),
    'settings': (glyph_gear, 'teal'),
    'diagnose': (glyph_search, 'green'),
    'm3u': (glyph_folder, 'purple'),
    'xtream': (glyph_server, 'blue'),
    'stalker': (glyph_box, 'magenta'),
    'translate': (glyph_wave, 'teal'),
}


def make_icon(name, size=512):
    fn, accent = GLYPHS[name]
    c = icon_base(size, accent)
    draw_glyph(c, fn(c), accent)
    vignette(c, amount=0.35, power=1.8)
    grain(c, 0.004, seed=hash(name) % 997)
    return c


# -------------------------------------------------------------- assembly

ICON_LARGE = 460
ICON_SMALL = 280

BACKGROUNDS = (
    ('bg_main', 'blue', 3),
    ('bg_m3u', 'purple', 11),
    ('bg_xtream', 'blue', 23),
    ('bg_stalker', 'magenta', 37),
    ('bg_list', 'teal', 51),
)


def build(outdir):
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    total = 0

    for name, accent, seed in BACKGROUNDS:
        c = background(1920, 1080, accent, seed)
        path = os.path.join(outdir, name + '.png')
        n = write_png(path, c.rgb)
        total += n
        print('  %-16s 1920x1080  %6.1f kB' % (name + '.png', n / 1024.0))

    # Two fixed sizes rather than one: Enigma2's pixmap scaling is not
    # dependable on older images, so the skin uses them at native size.
    for name in sorted(GLYPHS):
        for suffix, size in (('', ICON_LARGE), ('_s', ICON_SMALL)):
            c = make_icon(name, size)
            fname = '%s%s.png' % (name, suffix)
            n = write_png(os.path.join(outdir, fname), c.rgb, c.alpha)
            total += n
            print('  %-16s  %3dx%-3d   %6.1f kB'
                  % (fname, size, size, n / 1024.0))

    print('  total %.1f kB' % (total / 1024.0))
    total += emblems(outdir)
    return total


EMBLEM = 450
EMBLEMS = ('m3u', 'xtream', 'stalker')


def emblems(outdir):
    """Setup/source-screen emblems: the icon with its card filling 450px.

    HybridIPTV scales its emblem into a 450px-tall box. The menu icons
    leave a wide transparent margin round the card, which at that size
    shrinks the glyph to a third of the reference's, so the emblem is
    rendered larger and cropped to the card instead of being upscaled.
    """
    total = 0
    render = int(round(EMBLEM / 0.67))   # card outline just inside
    lo = (render - EMBLEM) // 2
    for name in EMBLEMS:
        c = make_icon(name, render)
        rgb = c.rgb[lo:lo + EMBLEM, lo:lo + EMBLEM]
        alpha = c.alpha[lo:lo + EMBLEM, lo:lo + EMBLEM]
        fname = 'emblem_%s.png' % name
        n = write_png(os.path.join(outdir, fname), rgb, alpha)
        total += n
        print('  %-16s  %3dx%-3d   %6.1f kB' % (fname, EMBLEM, EMBLEM, n / 1024.0))
    return total


if __name__ == '__main__':
    target = (sys.argv[1] if len(sys.argv) > 1
              else os.path.join(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__))), 'PIIP', 'icons'))
    if '--emblems' in sys.argv[1:]:
        # Only the emblems: the wallpapers in the icons folder are kept.
        target = next((x for x in sys.argv[1:] if not x.startswith('--')),
                      os.path.join(os.path.dirname(os.path.dirname(
                          os.path.abspath(__file__))), 'PIIP', 'icons'))
        print('writing emblems to %s' % target)
        emblems(target)
    else:
        print('writing artwork to %s' % target)
        build(target)
