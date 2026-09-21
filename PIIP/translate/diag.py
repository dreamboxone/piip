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
"""Playback/translation test harness that keeps working without SSH.

    python diag.py preflight [--url URL]
    python diag.py start [--minutes 30] [--label NAME] [--tap-mb 300]
                         [--frames 2] [--url URL]
    python diag.py abtest --url URL [--minutes 3] [--label NAME]
    python diag.py headless --url URL [--minutes 10] [--label NAME]
                            [--translate 1] [--reference 1]
    python diag.py stop
    python diag.py status
    python diag.py report [FOLDER]          (default: newest session)

`start` and `abtest` detach from the terminal (double fork + setsid) and
write everything to a session folder on the hard disk, then write the
report there themselves when the time is up. Losing the SSH connection,
closing the terminal or restarting Enigma2 does not lose the test.

What counts is what reaches the viewer, so a watch records, next to the
engine's own metrics:
  * the decoder's play position from inside Enigma2 (utils/diagagent.py),
  * a small grab of the video plane every few seconds (freeze/black),
  * the first megabytes of the exact TS handed to the decoder (output.ts),
  * CPU, memory and network of the whole receiver.
"""

from __future__ import print_function

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN)

from utils import diaglog                                    # noqa: E402

try:
    from urllib2 import urlopen, Request                     # Python 2
except ImportError:                                          # pragma: no cover
    from urllib.request import urlopen, Request

import threading

STOP_FILE = '/tmp/piip_diag.stop'
# Python 2 can deadlock when two threads fork (Popen) at the same moment.
POPEN_LOCK = threading.Lock()
HEADLESS_MARKER = '/tmp/piip_diag.headless'
COMMAND_FILE = '/tmp/piip_diag.cmd'
GEMINI_HOST = 'generativelanguage.googleapis.com'


def jdump(path, data):
    with open(path, 'w') as fh:
        json.dump(data, fh, indent=1, sort_keys=True)


def sh(cmd, timeout=15):
    """Output of a shell command, never raising, bounded in time."""
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
            return 'timeout'
        out = proc.communicate()[0]
        return out.decode('utf-8', 'replace') if isinstance(out, bytes) else out
    except Exception as exc:
        return 'error: %s' % exc


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def settings():
    values = {}
    try:
        with open('/etc/enigma2/settings') as fh:
            for line in fh:
                if line.startswith('config.plugins.piip.'):
                    key, _, value = line.rstrip('\n').partition('=')
                    key = key[len('config.plugins.piip.'):]
                    if 'key' in key or 'pass' in key:
                        value = '(set)' if value else ''
                    values[key] = value
    except Exception:
        pass
    return values


# ---------------------------------------------------------------- preflight

def gemini_setup_check(timeout=15.0):
    """Open a real Live session and wait for setupComplete; no audio sent."""
    from utils.apikey import find
    from translate import ws
    from translate.gemini import GeminiTranslator, ENDPOINT, MODELS
    key = find(settings_raw('api_key'))[0]
    if not key:
        return {'ok': False, 'error': 'no API key'}
    model = settings_raw('model_custom').strip() or MODELS[0]
    t0 = time.time()
    try:
        conn = ws.connect('%s?key=%s' % (ENDPOINT, key), timeout=timeout)
    except Exception as exc:
        return {'ok': False, 'error': 'connect: %s' % exc, 'model': model}
    connected = time.time() - t0
    try:
        g = GeminiTranslator(key, lambda pcm: None, model=model)
        conn.send_json(g.setup_message())
        conn.sock.settimeout(timeout)
        while True:
            msg = conn.recv_json()
            if msg is None:
                return {'ok': False, 'error': 'closed before setupComplete',
                        'model': model}
            if 'setupComplete' in msg:
                return {'ok': True, 'model': model,
                        'connect_s': round(connected, 2),
                        'setup_s': round(time.time() - t0, 2)}
            if 'error' in msg:
                return {'ok': False, 'error': str(msg['error'])[:300],
                        'model': model}
    except Exception as exc:
        return {'ok': False, 'error': 'setup: %s' % exc, 'model': model}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def settings_raw(name):
    try:
        with open('/etc/enigma2/settings') as fh:
            for line in fh:
                if line.startswith('config.plugins.piip.%s=' % name):
                    return line.rstrip('\n').split('=', 1)[1]
    except Exception:
        pass
    return ''


