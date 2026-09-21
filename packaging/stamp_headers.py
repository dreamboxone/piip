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
"""Put the copyright header on every source file, idempotently.

Re-running this must not stack headers, so an existing block is replaced
rather than appended to.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

YEAR = '2026'
HOLDER = 'Routekernel'

HEADER = u"""# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) %(year)s %(holder)s. All rights reserved.
#
# Telegram : https://t.me/routekernel1
# YouTube  : https://youtube.com/@routekernel
# Project  : https://github.com/dreamboxone/piip
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
# Unauthorised reverse engineering or removal of this notice is prohibited.
#
""" % {'year': YEAR, 'holder': HOLDER}

MARKER = 'Copyright (c) %s %s' % (YEAR, HOLDER)

CODING = re.compile(r'^#\s*-\*-\s*coding[:=]\s*[-\w.]+\s*-\*-\s*$')
SHEBANG = re.compile(r'^#!')


def strip_existing(lines):
    """Drop a leading coding line and any previous header block."""
    i = 0
    while i < len(lines):
        line = lines[i]
        if CODING.match(line) or (line.startswith('#') and
                                  ('Routekernel' in line or
                                   'PIIP —' in line or
                                   'Telegram :' in line or
                                   'YouTube  :' in line or
                                   'Project  :' in line or
                                   'Licensed under the PIIP' in line or
                                   'Unauthorised reverse engineering' in line or
                                   line.strip() == '#')):
            i += 1
            continue
        break
    return lines[i:]


def stamp(path):
    with io.open(path, encoding='utf-8') as fh:
        text = fh.read()
    lines = text.split('\n')

    shebang = ''
    if lines and SHEBANG.match(lines[0]):
        shebang = lines[0] + '\n'
        lines = lines[1:]

    body = strip_existing(lines)
    # A file that opened with a docstring keeps it flush against the header.
    while body and not body[0].strip():
        body = body[1:]

    new = shebang + HEADER + '\n'.join(body)
    if not new.endswith('\n'):
        new += '\n'
    if new == text:
        return False
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(new)
    return True


def targets(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ('__pycache__', '.git', 'dist', 'build')]
        for name in sorted(filenames):
            if name.endswith('.py'):
                yield os.path.join(dirpath, name)


def main(roots):
    changed = total = 0
    for root in roots:
        for path in targets(root):
            total += 1
            if stamp(path):
                changed += 1
                print('  stamped %s' % os.path.relpath(path, ROOT))
    print('%d files, %d updated' % (total, changed))
    return 0


if __name__ == '__main__':
    args = sys.argv[1:] or [os.path.join(ROOT, 'PIIP'),
                            os.path.join(ROOT, 'packaging')]
    sys.exit(main(args))
