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
"""Unpack the built .deb again and check it is what dpkg expects.

The build box has no dpkg to validate against, so the package is taken
apart with an independent reader and inspected field by field.
"""

import io
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, 'PIIP')
INSTALL_DIR = './usr/lib/enigma2/python/Plugins/Extensions/PIIP'

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


def read_ar(path):
    """-> ordered [(name, bytes)] parsed straight from the ar container."""
    out = []
    with open(path, 'rb') as fh:
        magic = fh.read(8)
        if magic != b'!<arch>\n':
            raise ValueError('not an ar archive: %r' % magic)
        while True:
            header = fh.read(60)
            if len(header) < 60:
                break
            name = header[0:16].decode('ascii').strip()
            end = header[58:60]
            if end != b'`\n':
                raise ValueError('bad member header terminator: %r' % end)
            size = int(header[48:58].decode('ascii').strip())
            payload = fh.read(size)
            if size % 2:
                fh.read(1)
            out.append((name.rstrip('/'), payload))
    return out


def main(deb):
    print('package: %s' % deb)
    print('size:    %.1f kB\n' % (os.path.getsize(deb) / 1024.0))

    print('container')
    members = read_ar(deb)
    names = [n for n, _ in members]
    check('ar magic and headers parse', True)
    check('exactly three members', len(members) == 3, str(names))
    check('debian-binary comes first', names[0] == 'debian-binary', names[0])
    check('control before data',
          names[1] == 'control.tar.gz' and names[2] == 'data.tar.gz', str(names))
    body = dict(members)
    check('format marker is 2.0', body['debian-binary'] == b'2.0\n',
          repr(body['debian-binary']))

    print('\ncontrol archive')
    ctar = tarfile.open(fileobj=io.BytesIO(body['control.tar.gz']))
    cnames = sorted(m.name.lstrip('./') for m in ctar.getmembers() if m.isfile())
    check('control file present', 'control' in cnames, str(cnames))
    for script in ('preinst', 'postinst', 'prerm'):
        member = ctar.getmember('./' + script)
        check('%s present' % script, member.isfile())
        check('%s is executable' % script, member.mode & 0o111 == 0o111,
              oct(member.mode))
        text = ctar.extractfile(member).read().decode()
        check('%s has a shebang' % script, text.startswith('#!/bin/sh'),
              text[:20])

    control = ctar.extractfile('./control').read().decode()
    fields = {}
    for line in control.splitlines():
        if line and not line.startswith(' ') and ':' in line:
            k, v = line.split(':', 1)
            fields[k.strip()] = v.strip()
    for key in ('Package', 'Version', 'Architecture', 'Maintainer',
                'Description', 'Installed-Size'):
        check('control has %s' % key, key in fields, str(sorted(fields)))
    check('package name is the enigma2 convention',
          fields.get('Package', '').startswith('enigma2-plugin-extensions-'),
          fields.get('Package'))
    check('architecture is all, so armhf and mipsel work too',
          fields.get('Architecture') == 'all', fields.get('Architecture'))
    check('no hard Depends that could block install',
          'Depends' not in fields, fields.get('Depends', ''))
    check('ffmpeg recommended', fields.get('Recommends') == 'ffmpeg',
          fields.get('Recommends', ''))
    check('installed size is a positive number',
          fields.get('Installed-Size', '0').isdigit()
          and int(fields['Installed-Size']) > 0,
          fields.get('Installed-Size'))
    check('description continuation lines are indented',
          all(ln.startswith(' ') for ln in control.split('Description:')[1]
              .splitlines()[1:] if ln and not ln.startswith('Installed-Size')))

    print('\ndata archive')
    dtar = tarfile.open(fileobj=io.BytesIO(body['data.tar.gz']))
    dmembers = dtar.getmembers()
    files = [m for m in dmembers if m.isfile()]
    dirs = [m for m in dmembers if m.isdir()]
    check('data archive is not empty', len(files) > 0, str(len(files)))
    check('every path is relative', all(m.name.startswith('./') for m in dmembers),
          next((m.name for m in dmembers if not m.name.startswith('./')), ''))
    check('everything installs under the plugin directory',
          all(m.name.startswith(INSTALL_DIR) for m in files),
          next((m.name for m in files if not m.name.startswith(INSTALL_DIR)), ''))
    check('parent directories are declared',
          './usr/lib/enigma2/python/Plugins/Extensions' in
          [m.name.rstrip('/') for m in dirs])
    check('owned by root', all(m.uid == 0 and m.gid == 0 for m in dmembers))
    check('owner names are root',
          all(m.uname == 'root' and m.gname == 'root' for m in dmembers))
    check('files are 0644 or 0755',
          all(m.mode in (0o644, 0o755) for m in files),
          str(sorted({oct(m.mode) for m in files})))
    check('directories are 0755', all(m.mode == 0o755 for m in dirs))

    engine = [m for m in files if m.name.endswith('translate/engine.py')]
    check('engine.py shipped', len(engine) == 1)
    check('engine.py is executable, it is spawned directly',
          bool(engine) and engine[0].mode == 0o755,
          oct(engine[0].mode) if engine else '')

    packaged = set(m.name[len(INSTALL_DIR) + 1:] for m in files)
    check('no compiled bytecode shipped',
          not any(n.endswith(('.pyc', '.pyo')) for n in packaged),
          str([n for n in packaged if n.endswith('.pyc')][:3]))
    check('no __pycache__ shipped',
          not any('__pycache__' in n for n in packaged))

    print('\ncontents')
    expected = set()
    for dirpath, dirnames, filenames in os.walk(SOURCE):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if name.endswith(('.pyc', '.pyo')) or name == 'engine_test.log':
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), SOURCE)
            expected.add(rel.replace(os.sep, '/'))
    missing = sorted(expected - packaged)
    extra = sorted(packaged - expected)
    check('every source file is packaged', not missing, str(missing[:5]))
    check('nothing unexpected is packaged', not extra, str(extra[:5]))

    for essential in ('plugin.py', 'main.py', 'icon.png', 'README.md',
                      'providers/stalker.py', 'translate/engine.py',
                      'translate/gemini.py', 'utils/apikey.py',
                      'screens/player.py'):
        check('ships %s' % essential, essential in packaged)

    check('tests are included for on-device diagnostics',
          any(n.startswith('tests/') for n in packaged))

    print('\nfile integrity')
    sample = sorted(n for n in packaged if n.endswith('.py'))[:6]
    ok = True
    for rel in sample:
        got = dtar.extractfile(INSTALL_DIR + '/' + rel).read()
        want = open(os.path.join(SOURCE, rel.replace('/', os.sep)), 'rb').read()
        if got != want:
            ok = False
            print('        mismatch in %s' % rel)
    check('extracted files match the source byte for byte', ok,
          '%d sampled' % len(sample))

    icon = dtar.extractfile(INSTALL_DIR + '/icon.png').read()
    check('icon is a valid PNG', icon[:8] == b'\x89PNG\r\n\x1a\n')

    print()
    if FAIL:
        print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
        return 1
    print('package verified: %d files, %d directories'
          % (len(files), len(dirs)))
    return 0


if __name__ == '__main__':
    from build_deb import PACKAGE, VERSION, ARCH
    default = os.path.join(ROOT, 'dist',
                           '%s_%s_%s.deb' % (PACKAGE, VERSION, ARCH))
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else default))
