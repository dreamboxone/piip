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
"""SubRip / WebVTT parsing and lookup.

Persian subtitles arrive in a wide range of encodings — UTF-8 with and
without a BOM, and Windows-1256 from older sources — so decoding is done by
sniffing rather than trusting the file.
"""

import os
import re
import zipfile

from .compat import native

try:
    import io
    BytesIO = io.BytesIO
except ImportError:                                    # pragma: no cover
    from StringIO import StringIO as BytesIO

TIME = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*'
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')
TAG = re.compile(r'<[^>]+>')
BRACE = re.compile(r'\{\\[^}]*\}')          # ASS/SSA override blocks in SRT

ENCODINGS = ('utf-8-sig', 'utf-8', 'cp1256', 'iso-8859-6', 'cp1252', 'latin-1')


class Cue(object):
    __slots__ = ('start', 'end', 'text')

    def __init__(self, start, end, text):
        self.start = int(start)             # milliseconds
        self.end = int(end)
        # Subtitle files decode to unicode; the overlay is a SWIG widget.
        self.text = native(text)

    @property
    def duration(self):
        return max(0, self.end - self.start)

    def __repr__(self):
        return '<Cue %d-%d %r>' % (self.start, self.end, self.text[:30])


def decode(data):
    """Bytes -> text, guessing the encoding Persian subtitles actually use."""
    if not isinstance(data, bytes):
        return data
    for enc in ENCODINGS:
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # A wrong single-byte guess shows up as a pile of replacement chars.
        if u'�' not in text:
            return text
    return data.decode('utf-8', 'replace')


def _ms(h, m, s, frac):
    frac = (frac + '00')[:3]                # '5' -> 500, '05' -> 050
    return ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(frac)


def clean(text):
    text = BRACE.sub('', text)
    text = TAG.sub('', text)
    return text.strip()


def parse(data):
    """Parse SRT or VTT into a time-ordered list of Cue."""
    text = decode(data)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    lines = text.split('\n')
    i, n = 0, len(lines)
    while i < n:
        m = TIME.search(lines[i])
        if not m:
            i += 1
            continue
        start = _ms(*m.group(1, 2, 3, 4))
        end = _ms(*m.group(5, 6, 7, 8))
        i += 1
        body = []
        while i < n and lines[i].strip():
            body.append(lines[i])
            i += 1
        payload = clean('\n'.join(body))
        if payload and end > start:
            cues.append(Cue(start, end, payload))
        i += 1
    cues.sort(key=lambda c: c.start)
    return cues


def from_zip(data, prefer=('.srt', '.vtt', '.ass')):
    """Most subtitle sites hand out a zip; pull the first subtitle out."""
    zf = zipfile.ZipFile(BytesIO(data))
    names = zf.namelist()
    for ext in prefer:
        for name in names:
            if name.lower().endswith(ext):
                return parse(zf.read(name))
    if names:
        return parse(zf.read(names[0]))
    return []


def load(data):
    """Parse whatever a download gave us: raw subtitle or a zip."""
    # On Python 2 downloaded bytes are str too, and os.stat raises on the
    # NUL bytes inside a zip, so only something shaped like a path is tried.
    if isinstance(data, str) and len(data) < 4096 and '\0' not in data \
            and os.path.isfile(data):
        with open(data, 'rb') as handle:
            data = handle.read()
    if isinstance(data, bytes) and data[:2] == b'PK':
        return from_zip(data)
    return parse(data)


class Subtitles(object):
    """Cue lookup with an adjustable time shift."""

    def __init__(self, cues=None, offset_ms=0, source_name=''):
        self.cues = list(cues or [])
        self.offset = int(offset_ms)
        self.sub_fps = 0.0
        self.video_fps = 0.0
        self.scale = 1.0
        self.source_name = native(source_name or '')
        self._last = 0

    def __len__(self):
        return len(self.cues)

    def shift(self, delta_ms):
        self.offset += int(delta_ms)
        return self.offset

    def set_fps(self, sub_fps=0, video_fps=0):
        """Scale subtitle timing for a subtitle authored at another FPS."""
        try:
            sub_fps, video_fps = float(sub_fps), float(video_fps)
        except (TypeError, ValueError):
            sub_fps = video_fps = 0.0
        self.sub_fps, self.video_fps = sub_fps, video_fps
        self.scale = (sub_fps / video_fps
                      if sub_fps > 0 and video_fps > 0 else 1.0)
        self._last = 0
        return self.scale

    def at(self, position_ms):
        """The cue showing at this playback position, or None.

        Playback moves forward, so the scan resumes from the previous hit
        instead of walking the whole file for every frame.
        """
        if not self.cues:
            return None
        t = int((int(position_ms) - self.offset) / self.scale)
        if self._last >= len(self.cues) or self.cues[self._last].start > t:
            self._last = 0
        for idx in range(self._last, len(self.cues)):
            cue = self.cues[idx]
            if cue.start <= t < cue.end:
                self._last = idx
                return cue
            if cue.start > t:
                self._last = max(0, idx - 1)
                return None
        return None

    def text_at(self, position_ms):
        cue = self.at(position_ms)
        return cue.text if cue else ''
