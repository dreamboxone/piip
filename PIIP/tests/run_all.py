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
"""Run every test and print one short summary.

Six hundred lines of PASS scrolling past an SSH session hides the two lines
that matter, so this prints a line per suite and only the failures.

    python tests/run_all.py            summary plus failures
    python tests/run_all.py -v         everything
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
VERBOSE = '-v' in sys.argv[1:]


def suites():
    return sorted(f for f in os.listdir(HERE)
                  if f.startswith('test_') and f.endswith('.py'))


def run(name):
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, name)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            cwd=PKG)
    out = proc.communicate()[0]
    if not isinstance(out, str):
        out = out.decode('utf-8', 'replace')
    return proc.returncode, out


def main():
    print('python  : %s' % sys.version.split()[0])
    print('platform: %s' % sys.platform)
    print('plugin  : %s' % PKG)
    print('')

    names = suites()
    if not names:
        print('no test files found in %s' % HERE)
        return 1

    total_pass = total_fail = 0
    broken = []
    failed_lines = []

    for name in names:
        code, out = run(name)
        passed = out.count('  PASS  ')
        failures = [ln for ln in out.split('\n') if ln.startswith('  FAIL  ')]
        crashed = 'Traceback (most recent call last)' in out

        total_pass += passed
        total_fail += len(failures)

        if crashed:
            status = 'CRASHED'
            broken.append((name, out))
        elif failures:
            status = '%d FAILED' % len(failures)
            failed_lines.extend('%s %s' % (name, f.strip()) for f in failures)
        elif code != 0:
            status = 'exit %d' % code
            broken.append((name, out))
        else:
            status = 'ok'

        print('%-24s %4d passed   %s' % (name, passed, status))
        if VERBOSE:
            print(out)

    print('')
    print('-' * 58)
    print('%d checks passed, %d failed, %d suites crashed'
          % (total_pass, total_fail, len(broken)))

    if failed_lines and not VERBOSE:
        print('')
        print('failures:')
        for line in failed_lines[:40]:
            print('  %s' % line)

    if broken and not VERBOSE:
        print('')
        for name, out in broken:
            print('=== %s ===' % name)
            tail = [ln for ln in out.split('\n') if ln.strip()][-12:]
            for line in tail:
                print('  %s' % line)

    return 1 if (total_fail or broken) else 0


if __name__ == '__main__':
    sys.exit(main())