def probe_stream(url):
    from translate import redact
    t0 = time.time()
    out = sh("ffprobe -v error -rw_timeout 8000000 -show_entries "
             "stream=codec_type,codec_name,width,height,sample_rate,channels "
             "-of compact=p=0 '%s'" % url.replace("'", ''), timeout=25)
    return {'url': redact.text(url), 'seconds': round(time.time() - t0, 1),
            'streams': [l for l in out.splitlines() if l.strip()][:8]}


def tcp_time(host, port=443, timeout=5.0):
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout)
        s.close()
        return round((time.time() - t0) * 1000)
    except Exception:
        return -1


def preflight(folder, url=''):
    checks = []

    def add(name, ok, detail):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})

    add('clock is set', time.localtime().tm_year >= 2024,
        time.strftime('%Y-%m-%d %H:%M:%S'))
    load = open('/proc/loadavg').read().split()[:3]
    add('receiver is idle before the test', float(load[0]) < 2.5,
        'load %s' % ' '.join(load))
    mem = dict((l.split(':')[0], l.split(':')[1].strip())
               for l in open('/proc/meminfo') if ':' in l)
    add('free memory', True, mem.get('MemAvailable', mem.get('MemFree', '?')))
    st = os.statvfs(folder)
    free_mb = st.f_bavail * st.f_frsize // 1048576
    add('space for logs and tap', free_mb > 500, '%d MB free in %s'
        % (free_mb, folder))
    ff = sh('ffmpeg -hide_banner -version | head -1')
    add('ffmpeg present', 'ffmpeg version' in ff, ff.strip())
    add('ffprobe present', 'ffprobe version' in sh('ffprobe -version | head -1'),
        '')
    add('aac encoder', ' aac ' in sh('ffmpeg -hide_banner -encoders 2>/dev/null'
                                     ' | grep -w aac'), '')
    stale = sh("ps w | grep 'translate/engine.py' | grep -v grep")
    add('no engine left running', not stale.strip(), stale.strip()[:200])
    busy = sh("netstat -lnt 2>/dev/null | grep -E ':(8901|8902) '")
    add('engine ports free', not busy.strip(), busy.strip())
    add('enigma2 running', 'active' in sh('systemctl is-active enigma2'), '')
    ms = tcp_time(GEMINI_HOST)
    add('Gemini host reachable', ms >= 0, '%d ms TCP connect' % ms)
    gem = gemini_setup_check()
    add('Gemini Live session accepted (key + model)', gem.get('ok'),
        json.dumps(gem))
    agent_seen = os.path.exists('/usr/lib/enigma2/python/Plugins/Extensions/'
                                'PIIP/utils/diagagent.py')
    add('decoder sampler installed', agent_seen, '')
    info = {'settings': settings(), 'checks': checks}
    if url:
        info['stream'] = probe_stream(url)
        add('stream opens with ffprobe', any('video' in s for s in
                                             info['stream']['streams']),
            json.dumps(info['stream']))
    jdump(os.path.join(folder, 'preflight.json'), info)
    with open(os.path.join(folder, 'preflight.txt'), 'w') as fh:
        for c in checks:
            fh.write('%-4s %-44s %s\n' % ('OK' if c['ok'] else 'FAIL',
                                          c['check'], c['detail']))
    return checks


# -------------------------------------------------------------------- watch

