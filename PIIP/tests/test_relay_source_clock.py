# -*- coding: utf-8 -*-
"""Exercise the relay fork with six-second TS bursts and a virtual clock."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'translate', 'e2dub'))
import e2dub_relay as relay


def packet(seconds):
    ticks = int(seconds * 90000)
    data = bytearray([0x47, 1, 0, 0x30, 7, 0x10]) + bytearray(182)
    data[6:12] = bytearray([(ticks >> 25) & 255, (ticks >> 17) & 255,
                           (ticks >> 9) & 255, (ticks >> 1) & 255,
                           (ticks & 1) << 7, 0])
    return relay.to_bytes(data)


clock = [100.0]
live = []
output = []
stream = b''.join(packet(i / 100.0) for i in range(1801))


class Source(object):
    def __init__(self):
        self.offset = 0

    def read(self, size):
        # Three HLS segments arrive instantaneously, six seconds apart.
        available = min(len(stream), (int((clock[0] - 100) // 6) + 1) * 600 * 188)
        if self.offset < available:
            end = min(available, self.offset + size)
            data = stream[self.offset:end]
            self.offset = end
            clock[0] += .001
            return data
        clock[0] += .02
        if clock[0] > 128:
            relay.STOP[0] = True
        return None

    def close(self):
        pass


class Socket(object):
    def setblocking(self, value):
        pass

    def sendto(self, data, address):
        live.append((clock[0], data))
        return len(data)

    def close(self):
        pass


relay.open_input_source = lambda *args: (Source(), b'', 'test')
relay.socket.socket = lambda *args: Socket()
relay.signal.signal = lambda *args: None
relay.set_nonblocking = lambda *args: None
relay.steady_time = lambda: clock[0]
relay.set_state = lambda *args, **kwargs: None
relay.log = lambda *args: None
relay.os.write = lambda fd, data: (output.append((clock[0], data)) or len(data))
relay.run('http://test', 6, 19878, '/unused', source_pacing=True)
delayed = b''.join(data for _, data in output)
assert delayed == stream[:len(delayed)] and len(stream) - len(delayed) <= 376
print('  PASS  segment bursts preserve source bytes with at most two trailing PCR packets buffered')
assert b''.join(data for _, data in live) == stream[:len(live) * 1316]
print('  PASS  live capture receives the same ordered source bytes')
assert max(b[0] - a[0] for a, b in zip(live, live[1:])) < .2
print('  PASS  six-second source gaps do not become six-second capture gaps')
assert all(len(data) <= 1316 for _, data in live)
print('  PASS  capture uses bounded UDP datagrams')
# Match each output packet to the send time of its corresponding UDP batch.
live_times = [stamp for stamp, data in live for _ in range(len(data) // 188)]
out_times = [stamp for stamp, data in output for _ in range(len(data) // 188)]
assert all(stamp - live_times[i] >= 5.9 for i, stamp in enumerate(out_times[:len(live_times)]))
print('  PASS  both branches preserve the configured six-second separation')
