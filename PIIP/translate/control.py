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
"""Client side of the engine's control socket, plus process supervision.

Used from inside Enigma2. Every call is short, non-blocking-ish and wrapped,
because nothing here may ever take the UI down.
"""

import json
import os
import socket
import subprocess
import sys
import time

try:                                     # inside the plugin package
    from ..utils.compat import devnull
except (ImportError, ValueError):        # imported standalone (tests)
    from utils.compat import devnull

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, 'engine.py')
STDERR_LOG = '/tmp/piip_engine_stderr.log'


def python_binary():
    """Some Enigma2 builds leave sys.executable empty, which would make
    every engine start fail with an unhelpful error."""
    if sys.executable and os.path.exists(sys.executable):
        return sys.executable
    for candidate in ('/usr/bin/python3', '/usr/bin/python',
                      'python3', 'python'):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            return candidate
    return 'python3'


class EngineHandle(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.http_port = int(cfg.get('http_port', 8901))
        self.control_port = int(cfg.get('control_port', 8902))

    # ------------------------------------------------------------ lifecycle

    def start(self):
        self.stop()
        cmd = [python_binary(), ENGINE, '-']
        # Never discard the engine's stderr. An engine that dies during its
        # own imports has not opened its log yet, so throwing stderr away
        # left "source engine did not start" with an empty log beside it and
        # nothing at all to go on.
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=devnull(),
            stderr=self._stderr(), close_fds=True)
        self.proc.stdin.write(json.dumps(self.cfg).encode('utf-8'))
        self.proc.stdin.close()
        return self.wait_ready()

    @staticmethod
    def _stderr():
        try:
            return open(STDERR_LOG, 'ab', 0)
        except Exception:
            return devnull()

    def failure(self):
        """What the engine last complained about, for the caller's log."""
        try:
            with open(STDERR_LOG, 'rb') as handle:
                try:
                    handle.seek(-2048, os.SEEK_END)
                except Exception:
                    pass
                lines = handle.read().decode('utf-8', 'replace').splitlines()
        except Exception:
            return ''
        for line in reversed(lines):
            line = line.strip()
            # The last line of a traceback names the error itself.
            if line and not line.startswith(('File "', 'Traceback', '~', '^')):
                return line[:300]
        return ''

    def wait_ready(self, timeout=20.0):
        """Block until the engine's HTTP port answers, so playback can start."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return False
            try:
                s = socket.create_connection(('127.0.0.1', self.control_port), 0.5)
                s.close()
                return True
            except Exception:
                time.sleep(0.25)
        return False

    def stop(self):
        if self.proc is None:
            return
        try:
            self.command({'cmd': 'stop'}, timeout=1.0)
        except Exception:
            pass
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                for _ in range(20):
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if self.proc.poll() is None:
                    self.proc.kill()
        except Exception:
            pass
        self.proc = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    # -------------------------------------------------------------- control

    def command(self, req, timeout=2.0):
        s = socket.create_connection(('127.0.0.1', self.control_port), timeout)
        try:
            s.sendall((json.dumps(req) + '\n').encode('utf-8'))
            s.settimeout(timeout)
            buf = b''
            while b'\n' not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            return json.loads(buf.decode('utf-8', 'replace').strip() or '{}')
        finally:
            try:
                s.close()
            except Exception:
                pass

    def try_command(self, req):
        try:
            return self.command(req)
        except Exception:
            return None

    def set_gain(self, original=None, translated=None):
        req = {'cmd': 'set_gain'}
        if original is not None:
            req['original'] = original
        if translated is not None:
            req['translated'] = translated
        return self.try_command(req)

    def set_delay(self, seconds):
        return self.try_command({'cmd': 'set_delay', 'seconds': seconds})

    def status(self):
        return self.try_command({'cmd': 'status'})

    def position(self):
        """Seconds into the item, or 0 when unknown."""
        st = self.status()
        try:
            return float((st or {}).get('position') or 0)
        except (TypeError, ValueError):
            return 0.0

    def seek(self, seconds):
        """Restart the pipeline at a new offset.

        There is no way to seek a live pipe, so seeking means tearing the
        two ffmpeg processes down and starting them again with -ss. It costs
        a couple of seconds of black screen, which is why the player only
        does it on an explicit key press.
        """
        seconds = max(0.0, float(seconds))
        self.cfg['start_at'] = seconds
        return self.start()

    @property
    def url(self):
        return 'http://127.0.0.1:%d/live.ts' % self.http_port