class SystemSampler(object):
    def __init__(self):
        self.last_cpu = None
        self.last_net = None
        self.last_t = None
        self.e2_pid = None
        self.last_e2 = None

    @staticmethod
    def _cpu():
        with open('/proc/stat') as fh:
            parts = [int(x) for x in fh.readline().split()[1:]]
        return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)

    @staticmethod
    def _net():
        rx = tx = 0
        with open('/proc/net/dev') as fh:
            for line in fh:
                if ':' not in line:
                    continue
                name, data = line.split(':', 1)
                if name.strip() == 'lo':
                    continue
                fields = data.split()
                rx += int(fields[0])
                tx += int(fields[8])
        return rx, tx

    def _enigma_pid(self):
        if self.e2_pid and os.path.exists('/proc/%d' % self.e2_pid):
            return self.e2_pid
        for name in os.listdir('/proc'):
            if name.isdigit():
                try:
                    with open('/proc/%s/comm' % name) as fh:
                        if fh.read().strip() == 'enigma2':
                            self.e2_pid = int(name)
                            return self.e2_pid
                except Exception:
                    continue
        return None

    def sample(self):
        now = time.time()
        rec = {'t': round(now, 2),
               'load': float(open('/proc/loadavg').read().split()[0])}
        total, idle = self._cpu()
        rx, tx = self._net()
        pid = self._enigma_pid()
        e2 = None
        if pid:
            try:
                with open('/proc/%d/stat' % pid) as fh:
                    f = fh.read().rsplit(')', 1)[1].split()
                e2 = int(f[11]) + int(f[12])
                rec['e2_rss_mb'] = int(f[21]) * 4096 // 1048576
            except Exception:
                e2 = None
        if self.last_t is not None:
            dt = now - self.last_t
            dtot = max(1, total - self.last_cpu[0])
            rec['cpu'] = int(100 * (1 - float(idle - self.last_cpu[1]) / dtot))
            rec['rx_kbps'] = int((rx - self.last_net[0]) * 8 / 1000.0 / dt)
            rec['tx_kbps'] = int((tx - self.last_net[1]) * 8 / 1000.0 / dt)
            if e2 is not None and self.last_e2 is not None:
                rec['cpu_enigma2'] = int((e2 - self.last_e2) * 100.0 / 100 / dt)
        try:
            for line in open('/proc/meminfo'):
                if line.startswith('MemAvailable:'):
                    rec['mem_avail_mb'] = int(line.split()[1]) // 1024
        except Exception:
            pass
        self.last_cpu, self.last_net, self.last_t, self.last_e2 = \
            (total, idle), (rx, tx), now, e2
        return rec


def grab_frame(folder, index):
    try:
        data = urlopen('http://127.0.0.1/screenshot?format=jpg&video=1'
                       '&res=160x90&jpgquali=70', timeout=6).read()
    except Exception as exc:
        return {'t': round(time.time(), 2), 'error': str(exc)[:80]}
    name = 'frames/%06d.jpg' % index
    with open(os.path.join(folder, name), 'wb') as fh:
        fh.write(data)
    return {'t': round(time.time(), 2), 'file': name, 'size': len(data),
            'md5': hashlib.md5(data).hexdigest()}


def send_command(cmd):
    tmp = COMMAND_FILE + '.part'
    with open(tmp, 'w') as fh:
        json.dump(cmd, fh)
    os.rename(tmp, COMMAND_FILE)


