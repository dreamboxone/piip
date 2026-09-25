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
"""Build an installable .deb for the PIIP Enigma2 plugin.

Written in pure Python because the build box has no dpkg-deb: a .deb is
just an `ar` archive holding debian-binary, control.tar.gz and data.tar.gz.

The package is Architecture: all. The plugin is pure Python, so unlike the
HybridIPTV package it came from — which shipped arm64 only — this installs
on armhf and mipsel receivers too.
"""

import io
import os
import posixpath
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, 'PIIP')
RELEASE = os.path.join(ROOT, 'release', 'PIIP')

PACKAGE = 'enigma2-plugin-extensions-piip'
VERSION = '1.0.7'
ARCH = 'all'
INSTALL_DIR = 'usr/lib/enigma2/python/Plugins/Extensions/PIIP'

SKIP_DIRS = {'__pycache__', '.git', '.idea'}
SKIP_EXT = {'.pyc', '.pyo', '.orig', '.rej', '.tmp'}
SKIP_NAMES = {'.DS_Store', 'engine_test.log'}

CONTROL = """Package: %(package)s
Version: %(version)s
Architecture: %(arch)s
Section: extra
Priority: optional
Maintainer: Routekernel
Homepage: https://github.com/dreamboxone/piip
Recommends: ffmpeg
Description: IPTV player with live Persian audio translation
 Plays M3U, Xtream Codes and Stalker portal sources, and translates the
 channel audio into Persian in real time through the Gemini Live API.
 Original and translated audio are mixed with independent volume controls.
 .
 Video is stream-copied, never re-encoded, so 4K costs no more CPU than SD.
 .
 Also provides movies and series with resume, a programme guide, bouquet
 export and subtitle download.
 .
 Needs ffmpeg on the receiver plus a Gemini API key in /root/apikey.txt.
 Run "Check receiver requirements" from the plugin menu after installing.
 .
 Telegram: https://t.me/routekernel1 - YouTube: https://youtube.com/@routekernel
"""

PREINST = """#!/bin/sh
set -e
DIR=/usr/lib/enigma2/python/Plugins/Extensions/PIIP
echo ">>> PIIP: preparing install..."
if [ -d "$DIR" ]; then
    echo ">>> Removing previous version..."
    rm -rf "$DIR"
fi
exit 0
"""

POSTINST = """#!/bin/sh
set -e
echo ""
echo ">>> PIIP installed.   (c) Routekernel"
echo ""
# Root's home is /root on DreamOS and /home/root on OE-Alliance images,
# where /root does not exist at all.
HOMEDIR=/root
[ -d /root ] || HOMEDIR=/home/root
if [ ! -s /root/apikey.txt ] && [ ! -s /home/root/apikey.txt ] && [ ! -s /etc/enigma2/piip_apikey.txt ]; then
    echo "    NEXT: put your Gemini API key in $HOMEDIR/apikey.txt"
    echo "          echo 'YOUR_KEY' > $HOMEDIR/apikey.txt && chmod 600 $HOMEDIR/apikey.txt"
    echo ""
fi
if [ ! -f /root/m3u.txt ] && [ ! -f /home/root/m3u.txt ]; then
    echo "    Add your playlists to $HOMEDIR/m3u.txt (one per line)."
    echo ""
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "    WARNING: ffmpeg was not found. Playback needs it."
    echo ""
fi
echo "    Telegram: https://t.me/routekernel1"
echo "    YouTube : https://youtube.com/@routekernel"
echo ""

# The installer package is no longer needed once it is unpacked.
rm -f /tmp/enigma2-plugin-extensions-piip_*.deb 2>/dev/null || true

echo ">>> Restarting Enigma2..."
echo "    (the picture will go away for a few seconds; SSH is unaffected)"
echo ""

# In the foreground: every file is already unpacked by the time postinst
# runs, and a backgrounded restart dies with dpkg's process group before it
# ever fires. PATH is set explicitly because a package script does not get
# the login PATH, which is why "init" was not found here.
PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PATH

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^enigma2'; then
    systemctl restart enigma2 || echo "!!! systemctl restart enigma2 failed"
elif [ -x /etc/init.d/enigma2 ]; then
    /etc/init.d/enigma2 restart || echo "!!! /etc/init.d/enigma2 restart failed"
elif command -v init >/dev/null 2>&1; then
    init 4
    sleep 3
    init 3
else
    killall -9 enigma2 || true
fi

echo ">>> Done. If the picture does not come back, run: systemctl restart enigma2"

exit 0
"""

PRERM = """#!/bin/sh
set -e
echo ">>> PIIP: removing. Bouquets and settings are left in place."
echo "    To clean up fully:"
echo "      rm -f /etc/enigma2/userbouquet.piip_*.tv"
echo "      rm -f /etc/enigma2/piip_*.json"
exit 0
"""


