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
"""Hand the exported bouquet over to EPGImport.

EPGImport is what puts programme data behind the receiver's own channel
list. It needs two files: a channel map tying each XMLTV id to a service
reference, and a sources file telling it where the XMLTV feed lives.
"""

import os

from .bouquet import encode_url
from .compat import replace_file

EPGIMPORT_DIR = '/etc/epgimport'
CHANNELS_FILE = 'piip.channels.xml'
SOURCES_FILE = 'piip.sources.xml'


def _xml_escape(text):
    return (str(text)
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _write(path, body):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as fh:
            fh.write(body)
        replace_file(tmp, path)
        return path
    except (IOError, OSError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


def build_channels(entries, service_type=4097):
    """entries: [(xmltv_id, url, name)] -> channels.xml text."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
    written = 0
    for xmltv_id, url, name in entries:
        if not xmltv_id or not url:
            continue
        ref = '%d:0:1:0:0:0:0:0:0:0:%s' % (int(service_type), encode_url(url))
        lines.append('  <channel id="%s">%s</channel><!-- %s -->'
                     % (_xml_escape(xmltv_id), ref, _xml_escape(name)))
        written += 1
    lines.append('</channels>')
    return '\n'.join(lines) + '\n', written


def build_sources(xmltv_url, description='PIIP'):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<sources>\n'
        '  <sourcecat sourcecatname="PIIP">\n'
        '    <source type="gen_xmltv" nocheck="1" channels="%s">\n'
        '      <description>%s</description>\n'
        '      <url><![CDATA[%s]]></url>\n'
        '    </source>\n'
        '  </sourcecat>\n'
        '</sources>\n'
        % (CHANNELS_FILE, _xml_escape(description), xmltv_url)
    )


def available(directory=EPGIMPORT_DIR):
    return os.path.isdir(directory)


def export(items, resolver_port, xmltv_url='', service_type=4097,
           directory=EPGIMPORT_DIR, keys=None):
    """Write both EPGImport files for an already-exported bouquet.

    `keys` are the bouquet map keys in the same order as `items`, so the
    service references match what the bouquet actually contains.
    """
    if not os.path.isdir(directory):
        return {'ok': False,
                'error': 'EPGImport is not installed (%s missing)' % directory}

    entries = []
    for idx, item in enumerate(items):
        xmltv_id = getattr(item, 'tvg_id', '') or ''
        if not xmltv_id:
            continue
        if keys is not None and idx < len(keys):
            url = 'http://127.0.0.1:%d/play/%s' % (int(resolver_port), keys[idx])
        else:
            url = item.url
        entries.append((xmltv_id, url, item.name))

    body, written = build_channels(entries, service_type)
    channels_path = _write(os.path.join(directory, CHANNELS_FILE), body)
    sources_path = None
    if xmltv_url:
        sources_path = _write(os.path.join(directory, SOURCES_FILE),
                              build_sources(xmltv_url))

    return {
        'ok': channels_path is not None,
        'channels': channels_path,
        'sources': sources_path,
        'mapped': written,
        'skipped': len(items) - written,
    }


def remove(directory=EPGIMPORT_DIR):
    removed = 0
    for name in (CHANNELS_FILE, SOURCES_FILE):
        try:
            os.remove(os.path.join(directory, name))
            removed += 1
        except OSError:
            pass
    return removed