def watch(folder, minutes, frames_every, script, job=None):
    """The detached loop. Ends on time, on `diag.py stop`, or on SIGTERM."""
    until = time.time() + minutes * 60.0
    stopping = [False]

    def on_term(*_args):
        stopping[0] = True
    signal.signal(signal.SIGTERM, on_term)

    events = os.path.join(folder, 'events.log')
    diaglog.append_text(events, 'watch start pid=%d minutes=%s'
                        % (os.getpid(), minutes))
    if not os.path.isdir(os.path.join(folder, 'frames')):
        os.makedirs(os.path.join(folder, 'frames'))
    system = diaglog.JsonLines(os.path.join(folder, 'system.jsonl'))
    frames = diaglog.JsonLines(os.path.join(folder, 'frames.jsonl'))
    net = diaglog.JsonLines(os.path.join(folder, 'net.jsonl'))
    journal = None
    try:
        journal = subprocess.Popen(
            'journalctl -u enigma2 -f -n 0 -o short-iso | head -c 30000000',
            shell=True, stdout=open(os.path.join(folder, 'enigma2.log'), 'w'),
            stderr=subprocess.STDOUT, preexec_fn=os.setsid)
    except Exception:
        journal = None
    sampler = SystemSampler()
    started = time.time()
    steps = sorted(script or [], key=lambda s: s.get('at', 0))
    frame_no = 0
    next_frame = next_net = started
    if job is not None:
        import threading
        worker = threading.Thread(target=job)
        worker.daemon = True
        worker.start()
    try:
        while not stopping[0] and time.time() < until:
            if os.path.exists(STOP_FILE):
                diaglog.append_text(events, 'watch stop requested')
                if job is not None:
                    worker.join(20)
                os.remove(STOP_FILE)
                break
            now = time.time()
            while steps and now - started >= steps[0].get('at', 0):
                step = steps.pop(0)
                diaglog.append_text(events, 'script %s' % json.dumps(
                    dict((k, v) for k, v in step['cmd'].items()
                         if k != 'url')))
                send_command(step['cmd'])
            try:
                system.write(sampler.sample())
            except Exception:
                pass
            if job is not None and not worker.is_alive():
                break
            if frames_every and now >= next_frame:
                frame_no += 1
                frames.write(grab_frame(folder, frame_no))
                next_frame = now + frames_every
            if now >= next_net:
                net.write({'t': round(now, 2), 'gemini_tcp_ms': tcp_time(GEMINI_HOST)})
                next_net = now + 30
            time.sleep(max(0.05, 1.0 - (time.time() - now)))
    finally:
        if job is not None and worker.is_alive():
            open(STOP_FILE, 'w').close()
            worker.join(20)
            try:
                os.remove(STOP_FILE)
            except Exception:
                pass
        kill_engine(folder)
        if script:
            send_command({'cmd': 'stop'})
            time.sleep(3)
        diaglog.append_text(events, 'watch end')
        for w in (system, frames, net):
            w.close()
        for marker in (diaglog.MARKER, HEADLESS_MARKER):
            try:
                if job is None or marker == HEADLESS_MARKER:
                    os.remove(marker)
            except Exception:
                pass
        if journal is not None:
            try:
                os.killpg(journal.pid, signal.SIGTERM)
            except Exception:
                pass
        time.sleep(2)
        try:
            from translate import diagreport
            diagreport.write(folder)
        except Exception as exc:
            import traceback
            with open(os.path.join(folder, 'report.txt'), 'w') as fh:
                fh.write('report failed: %s\n%s' % (exc, traceback.format_exc()))


# ----------------------------------------------------------------- headless

MAX_BW = [0]
GEMINI_FILTER = [None]          # None: the engine default; '' : no filter
HEADLESS_HTTP = 8921
HEADLESS_CTL = 8922


