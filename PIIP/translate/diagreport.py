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
"""Turn a diagnostics session folder into report.txt and report.json.

The yardstick is the viewer. A second only counts as "picture OK" when the
decoder's play position advanced; "translation delivered" only when the
engine mixed translated speech into that second AND the decoder was playing
it. Engine-side health is reported separately, and every picture stall is
listed with the engine and system readings around it, because the cause of
a stall is almost always visible a few seconds before it.
"""

from __future__ import print_function

import json
import os
import re
import subprocess
import time

SPEECH_RMS = 400          # ~ -38 dBFS: programme sound worth translating
TRANS_RMS = 250           # translated speech actually audible in the mix
STALL_RATIO = 0.3         # play position advanced < 30% of wall time


def load_jsonl(path):
    rows = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except IOError:
        pass
    return rows


def parse_events(path):
    rows = []
    pattern = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$')
    try:
        with open(path) as fh:
            for line in fh:
                m = pattern.match(line.rstrip('\n'))
                if m:
                    t = time.mktime(time.strptime(m.group(1), '%Y-%m-%d %H:%M:%S'))
                    rows.append((t, m.group(2)))
    except IOError:
        pass
    return rows


def segments(events, t_end):
    """[(start, end, label, translate)] from the player's start/close notes."""
    out, current = [], None
    for t, text in events:
        if text.startswith('player start '):
            m = re.match(r'player start (.*) translate=(\w+)', text)
            name = m.group(1) if m else text[13:]
            if current and current[1] == name:
                continue                      # a retry of the same playback
            if current:
                out.append((current[0], t, current[1], current[2]))
            current = (t, name, bool(m and m.group(2) == 'True'))
        elif text.startswith('player close') and current:
            out.append((current[0], t, current[1], current[2]))
            current = None
    if current:
        out.append((current[0], t_end, current[1], current[2]))
    return out


def runs(flags):
    """Lengths of consecutive True runs."""
    result, n = [], 0
    for f in flags:
        if f:
            n += 1
        elif n:
            result.append(n)
            n = 0
    if n:
        result.append(n)
    return result


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def within(rows, t0, t1):
    return [r for r in rows if t0 <= r.get('t', 0) < t1]


def decoder_stats(player, t0):
    playing = [r for r in player if 'pos_delta' in r and r.get('wall_delta')]
    first = next((r['t'] for r in playing if r['pos_delta'] > 0.05), None)
    after = [r for r in playing if first is not None and r['t'] >= first]
    ok = [r['pos_delta'] >= STALL_RATIO * r['wall_delta'] for r in after]
    stall_runs = runs([not x for x in ok])
    stalls = []
    run_start = None
    for r, good in zip(after, ok):
        if not good and run_start is None:
            run_start = r['t']
        elif good and run_start is not None:
            stalls.append((run_start, r['t']))
            run_start = None
    if run_start is not None:
        stalls.append((run_start, after[-1]['t']))
    return {
        'samples': len(player),
        'startup_s': round(first - t0, 1) if first else None,
        'seconds_after_start': int(sum(r['wall_delta'] for r in after)),
        'picture_ok_pct': pct(sum(ok), len(ok)),
        'stalls': len(stall_runs),
        'stall_seconds': sum(stall_runs),
        'longest_stall_s': max(stall_runs) if stall_runs else 0,
        'no_service_samples': len([r for r in player if not r.get('service')]),
        'stall_windows': stalls,
    }


