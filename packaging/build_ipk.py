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
"""Build an installable .ipk for OE-Alliance images (opkg).

An opkg .ipk is the same `ar` archive a .deb is, so the payload, the
maintainer scripts and the directory layout are shared with build_deb.py and
only the control stanza differs: opkg wants Depends rather than Recommends,
and it does not read Homepage or Installed-Size the way dpkg does.

One package covers arm64, armhf and mipsel: the plugin is pure Python and is
marked Architecture: all.

    python packaging/build_ipk.py
"""

from __future__ import print_function

import io
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from build_deb import (                                       # noqa: E402
    PACKAGE, VERSION, ARCH, SOURCE, POSTINST, PREINST, PRERM,
    _info, ar_member, build_data, collect,
)

# opkg installs into the same tree as dpkg, but it resolves dependencies
# itself, so what dpkg only recommends is named here as a requirement.
CONTROL = """Package: %(package)s
Version: %(version)s
Architecture: %(arch)s
Section: extra
Priority: optional
Maintainer: Routekernel
Source: https://github.com/dreamboxone/piip
Depends: enigma2, ffmpeg
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


def build(output=None, source=None):
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
        output = os.path.join(ROOT, 'dist',
                              '%s_%s_%s.ipk' % (PACKAGE, VERSION, ARCH))
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
        'ipk_bytes': len(blob),
    }


if __name__ == '__main__':
    result = build()
    print('%s' % result['path'])
    print('  %d files, %.1f MB installed, %.1f MB packed'
          % (result['files'], result['raw_bytes'] / 1048576.0,
             result['ipk_bytes'] / 1048576.0))