def headless_config(url, folder, translate=True):
    """What plugin.engine_config would build, read from the settings file."""
    from utils.apikey import find
    key = find(settings_raw('api_key'))[0]

    def num(name, default):
        try:
            return float(settings_raw(name) or default)
        except ValueError:
            return float(default)
    translating = bool(translate and key)
    extra = {}
    if GEMINI_FILTER[0] is not None:
        extra['gemini_filter'] = GEMINI_FILTER[0]
    cfg = {
        # A recorded file is played at its own speed, like a film.
        'url': url, 'realtime': url.startswith('/'), 'start_at': 0.0, 'duration': 0,
        'api_key': key,
        'model': settings_raw('model_custom').strip() or
                 'gemini-3.5-live-translate-preview',
        'language': settings_raw('language') or 'Persian',
        'translate': translating, 'passthrough': not translating,
        'delay': num('delay', 6), 'max_backlog': num('max_backlog', 6),
        'gain_original': num('vol_original', 30) / 100.0,
        'gain_translated': num('vol_translated', 100) / 100.0,
        'http_port': HEADLESS_HTTP, 'control_port': HEADLESS_CTL,
        'ffmpeg': settings_raw('ffmpeg') or 'ffmpeg',
        'user_agent': settings_raw('user_agent') or
                      'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3',
        'http_headers': {}, 'diag_dir': folder, 'tap_mb': 2000,
        'dump_audio': True, 'log': os.path.join(folder, 'engine-stderr.log'),
        'max_bandwidth': int(MAX_BW[0] or settings_raw('translate_max_bitrate') or 0),
    }
    cfg.update(extra)
    return cfg


def run_consumer(folder, url, name, stop_at, events, out_name='player.jsonl'):
    """A stand-in for the decoder: reads the stream at playback speed.

    ffmpeg with -re consumes the TS no faster than its timestamps, as a
    set-top decoder does; its progress (media time vs wall time) is written
    in the same shape as the in-Enigma2 sampler so the report treats both
    alike. Runs niced so it never competes with the engine or the TV.
    """
    out = diaglog.JsonLines(os.path.join(folder, out_name))
    cmd = ['nice', '-n', '10', 'ffmpeg', '-hide_banner', '-nostdin',
           '-loglevel', 'error', '-re', '-i', url, '-map', '0', '-c', 'copy',
           '-f', 'null', '-', '-progress', 'pipe:1', '-nostats']
    diaglog.append_text(events, 'consumer open %s' % name)
    with POPEN_LOCK:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=open(os.path.join(folder, 'consumer.err'), 'a'),
                                close_fds=True)
    last_pos = last_wall = None
    block = {}
    try:
        while time.time() < stop_at and not os.path.exists(STOP_FILE):
            line = proc.stdout.readline()
            if not line:
                break
            if isinstance(line, bytes):
                line = line.decode('utf-8', 'replace')
            key, _, value = line.strip().partition('=')
            block[key] = value
            if key != 'progress':
                continue
            now = time.time()
            try:
                pos = int(block.get('out_time_us') or block.get('out_time_ms') or 0) / 1e6
            except ValueError:
                pos = 0.0
            rec = {'t': round(now, 2), 'service': True, 'pos': round(pos, 3),
                   'frames': block.get('frame'), 'screen': 'headless'}
            if last_pos is not None and now - last_wall > 0.05:
                rec['pos_delta'] = round(pos - last_pos, 3)
                rec['wall_delta'] = round(now - last_wall, 3)
            last_pos, last_wall = pos, now
            out.write(rec)
            block = {}
            if value == 'end':
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
        diaglog.append_text(events, 'consumer ended rc=%s' % proc.poll())
        out.close()