def frame_stats(frames):
    good = [f for f in frames if f.get('md5')]
    if not good:
        return {'frames': 0}
    sizes = sorted(f['size'] for f in good)
    median = sizes[len(sizes) // 2]
    frozen = [good[i]['md5'] == good[i - 1]['md5'] for i in range(1, len(good))]
    black = [f['size'] < max(900, median * 0.35) for f in good]
    return {'frames': len(good), 'identical_consecutive_pct': pct(sum(frozen), len(frozen)),
            'frozen_runs_ge3': len([n for n in runs(frozen) if n >= 2]),
            'dark_or_empty_pct': pct(sum(black), len(black)),
            'grab_errors': len(frames) - len(good)}


def engine_stats(engine):
    if not engine:
        return {}
    n = len(engine)
    flowing = [r for r in engine if r.get('flowing')]
    speech = [r for r in flowing if r.get('orig_rms', 0) >= SPEECH_RMS]
    present = [r for r in speech if r.get('present_ms', 0) >= 300 and
               r.get('trans_rms', 0) >= TRANS_RMS]
    last = engine[-1]
    peak = lambda k: max([r.get(k, 0) for r in engine] or [0])
    return {
        'seconds': n,
        'mode': last.get('mode'),
        'flowing_pct': pct(len(flowing), n),
        'ingest_stall_s': len([r for r in flowing if not r.get('v_in')]),
        # Seconds in which not one byte reached the decoder socket: the
        # picture freezes however well the consumer's buffer hides it.
        'decoder_starved_s': len([r for r in flowing if not r.get('client_out')]),
        'decoder_starved_runs': len([k for k in runs([not r.get('client_out')
                                                      for r in flowing]) if k >= 2]),
        'rebuffers': sum(r.get('rebuffer', 0) for r in engine),
        'source_restarts': last.get('restarts', 0),
        'extra_delay_max_s': peak('extra_delay'),
        'late_dropped_ms': last.get('late_dropped_ms', 0),
        'gemini_input_dropped_s': last.get('gem_dropped_in_s', 0),
        'gemini_stale_skipped_s': last.get('gem_stale_s', 0),
        'gemini_send_max_ms': peak('gem_send_ms'),
        'mux_out_stall_s': len([r for r in flowing if not r.get('mux_out')]),
        'client_send_max_ms': peak('client_send_ms'),
        'client_send_over_500ms_s': len([r for r in engine if r.get('client_send_ms', 0) > 500]),
        'client_drops': sum(r.get('client_drop', 0) for r in engine),
        'client_attach': sum(r.get('client_attach', 0) for r in engine),
        'pcm_starved_ticks': sum(r.get('pcm_starved', 0) for r in engine),
        'clock_late_max_ms': peak('clock_late_max_ms'),
        'pcm_write_max_ms': peak('pcm_write_ms'),
        'video_write_max_ms': peak('v_write_ms'),
        'gemini_feed_max_ms': peak('gem_feed_ms'),
        'gemini_feed_over_200ms_s': len([r for r in engine if r.get('gem_feed_ms', 0) > 200]),
        'gemini_connected_pct': pct(len([r for r in engine if r.get('gem_connected')]), n),
        'gemini_sessions': last.get('gem_sessions', 0),
        'gemini_errors': last.get('gem_errors', 0),
        'gemini_sent_s': round(last.get('gem_sent_total', 0) / 32000.0, 1),
        'gemini_received_s': round(last.get('gem_recv_total', 0) / 48000.0, 1),
        'translated_mixed_s': round(sum(r.get('present_ms', 0) for r in engine) / 1000.0, 1),
        'speech_seconds': len(speech),
        'speech_with_translation_s': len(present),
        'backlog_max_s': peak('backlog'),
        'translation_dropped_ms': last.get('dropped_ms', 0),
        'cpu_engine_max': peak('cpu_engine'),
        'cpu_ffin_max': peak('cpu_ffin'),
        'cpu_mux_max': peak('cpu_mux'),
        'last_state': last.get('gemini'),
    }


def viewer_translation(engine, player):
    """Speech seconds where translated audio was mixed and the decoder played."""
    progress = {}
    for r in player:
        if 'pos_delta' in r and r.get('wall_delta'):
            progress[int(r['t'])] = r['pos_delta'] >= STALL_RATIO * r['wall_delta']
    speech = delivered = 0
    for r in engine:
        if not r.get('flowing') or r.get('orig_rms', 0) < SPEECH_RMS:
            continue
        sec = int(r['t'])
        playing = progress.get(sec, progress.get(sec - 1, progress.get(sec + 1)))
        speech += 1
        if (playing and r.get('present_ms', 0) >= 300 and
                r.get('trans_rms', 0) >= TRANS_RMS):
            delivered += 1
    return speech, delivered


def context(t, engine, system, player):
    """Readings from 6 s before a stall to 2 s into it."""
    lines = []
    for r in within(engine, t - 6, t + 3):
        lines.append('    %s eng v_in=%-6s mux=%-6s send=%-4sms drop=%s starved=%s '
                     'late=%sms gem=%sms cpu e/f/m=%s/%s/%s backlog=%s' % (
                         time.strftime('%H:%M:%S', time.localtime(r['t'])),
                         r.get('v_in', 0) // 1024, r.get('mux_out', 0) // 1024,
                         r.get('client_send_ms', 0), r.get('client_drop', 0),
                         r.get('pcm_starved', 0), r.get('clock_late_max_ms', 0),
                         r.get('gem_feed_ms', 0), r.get('cpu_engine', '-'),
                         r.get('cpu_ffin', '-'), r.get('cpu_mux', '-'),
                         r.get('backlog', 0)))
    for r in within(system, t - 3, t + 2):
        lines.append('    %s sys cpu=%s%% e2=%s%% load=%s rx=%skbps' % (
            time.strftime('%H:%M:%S', time.localtime(r['t'])), r.get('cpu'),
            r.get('cpu_enigma2'), r.get('load'), r.get('rx_kbps')))
    for r in within(player, t - 2, t + 3):
        lines.append('    %s dec pos=%s d=%s buf=%s' % (
            time.strftime('%H:%M:%S', time.localtime(r['t'])), r.get('pos'),
            r.get('pos_delta'), r.get('buffer')))
    return lines


def ts_analysis(folder):
    path = os.path.join(folder, 'output.ts')
    if not os.path.exists(path) or os.path.getsize(path) < 188 * 100:
        return None
    result = {'bytes': os.path.getsize(path)}
    try:
        out = subprocess.Popen(
            ['ffprobe', '-v', 'error', '-show_entries',
             'packet=stream_index,pts_time', '-of', 'csv=p=0', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[0]
        if isinstance(out, bytes):
            out = out.decode('utf-8', 'replace')
        last, gaps, first, lastpts = {}, {}, {}, {}
        for line in out.splitlines():
            parts = line.split(',')
            if len(parts) < 2 or parts[1] in ('', 'N/A'):
                continue
            idx, pts = parts[0], float(parts[1])
            if idx in last and pts - last[idx] > 0.5:
                gaps.setdefault(idx, []).append(round(pts - last[idx], 2))
            first.setdefault(idx, pts)
            last[idx] = pts
        result['streams'] = dict((i, {'first': round(first[i], 2),
                                      'last': round(last[i], 2),
                                      'gaps_over_0.5s': len(gaps.get(i, [])),
                                      'largest_gap': max(gaps.get(i, [0]))})
                                 for i in last)
    except Exception as exc:
        result['error'] = str(exc)
    try:
        err = subprocess.Popen(
            ['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-map', '0:a:0',
             '-af', 'silencedetect=n=-45dB:d=1', '-f', 'null', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[1]
        if isinstance(err, bytes):
            err = err.decode('utf-8', 'replace')
        silences = [float(x) for x in re.findall(r'silence_duration: ([\d.]+)', err)]
        result['delivered_audio_silences_over_1s'] = len(silences)
        result['delivered_audio_silent_s'] = round(sum(silences), 1)
    except Exception as exc:
        result['audio_error'] = str(exc)
    return result


def write(folder):
    if not folder or not os.path.isdir(folder):
        return 'no session folder'
    engine = load_jsonl(os.path.join(folder, 'engine.jsonl'))
    player = load_jsonl(os.path.join(folder, 'player.jsonl'))
    system = load_jsonl(os.path.join(folder, 'system.jsonl'))
    frames = load_jsonl(os.path.join(folder, 'frames.jsonl'))
    events = parse_events(os.path.join(folder, 'events.log'))
    t_end = max([r.get('t', 0) for r in engine + player + system] or [time.time()])
    segs = segments(events, t_end) or [(min([r.get('t', t_end) for r in player + engine] or [t_end]),
                                        t_end, os.path.basename(folder), bool(engine))]
    report = {'folder': folder, 'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
              'segments': []}
    lines = ['PIIP playback diagnosis', '=' * 60, 'folder    : %s' % folder,
             'generated : %s' % report['generated'], '']
    pre = os.path.join(folder, 'preflight.txt')
    if os.path.exists(pre):
        lines += ['PREFLIGHT', open(pre).read().rstrip(), '']
    for t0, t1, name, translate in segs:
        seg_player = within(player, t0, t1 + 1)
        seg_engine = within(engine, t0, t1 + 1)
        seg_frames = within(frames, t0, t1 + 1)
        seg_system = within(system, t0, t1 + 1)
        dec = decoder_stats(seg_player, t0)
        eng = engine_stats(seg_engine)
        frm = frame_stats(seg_frames)
        speech, delivered = viewer_translation(seg_engine, seg_player)
        seg_events = [(t, e) for t, e in events if t0 - 1 <= t <= t1 + 1]
        retries = len([e for _t, e in seg_events if 'retry' in e])
        eofs = len([e for _t, e in seg_events if 'evEOF' in e])
        seg = {'name': name, 'translate': translate,
               'start': time.strftime('%H:%M:%S', time.localtime(t0)),
               'duration_s': int(t1 - t0), 'decoder': dict(dec),
               'frames': frm, 'engine': eng, 'retries': retries, 'eof_events': eofs,
               'speech_seconds': speech, 'speech_translated_for_viewer_s': delivered,
               'translation_success_pct': pct(delivered, speech)}
        seg['decoder'].pop('stall_windows', None)
        report['segments'].append(seg)
        lines += ['-' * 60,
                  'SEGMENT %s  (%s, %ds, translation %s)' % (
                      name, seg['start'], seg['duration_s'], 'ON' if translate else 'OFF'),
                  '',
                  'WHAT THE VIEWER GOT (decoder inside Enigma2)',
                  '  picture/sound progressing : %s%% of %ss after first frame'
                  % (dec['picture_ok_pct'], dec['seconds_after_start']),
                  '  time to first picture     : %ss' % dec['startup_s'],
                  '  stalls                    : %d (total %ds, longest %ds)'
                  % (dec['stalls'], dec['stall_seconds'], dec['longest_stall_s']),
                  '  stream restarts / EOF     : %d / %d' % (retries, eofs)]
        if frm.get('frames'):
            lines.append('  video grabs               : %d, identical-to-previous %s%%, '
                         'dark %s%%' % (frm['frames'], frm['identical_consecutive_pct'],
                                        frm['dark_or_empty_pct']))
        if translate:
            lines += ['  TRANSLATION SUCCESS       : %s%%  (%d of %d seconds of programme '
                      'speech had translated speech mixed in while the decoder played)'
                      % (seg['translation_success_pct'], delivered, speech)]
        if eng:
            lines += ['', 'ENGINE',
                      '  mode %s, flowing %s%%, ingest-stall %ss, mux-output-stall %ss'
                      % (eng['mode'], eng['flowing_pct'], eng['ingest_stall_s'],
                         eng['mux_out_stall_s']),
                      '  DECODER STARVED (no bytes delivered): %ss in %s runs of 2s+'
                      % (eng['decoder_starved_s'], eng['decoder_starved_runs']),
                      '  gemini input: dropped %ss, skipped as too late %ss, slowest send %sms'
                      % (eng['gemini_input_dropped_s'], eng['gemini_stale_skipped_s'],
                         eng['gemini_send_max_ms']),
                      '  rebuffers %s (extra delay up to %ss), source restarts %s, '
                      'translation dropped as too late %sms'
                      % (eng['rebuffers'], eng['extra_delay_max_s'],
                         eng['source_restarts'], eng['late_dropped_ms']),
                      '  decoder socket: max send %sms, >500ms in %ss, drops %s, attaches %s'
                      % (eng['client_send_max_ms'], eng['client_send_over_500ms_s'],
                         eng['client_drops'], eng['client_attach']),
                      '  audio pump: starved ticks %s, clock late max %sms, pcm write max %sms, '
                      'video write max %sms' % (eng['pcm_starved_ticks'], eng['clock_late_max_ms'],
                                                eng['pcm_write_max_ms'], eng['video_write_max_ms']),
                      '  gemini: connected %s%%, sessions %s, errors %s, sent %ss, received %ss, '
                      'mixed %ss, feed max %sms (>200ms in %ss), last "%s"'
                      % (eng['gemini_connected_pct'], eng['gemini_sessions'],
                         eng['gemini_errors'], eng['gemini_sent_s'], eng['gemini_received_s'],
                         eng['translated_mixed_s'], eng['gemini_feed_max_ms'],
                         eng['gemini_feed_over_200ms_s'], eng['last_state']),
                      '  backlog max %ss, dropped %sms, cpu max engine/ffin/mux %s/%s/%s%%'
                      % (eng['backlog_max_s'], eng['translation_dropped_ms'],
                         eng['cpu_engine_max'], eng['cpu_ffin_max'], eng['cpu_mux_max'])]
        if dec['stall_windows']:
            lines += ['', 'STALLS WITH CONTEXT']
            for s0, s1 in dec['stall_windows'][:12]:
                lines.append('  stall %s .. %s (%ds)' % (
                    time.strftime('%H:%M:%S', time.localtime(s0)),
                    time.strftime('%H:%M:%S', time.localtime(s1)), int(s1 - s0)))
                lines += context(s0, seg_engine, seg_system, seg_player)
        interesting = [(t, e) for t, e in seg_events
                       if not e.startswith(('service evUpdatedInfo', 'script'))][:40]
        if interesting:
            lines += ['', 'EVENTS']
            lines += ['  %s %s' % (time.strftime('%H:%M:%S', time.localtime(t)), e)
                      for t, e in interesting]
        lines.append('')
    reference = load_jsonl(os.path.join(folder, 'reference.jsonl'))
    if reference:
        ref = decoder_stats(reference, reference[0]['t'])
        ref.pop('stall_windows', None)
        report['reference'] = ref
        lines += ['-' * 60,
                  'REFERENCE: same stream played directly, no PIIP, same minutes',
                  '  picture/sound progressing : %s%% of %ss' % (
                      ref['picture_ok_pct'], ref['seconds_after_start']),
                  '  time to first picture     : %ss' % ref['startup_s'],
                  '  stalls                    : %d (total %ds, longest %ds)'
                  % (ref['stalls'], ref['stall_seconds'], ref['longest_stall_s']),
                  '']
    ts = ts_analysis(folder)
    if ts:
        report['output_ts'] = ts
        lines += ['-' * 60, 'TS HANDED TO THE DECODER (output.ts)',
                  json.dumps(ts, indent=1, sort_keys=True), '']
    logs = os.path.join(folder, 'engine.log')
    if os.path.exists(logs):
        tail = [l for l in open(logs).read().splitlines()
                if re.search(r'error|fail|died|exited|closed|dropped|goAway|session',
                             l, re.I)][-30:]
        if tail:
            lines += ['ENGINE LOG (errors and session changes, last 30)'] + tail + ['']
    text = '\n'.join(lines) + '\n'
    with open(os.path.join(folder, 'report.txt'), 'w') as fh:
        fh.write(text)
    with open(os.path.join(folder, 'report.json'), 'w') as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    return text