def wanted(path, name):
    if name in SKIP_NAMES:
        return False
    if os.path.splitext(name)[1] in SKIP_EXT:
        return False
    return True


def collect(source):
    """-> sorted list of (absolute path, path inside the package)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if not wanted(full, name):
                continue
            rel = os.path.relpath(full, source).replace(os.sep, '/')
            out.append((full, posixpath.join(INSTALL_DIR, rel)))
    return out


def _info(name, size, mode, mtime, isdir=False):
    ti = tarfile.TarInfo(name)
    ti.size = size
    ti.mode = mode
    ti.mtime = mtime
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = 'root'
    ti.type = tarfile.DIRTYPE if isdir else tarfile.REGTYPE
    return ti


def build_data(files, mtime):
    """data.tar.gz with every parent directory declared, as dpkg expects."""
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode='w:gz', format=tarfile.GNU_FORMAT)

    seen = set()
    for _full, target in files:
        parts = target.split('/')
        for i in range(1, len(parts)):
            d = './' + '/'.join(parts[:i])
            if d not in seen:
                seen.add(d)
                tar.addfile(_info(d, 0, 0o755, mtime, isdir=True))

    for full, target in files:
        with open(full, 'rb') as fh:
            payload = fh.read()
        # engine.py is spawned directly, so it keeps the executable bit.
        mode = 0o755 if target.endswith('engine.py') else 0o644
        tar.addfile(_info('./' + target, len(payload), mode, mtime),
                    io.BytesIO(payload))
    tar.close()
    return buf.getvalue()


def build_control(installed_kb, mtime):
    body = CONTROL % {'package': PACKAGE, 'version': VERSION, 'arch': ARCH}
    body += 'Installed-Size: %d\n' % installed_kb
    members = [
        ('./control', body, 0o644),
        ('./preinst', PREINST, 0o755),
        ('./postinst', POSTINST, 0o755),
        ('./prerm', PRERM, 0o755),
    ]
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode='w:gz', format=tarfile.GNU_FORMAT)
    tar.addfile(_info('./', 0, 0o755, mtime, isdir=True))
    for name, text, mode in members:
        payload = text.encode('utf-8')
        tar.addfile(_info(name, len(payload), mode, mtime),
                    io.BytesIO(payload))
    tar.close()
    return buf.getvalue()


def ar_member(name, payload, mtime):
    header = (
        name.ljust(16)[:16] +
        str(int(mtime)).ljust(12)[:12] +
        '0'.ljust(6)[:6] +
        '0'.ljust(6)[:6] +
        '100644'.ljust(8)[:8] +
        str(len(payload)).ljust(10)[:10] +
        '`\n'
    ).encode('ascii')
    assert len(header) == 60, len(header)
    out = header + payload
    if len(payload) % 2:
        out += b'\n'                      # ar members are 2-byte aligned
    return out


def build(output=None, source=None, suffix=''):
    source = source or SOURCE
    if not os.path.isdir(source):
        raise SystemExit('plugin source not found: %s' % source)

    mtime = int(time.time())
    files = collect(source)
    if not files:
        raise SystemExit('no files collected from %s' % source)

    data = build_data(files, mtime)
    raw_size = sum(os.path.getsize(f) for f, _ in files)
    control = build_control(max(1, raw_size // 1024), mtime)

    blob = b'!<arch>\n'
    blob += ar_member('debian-binary', b'2.0\n', mtime)
    blob += ar_member('control.tar.gz', control, mtime)
    blob += ar_member('data.tar.gz', data, mtime)

    if output is None:
        output = os.path.join(ROOT, 'dist', '%s_%s%s_%s.deb'
                              % (PACKAGE, VERSION, suffix, ARCH))
    outdir = os.path.dirname(output)
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)
    with open(output, 'wb') as fh:
        fh.write(blob)

    return {
        'path': output,
        'source': source,
        'files': len(files),
        'raw_bytes': raw_size,
        'deb_bytes': len(blob),
        'compiled': any(t.endswith('.so') for _f, t in files),
    }


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    # --compiled packages the Cython build in release/ instead of the sources
    if '--compiled' in sys.argv:
        res = build(args[0] if args else None, source=RELEASE,
                    suffix='-compiled')
    else:
        res = build(args[0] if args else None)
    print('built  %s' % res['path'])
    print('from   %s' % res['source'])
    print('type   %s' % ('compiled (.so)' if res['compiled']
                         else 'source (.py)'))
    print('files  %d  (%.1f kB of source)'
          % (res['files'], res['raw_bytes'] / 1024.0))
    print('size   %.1f kB' % (res['deb_bytes'] / 1024.0))