def headless(folder, url, minutes, translate, reference, label):
    events = os.path.join(folder, 'events.log')
    cfg = headless_config(url, folder, translate)
    name = '%s %s' % (label, 'translate' if cfg['translate'] else 'passthrough')
    stop_at = time.time() + minutes * 60.0
    if tcp_port_open(HEADLESS_HTTP) or tcp_port_open(HEADLESS_CTL):
        diaglog.append_text(events, 'headless ports busy (engines %s); ending them'
                            % stale_engines())
        try:
            s = socket.create_connection(('127.0.0.1', HEADLESS_CTL), 2)
            s.sendall(b'{"cmd":"stop"}\n')
            s.close()
        except Exception:
            pass
        time.sleep(3)
    with POPEN_LOCK:
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'engine.py'), '-'],
                                stdin=subprocess.PIPE,
                                stdout=open(os.path.join(folder, 'engine.out'), 'w'),
                                stderr=subprocess.STDOUT, close_fds=True)
    proc.stdin.write(json.dumps(cfg).encode('utf-8'))
    proc.stdin.close()
    # Recorded so the watch can always end it, even if this thread is stuck.
    with open(os.path.join(folder, 'engine.pid'), 'w') as fh:
        fh.write(str(proc.pid))
    diaglog.append_text(events, 'player start %s translate=%s delay=%s player=headless '
                        'url-host=%s' % (name, cfg['translate'], cfg['delay'],
                                         (url.split('/') + ['', '', ''])[2]))
    for _ in range(80):
        if tcp_port_open(HEADLESS_CTL):
            break
        time.sleep(0.25)
    ref = None
    # Started after the engine: Python 2 can deadlock forking from two
    # threads at once.
    if reference:
        # The same stream played directly, without PIIP, at the same time:
        # every freeze it shows too is the network's, not translation's.
        import threading
        ref = threading.Thread(target=run_consumer, args=(
            folder, url, 'reference', stop_at, events, 'reference.jsonl'))
        ref.daemon = True
        ref.start()
    try:
        run_consumer(folder, 'http://127.0.0.1:%d/live.ts' % HEADLESS_HTTP,
                     name, stop_at, events)
        # The consumer can end early (EOF): note it, keep the engine to time.
        while time.time() < stop_at and proc.poll() is None:
            if os.path.exists(STOP_FILE):
                break
            time.sleep(1)
    finally:
        diaglog.append_text(events, 'player close')
        try:
            s = socket.create_connection(('127.0.0.1', HEADLESS_CTL), 2)
            s.sendall(b'{"cmd":"stop"}\n')
            s.close()
        except Exception:
            pass
        for _ in range(30):
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        if proc.poll() is None:
            proc.kill()


def kill_engine(folder):
    """No headless engine may outlive its test: it would hold the ports and
    the next test's viewer would silently watch the wrong engine."""
    try:
        pid = int(open(os.path.join(folder, 'engine.pid')).read().strip())
    except Exception:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except OSError:
            return
        time.sleep(2)


def stale_engines():
    """PIDs of engine processes already listening on the headless ports."""
    out = sh("ps w | grep 'translate/engine.py' | grep -v grep")
    return [int(l.split()[0]) for l in out.splitlines() if l.strip()]


def tcp_port_open(port):
    try:
        s = socket.create_connection(('127.0.0.1', port), 0.3)
        s.close()
        return True
    except Exception:
        return False


def daemonize(log_path):
    """Detach completely: survives the SSH session that started it."""
    if os.fork():
        return False
    os.setsid()
    if os.fork():
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    out = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(devnull, 0)
    os.dup2(out, 1)
    os.dup2(out, 2)
    return True


def begin(args, script=None, label='watch', job=None):
    if diaglog.active_watch() or read_json(HEADLESS_MARKER):
        print('a watch is already running: %s' % diaglog.active_watch()['dir'])
        return 1
    minutes = float(args.get('minutes') or 30)
    base = diaglog.root()
    folder = os.path.join(base, 'watch-%s-%s' % (
        time.strftime('%Y%m%d-%H%M%S'),
        ''.join(c if c.isalnum() else '_' for c in args.get('label') or label)[:32]))
    os.makedirs(folder)
    diaglog.prune(base)
    checks = preflight(folder, args.get('url', ''))
    failed = [c for c in checks if not c['ok']]
    jdump(os.path.join(folder, 'meta.json'), {
        'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'minutes': minutes,
        'label': args.get('label') or label, 'script': [
            dict(s, cmd=dict((k, v) for k, v in s['cmd'].items() if k != 'url'))
            for s in (script or [])],
        'piip_version': sh("opkg status enigma2-plugin-extensions-piip | "
                           "grep Version").strip(),
        'python': sys.version.split()[0],
    })
    jdump(HEADLESS_MARKER if job else '/dev/null', {'dir': folder,
          'until': time.time() + minutes * 60})
    if job is None:
        # Only a watch of real playback is announced to Enigma2; a headless
        # run must not pull the player or the decoder sampler into it.
        jdump(diaglog.MARKER, {'dir': folder, 'until': time.time() + minutes * 60,
                               'tap_mb': int(args.get('tap-mb') or 300)})
    print('session  : %s' % folder)
    print('preflight: %d checks, %d failed' % (len(checks), len(failed)))
    for c in failed:
        print('  FAIL %s: %s' % (c['check'], c['detail']))
    print('report   : %s/report.txt (written automatically at the end)'
          % folder)
    sys.stdout.flush()
    if daemonize(os.path.join(folder, 'watch.out')):
        try:
            watch(folder, minutes, float(args.get('frames') or 2), script,
                  job(folder) if job else None)
        finally:
            os._exit(0)
    return 0


