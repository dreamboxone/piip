# -*- coding: utf-8 -*-
"""A burst of HLS PCM retains its media timeline through session setup."""
import os
import sys
import struct

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'translate', 'e2dub'))
sys.argv.append('--continuous-feed')
import e2dub_audio_helper as helper


def check(name, condition):
    print(('  PASS  ' if condition else '  FAIL  ') + name)
    if not condition:
        raise AssertionError(name)


# Six seconds arrive at once while Gemini is negotiating. The input gate
# remains closed, exactly as it does during a real setup or reconnect.
burst = struct.pack('<h', 3000) * (16000 * 6)
chunks = [burst, b'']
original_read = helper.os.read
helper.os.read = lambda fd, size: chunks.pop(0)
helper.steady_time = lambda: 100.0
helper.dump_pcm = lambda *args: None
helper.set_input_state = lambda *args: None
helper.INPUT_SILENCE_GATE = False
helper.TRANSLATED_OUTPUT_STARTED.set()
helper.should_probe_backlog = lambda *args: True
try:
    helper.stdin_reader()
finally:
    helper.os.read = original_read
frames = []
while not helper.INPUT_QUEUE.empty():
    frames.append(helper.INPUT_QUEUE.get_nowait())
check('setup preserves all six seconds of captured audio', len(frames) == 60)
check('source samples remain intact and in order', b''.join(f[0] for f in frames) == burst)
check('a burst retains 100 ms media spacing', all(abs(f[3] - (100.0 + i * .1)) < .00001 for i, f in enumerate(frames)))
check('queue pressure never pauses the continuous source feed', helper.FEEDING[0])
check('no setup audio is silently discarded', helper.INPUT_DISCONNECTED_DROPS[0] == 0)
check('no source frames are lost to the backlog drain', helper.INPUT_PAUSED_DROPS[0] == 0)
check('the input buffer has a finite delay-derived bound', helper.INPUT_QUEUE.maxsize == int((helper.PLAYBACK_DELAY_SECONDS + 6) * 10))
clock = helper.PCMInputClock()
check('a first segment starts at its arrival', clock.stamp(100) == 100)
check('a burst is paced by sample duration', abs(clock.stamp(100) - 100.1) < .00001)
check('a source outage does not make fresh audio stale', clock.stamp(110) == 110)
check('pacing resumes after a source outage', abs(clock.stamp(110) - 110.1) < .00001)

