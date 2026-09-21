#!/usr/bin/env python
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
"""Judge the translation itself from a diagnostics session's audio dumps.

    python diagquality.py FOLDER [--windows 4] [--seconds 30] [--judge 1]

Uses src16.pcm/.idx (what Gemini heard, with send times) and
trans24.pcm/.idx (what came back, with arrival times):

  * latency  - the lag that best lines the speech envelope of the input up
               with the envelope of the returned speech;
  * coverage - share of input speech seconds followed by returned speech;
  * judge    - for a few windows, a Gemini text model transcribes both sides
               and scores accuracy, completeness and fluency (1-10).

Writes quality.txt and quality.json into the folder.
"""

from __future__ import print_function

import array
import base64
import io
import json
import math
import os
import struct
import sys
import time

try:
    from urllib2 import Request, urlopen                     # Python 2
except ImportError:
    from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import audioop

    def _rms(pcm):
        return audioop.rms(pcm, 2)
except ImportError:                                          # Python 3.13+
    def _rms(pcm):
        samples = array.array('h')
        samples.frombytes(pcm)
        return math.sqrt(sum(x * x for x in samples) / float(len(samples)))

SRC_RATE, TR_RATE = 16000, 24000
STEP = 0.1                     # envelope resolution, seconds
# Tried in order; the first that answers is used for the whole report.
JUDGE_MODELS = ('gemini-3-flash-preview', 'gemini-3.5-flash', 'gemini-3-flash',
                'gemini-2.5-flash', 'gemini-2.5-pro')
JUDGE_MODEL = JUDGE_MODELS[-2]