def parse(argv):
    args, rest = {}, []
    i = 0
    while i < len(argv):
        if argv[i].startswith('--'):
            key = argv[i][2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                args[key] = argv[i + 1]
                i += 2
                continue
            args[key] = '1'
        else:
            rest.append(argv[i])
        i += 1
    return args, rest


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, (args, rest) = argv[0], parse(argv[1:])
    if cmd == 'preflight':
        folder = diaglog.new_dir('preflight')
        for c in preflight(folder, args.get('url', '')):
            print('%-4s %-44s %s' % ('OK' if c['ok'] else 'FAIL', c['check'],
                                     c['detail']))
        return 0
    if cmd == 'start':
        return begin(args)
    if cmd == 'abtest':
        url = args.get('url')
        if not url:
            print('abtest needs --url')
            return 2
        per = float(args.get('minutes') or 3)
        name = args.get('name') or 'abtest'
        script = [
            {'at': 5, 'cmd': {'cmd': 'play', 'url': url, 'name': name + ' A direct',
                              'translate': False}},
            {'at': 5 + per * 60, 'cmd': {'cmd': 'stop'}},
            {'at': 15 + per * 60, 'cmd': {'cmd': 'play', 'url': url,
                                           'name': name + ' B translate',
                                           'translate': True}},
            {'at': 15 + per * 120, 'cmd': {'cmd': 'stop'}},
        ]
        args['minutes'] = str(per * 2 + 0.6)
        return begin(args, script, 'abtest')
    if cmd == 'headless':
        url = args.get('url')
        if not url:
            print('headless needs --url')
            return 2
        minutes = float(args.get('minutes') or 10)
        args['minutes'] = str(minutes + 0.5)
        args['frames'] = '0'                  # never grab the TV picture
        translate = args.get('translate', '1') != '0'
        MAX_BW[0] = int(args.get('max-bw') or 0)
        if 'gemini-filter' in args:
            GEMINI_FILTER[0] = '' if args['gemini-filter'] == 'none' else args['gemini-filter']
        label = args.get('name') or 'headless'

        def job(folder):
            return lambda: headless(folder, url, minutes, translate,
                                    args.get('reference') == '1', label)
        return begin(args, None, args.get('label') or 'headless', job)
    if cmd == 'stop':
        watch_info = diaglog.active_watch() or read_json(HEADLESS_MARKER)
        if not watch_info:
            print('no watch running')
            return 1
        open(STOP_FILE, 'w').close()
        print('stop requested; report will be at %s/report.txt'
              % watch_info['dir'])
        return 0
    if cmd == 'status':
        watch_info = diaglog.active_watch() or read_json(HEADLESS_MARKER)
        print(json.dumps(watch_info or {'running': False}, indent=1))
        print('newest session: %s' % diaglog.latest())
        return 0
    if cmd == 'report':
        from translate import diagreport
        folder = rest[0] if rest else diaglog.latest()
        print(diagreport.write(folder))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
