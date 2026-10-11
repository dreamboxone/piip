# -*- coding: utf-8 -*-
"""Bounded playback audit. Read counters; never restart or alter playback."""
from __future__ import print_function
import argparse
import json
import os
import time

FILES = {
    'http': '/tmp/e2dub-audio-http-state',
    'relay': '/tmp/e2dub-audio-relay-state',
    'playout': '/tmp/e2dub-audio-helper-state-playout',
    'input': '/tmp/e2dub-audio-input-state',
}
COUNTERS = {
    'http': ('dropped_kb',),
    'relay': ('live_drops_kb', 'output_drops_kb', 'cap_drops_kb'),
    'playout': ('overflow_ms', 'udp_drops', 'input_stale_drops',
                'input_queue_full_drops', 'input_disconnected_drops',
                'input_paused_drops'),
    'kernel_udp': ('capture_drops', 'dub_drops'),
}


def read_udp_drops(path='/proc/net/udp'):
    result = {}
    ports = {'4DA6': 'capture_drops', '4DA5': 'dub_drops'}
    try:
        with open(path) as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 13 or ':' not in fields[1]:
                    continue
                key = ports.get(fields[1].split(':')[-1].upper())
                if key:
                    result[key] = result.get(key, 0) + int(fields[-1])
    except (IOError, OSError, ValueError):
        pass
    return result


def read_decoder(video_path='/sys/class/tsync/pts_video',
                 audio_path='/proc/asound/card0/pcm0p/sub0/status'):
    """Optional hardware witnesses on Dreambox; missing probes stay unknown."""
    result = {}
    try:
        with open(video_path) as handle:
            value = int(handle.read().strip(), 16)
        if value != 0xffffffff:
            result['video_pts'] = value
    except (IOError, OSError, ValueError):
        pass
    try:
        with open(audio_path) as handle:
            for line in handle:
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                if key.strip() == 'hw_ptr':
                    result['audio_hw_ptr'] = int(value.strip())
                elif key.strip() == 'state':
                    result['audio_state'] = value.strip()
    except (IOError, OSError, ValueError):
        pass
    return result


def assess(previous, current, now):
    faults = []
    for name, keys in COUNTERS.items():
        for key in keys:
            old = previous.get(name, {}).get(key)
            new = current.get(name, {}).get(key)
            if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new > old:
                faults.append('%s.%s:+%s' % (name, key, new - old))
    http = current.get('http', {})
    fresh = http.get('updated_monotonic')
    output = http.get('last_output_monotonic')
    if not isinstance(fresh, (int, float)) or not 0 <= now - fresh <= 3:
        faults.append('http.metrics_stale')
    elif not http.get('client'):
        faults.append('http.no_decoder_client')
    elif not isinstance(output, (int, float)) or not 0 <= now - output <= 3:
        faults.append('http.output_stalled')
        relay = current.get('relay', {})
        last_relay_output = relay.get('last_output_monotonic')
        if isinstance(last_relay_output, (int, float)) and 0 <= now - last_relay_output <= 3:
            faults.append('mux.output_stalled_after_relay')
    playout = current.get('playout', {})
    fresh = playout.get('updated_monotonic')
    if not isinstance(fresh, (int, float)) or not 0 <= now - fresh <= 3:
        faults.append('playout.metrics_stale')
    if http.get('client'):
        decoder = current.get('decoder', {})
        before = previous.get('decoder', {})
        for key in ('video_pts', 'audio_hw_ptr'):
            value = decoder.get(key)
            if isinstance(value, (int, float)) and value == before.get(key):
                faults.append('decoder.%s_not_advancing' % key)
    return faults


def snapshot():
    result = {}
    for name, path in FILES.items():
        try:
            with open(path) as handle:
                result[name] = json.load(handle)
        except (IOError, OSError, ValueError):
            result[name] = {}
    result['decoder'] = read_decoder()
    result['kernel_udp'] = read_udp_drops()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    seconds = max(2, min(600, args.seconds))
    previous = snapshot()
    failures = 0
    speech_seen = False
    translated_seen = False
    for _ in range(seconds):
        time.sleep(1)
        tick = getattr(time, 'monotonic', None)
        now = tick() if tick else os.times()[4]
        current = snapshot()
        faults = assess(previous, current, now)
        failures += bool(faults)
        signal = current.get('input', {}).get('signal_updated_monotonic', 0)
        speech_seen = speech_seen or bool(signal and 0 <= now - signal <= 3)
        translated_seen = translated_seen or (
            current.get('playout', {}).get('played_pcm_ms', 0) >
            previous.get('playout', {}).get('played_pcm_ms', 0))
        print(json.dumps({'monotonic': now, 'faults': faults, 'metrics': current}, sort_keys=True))
        previous = current
    # Transport health cannot establish semantic translation or lip sync.
    conclusive = speech_seen and translated_seen
    print(json.dumps({'failed_samples': failures, 'source_signal_seen': speech_seen,
                      'translated_pcm_played': translated_seen,
                      'result': 'failed' if failures else 'transport_ok' if conclusive else 'inconclusive',
                      'semantic_sync': 'requires_source_and_output_recording'}))
    return 1 if failures else 0 if conclusive else 2


if __name__ == '__main__':
    raise SystemExit(main())
