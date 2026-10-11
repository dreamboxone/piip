# -*- coding: utf-8 -*-
"""Fault injection for RAM mounts, bounded worker logs and audit counters."""
import os
import sys
import tempfile
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from PIIP.utils.storage import on_ram
from PIIP.utils.runtimelog import ProcessLog
from PIIP.translate.audit import assess, read_decoder, read_udp_drops


def check(name, condition):
    print(('  PASS  ' if condition else '  FAIL  ') + name)
    if not condition:
        raise AssertionError(name)


with tempfile.TemporaryFile(mode='w+') as handle:
    pass
folder = tempfile.mkdtemp()
mounts = os.path.join(folder, 'mounts')
target = os.path.realpath(os.path.join(folder, 'ram'))
with open(mounts, 'w') as handle:
    handle.write('root / ext4 rw 0 0\nram %s tmpfs rw 0 0\n' % target.replace(' ', '\\040'))
check('a verified tmpfs is accepted', on_ram(target, mounts))
check('ordinary filesystem paths are rejected', not on_ram(folder, mounts))
with open(mounts, 'a') as handle:
    handle.write('disk %s ext4 rw 0 0\n' % os.path.join(target, 'disk').replace(' ', '\\040'))
check('nested persistent mounts cannot masquerade as RAM', not on_ram(os.path.join(target, 'disk'), mounts))
check('missing mount information fails closed', not on_ram(target, mounts + '.missing'))
log = os.path.join(folder, 'worker.log')
sink = ProcessLog(log, 8192)
worker = subprocess.Popen([sys.executable, '-c', "import sys; sys.stderr.write('x'*200000)"], stderr=sink)
check('a noisy worker completes without pipe blockage', worker.wait() == 0)
sink.close()
check('worker output remains bounded', 0 < os.path.getsize(log) <= 8192)
healthy = {'http': {'updated_monotonic': 100, 'last_output_monotonic': 100, 'client': True, 'dropped_kb': 0},
           'playout': {'updated_monotonic': 100, 'overflow_ms': 0, 'underruns': 0}}
check('healthy fresh transport has no faults', assess(healthy, healthy, 101) == [])
check('stale state never counts as healthy', 'http.metrics_stale' in assess(healthy, healthy, 110))
bad = dict(healthy)
bad['playout'] = dict(healthy['playout'], overflow_ms=200)
check('discarded speech is observable', 'playout.overflow_ms:+200' in assess(healthy, bad, 101))
bad['playout']['input_paused_drops'] = 53
healthy['playout']['input_paused_drops'] = 0
check('discarded source speech is observable', 'playout.input_paused_drops:+53' in assess(healthy, bad, 101))
bad['http'] = dict(healthy['http'], last_output_monotonic=90)
check('a live process with stalled media fails', 'http.output_stalled' in assess(healthy, bad, 101))
bad['relay'] = {'last_output_monotonic': 100}
check('flowing relay with stalled HTTP locates the mux boundary', 'mux.output_stalled_after_relay' in assess(healthy, bad, 101))
stuck = dict(healthy, decoder={'video_pts': 90000, 'audio_hw_ptr': 4096})
check('a stopped hardware video clock is observable', 'decoder.video_pts_not_advancing' in assess(stuck, stuck, 101))
check('a stopped hardware audio cursor is observable', 'decoder.audio_hw_ptr_not_advancing' in assess(stuck, stuck, 101))
moving = dict(stuck, decoder={'video_pts': 180000, 'audio_hw_ptr': 52096})
check('advancing hardware clocks do not imply a decoder freeze', not any(f.startswith('decoder.') for f in assess(stuck, moving, 101)))
check('unavailable hardware probes stay unknown', read_decoder(mounts + '.missing', log + '.missing') == {})
with open(log, 'w') as handle:
    handle.write('226: 00000000:4DA6 00000000:0000 07 0:0 00:0 0 0 0 41896 2 abc 99\n')
check('kernel capture loss is read independently of application queues', read_udp_drops(log).get('capture_drops') == 99)
old = dict(healthy, kernel_udp={'capture_drops': 99})
new = dict(healthy, kernel_udp={'capture_drops': 100})
check('kernel capture loss fails the audit', 'kernel_udp.capture_drops:+1' in assess(old, new, 101))
for path in (mounts, log):
    os.remove(path)
os.rmdir(folder)