def load_idx(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 3:
                rows.append((float(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def envelope(pcm_path, idx_path, rate):
    """{time bucket: rms} on the wall-clock axis of the index."""
    idx = load_idx(idx_path)
    env = {}
    with open(pcm_path, 'rb') as fh:
        for t, off, n in idx:
            fh.seek(off)
            data = fh.read(n)
            per = int(rate * STEP) * 2
            for i in range(0, len(data) - len(data) % 2, per):
                part = data[i:i + per]
                if len(part) < 2:
                    continue
                level = _rms(part[:len(part) // 2 * 2])
                bucket = int((t + i / float(rate * 2)) / STEP)
                env[bucket] = max(env.get(bucket, 0), level)
    return env, idx


def best_lag(src, trans, max_lag_s=12.0):
    if not src or not trans:
        return None, 0.0
    keys = sorted(src)
    speech = set(k for k in keys if src[k] > 500)
    best, best_score = None, -1.0
    for lag in range(0, int(max_lag_s / STEP) + 1):
        score = 0.0
        for k in speech:
            if trans.get(k + lag, 0) > 300:
                score += 1
        if score > best_score:
            best, best_score = lag, score
    return (best * STEP if best is not None else None,
            best_score / float(len(speech)) if speech else 0.0)


def coverage(src, trans, lag, slack_s=3.0):
    """Share of 1-s input speech blocks answered by speech within lag+-slack."""
    if lag is None:
        return 0.0, 0
    secs = {}
    for k, v in src.items():
        if v > 500:
            secs[int(k * STEP)] = True
    answered = 0
    for sec in secs:
        lo = int((sec + lag - slack_s) / STEP)
        hi = int((sec + lag + slack_s + 1) / STEP)
        if any(trans.get(b, 0) > 300 for b in range(lo, hi)):
            answered += 1
    return (answered / float(len(secs)) if secs else 0.0), len(secs)


def wav(pcm, rate):
    out = io.BytesIO()
    out.write(b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ')
    out.write(struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16))
    out.write(b'data' + struct.pack('<I', len(pcm)) + pcm)
    return out.getvalue()


def cut(pcm_path, idx, t0, t1):
    parts = []
    with open(pcm_path, 'rb') as fh:
        for t, off, n in idx:
            if t0 <= t < t1:
                fh.seek(off)
                parts.append(fh.read(n))
    return b''.join(parts)


def judge(key, src_wav, tr_wav, model=JUDGE_MODEL):
    prompt = (
        'Audio 1 is a live TV broadcast segment (source language). Audio 2 is '
        'a live machine interpretation into Persian produced from audio 1 '
        'with a delay, so it may start late or be cut at the end. '
        'Return JSON only: {"source_transcript": str, "persian_transcript": str, '
        '"accuracy": 1-10, "completeness": 1-10, "fluency": 1-10, '
        '"problems": [short strings]}. Judge only the overlapping content.')
    body = {'contents': [{'parts': [
        {'text': prompt},
        {'inlineData': {'mimeType': 'audio/wav',
                        'data': base64.b64encode(src_wav).decode('ascii')}},
        {'inlineData': {'mimeType': 'audio/wav',
                        'data': base64.b64encode(tr_wav).decode('ascii')}}]}],
        'generationConfig': {'responseMimeType': 'application/json'}}
    url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:'
           'generateContent?key=%s' % (model, key))
    req = Request(url, data=json.dumps(body).encode('utf-8'),
                  headers={'Content-Type': 'application/json'})
    try:
        reply = json.loads(urlopen(req, timeout=180).read().decode('utf-8'))
        text = reply['candidates'][0]['content']['parts'][0]['text']
        result = json.loads(text)
        result['judge_model'] = model
        return result
    except Exception as exc:
        return {'error': str(exc)[:300], 'judge_model': model}


def judge_any(key, src_wav, tr_wav):
    for model in ([JUDGE[0]] if JUDGE[0] else list(JUDGE_MODELS)):
        result = judge(key, src_wav, tr_wav, model)
        if 'error' in result and '503' in result['error']:
            # Busy, not missing: one more try on the same model.
            time.sleep(5)
            result = judge(key, src_wav, tr_wav, model)
        if 'error' not in result or not ('404' in result['error'] or
                                         'not found' in result['error'].lower()):
            JUDGE[0] = model
            return result
    return result


JUDGE = [None]


def main(argv):
    folder = argv[0]
    opts = dict(zip(argv[1::2], argv[2::2]))
    windows = int(opts.get('--windows', 4))
    seconds = float(opts.get('--seconds', 30))
    src_env, src_idx = envelope(os.path.join(folder, 'src16.pcm'),
                                os.path.join(folder, 'src16.idx'), SRC_RATE)
    tr_env, tr_idx = envelope(os.path.join(folder, 'trans24.pcm'),
                              os.path.join(folder, 'trans24.idx'), TR_RATE)
    lag, match = best_lag(src_env, tr_env)
    cov, speech_secs = coverage(src_env, tr_env, lag)
    sent_s = sum(n for _t, _o, n in src_idx) / 32000.0
    recv_s = sum(n for _t, _o, n in tr_idx) / 48000.0
    result = {'lag_s': lag, 'envelope_match': round(match, 3),
              'coverage': round(cov, 3), 'speech_seconds': speech_secs,
              'sent_s': round(sent_s, 1), 'received_s': round(recv_s, 1),
              'windows': []}
    if opts.get('--judge', '1') != '0' and src_idx:
        key = opts.get('--key') or ''
        if not key:
            from utils.apikey import find
            key = find('')[0]
        start, end = src_idx[0][0] + 20, src_idx[-1][0] - seconds - 15
        span = max(0.0, end - start)
        for i in range(windows):
            t0 = start + span * (i + 0.5) / windows
            src = cut(os.path.join(folder, 'src16.pcm'), src_idx, t0, t0 + seconds)
            tr = cut(os.path.join(folder, 'trans24.pcm'), tr_idx,
                     t0 + (lag or 2), t0 + seconds + (lag or 2) + 6)
            item = {'at': time.strftime('%H:%M:%S', time.localtime(t0)),
                    'source_s': round(len(src) / 32000.0, 1),
                    'translation_s': round(len(tr) / 48000.0, 1)}
            if len(tr) < 48000:
                item['verdict'] = 'no translated speech returned for this window'
            else:
                item.update(judge_any(key, wav(src, SRC_RATE), wav(tr, TR_RATE)))
            result['windows'].append(item)
    scores = [w for w in result['windows'] if 'accuracy' in w]
    for name in ('accuracy', 'completeness', 'fluency'):
        vals = [float(w[name]) for w in scores]
        result['mean_' + name] = round(sum(vals) / len(vals), 1) if vals else None
    lines = ['PIIP translation quality', '=' * 60,
             'input sent to Gemini   : %.0f s' % result['sent_s'],
             'speech returned        : %.0f s' % result['received_s'],
             'best-fit latency       : %s s (envelope match %.0f%%)'
             % (lag, 100 * match),
             'coverage of input speech: %.0f%% of %d speech seconds'
             % (100 * cov, speech_secs),
             'judge (mean of %d windows): accuracy %s, completeness %s, fluency %s'
             % (len(scores), result['mean_accuracy'], result['mean_completeness'],
                result['mean_fluency']), '']
    for w in result['windows']:
        lines.append('-- window %s (source %ss, translation %ss)'
                     % (w['at'], w['source_s'], w['translation_s']))
        for k in ('verdict', 'error', 'accuracy', 'completeness', 'fluency',
                  'problems', 'source_transcript', 'persian_transcript'):
            if k in w:
                lines.append('   %s: %s' % (k, w[k]))
    text = '\n'.join(lines) + '\n'
    with open(os.path.join(folder, 'quality.txt'), 'wb') as fh:
        fh.write(text.encode('utf-8') if not isinstance(text, bytes) else text)
    with open(os.path.join(folder, 'quality.json'), 'w') as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    return text


if __name__ == '__main__':
    out = main(sys.argv[1:])
    try:
        print(out)
    except UnicodeEncodeError:
        print(out.encode('utf-8'))
