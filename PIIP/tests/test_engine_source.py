# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
#
"""HLS master playlists are read through one rendition, never all of them."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from translate.engine import pick_variant

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


MASTER = ('#EXTM3U\n'
          '#EXT-X-STREAM-INF:BANDWIDTH=1061313,RESOLUTION=640x360\nlow/a.m3u8\n'
          '#EXT-X-STREAM-INF:BANDWIDTH=1661313,RESOLUTION=960x540\nmid/b.m3u8\n'
          '#EXT-X-STREAM-INF:AVERAGE-BANDWIDTH=900,BANDWIDTH=6221313\nhi/c.m3u8\n')
check('media playlists are left alone',
      pick_variant('#EXTM3U\n#EXTINF:10,\nseg.ts\n', 'http://h/x.m3u8') is None)
check('highest rendition by default',
      pick_variant(MASTER, 'http://h/p/index.m3u8') == (6221313, 'http://h/p/hi/c.m3u8'))
check('bandwidth cap picks the best rendition under it',
      pick_variant(MASTER, 'http://h/p/index.m3u8', 1800000)[0] == 1661313)
check('a cap below every rendition picks the lightest',
      pick_variant(MASTER, 'http://h/p/index.m3u8', 500)[0] == 1061313)
SEPARATE = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",URI="audio.m3u8"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=900000,AUDIO="aud"\nv.m3u8\n')
check('renditions with separate audio keep the master', pick_variant(SEPARATE, 'http://h/') is None)
from translate.engine import Engine
from translate.e2dub.e2dub_audio_engine import AudioEngine
import tempfile
log = os.path.join(tempfile.gettempdir(), 'piip_engine_source_test.log')
for url, hls in (('/media/hdd/film.ts', False), ('http://host/live/1.ts', False),
                 ('http://host/live/index.m3u8?token=1', True)):
    eng = Engine({'url': url, 'translate': False, 'log': log})
    eng.source_url = url
    eng.source_is_hls = '.m3u' in url
    args = eng._input_args()
    check('%s: live_start_index only for HLS' % url.split('/')[-1],
          ('-live_start_index' in args) == hls, ' '.join(args[:14]))
    check('%s: HTTP options only for HTTP' % url.split('/')[-1],
          ('-reconnect' in args) == url.startswith('http'))
live = Engine({'url': 'http://host/live/index.m3u8', 'translate': False,
               'passthrough': True, 'ingest_realtime': True, 'log': log})
args = live._input_args()
check('source pacing remains opt-in for recorded streams',
      '-re' in args and args.index('-re') < args.index('-i'))
context = {
    'ffmpeg_path': 'ffmpeg', 'is_oe_alliance': True,
    'audio_stream': '0:a:0', 'original_volume': 30,
    'dub_udp_port': 19875, 'translated_audio_pid': 258,
    'original_audio_pid': 257, 'target_language': 'fa',
    'local_service_id': 1, 'local_tsid': 1, 'local_onid': 1,
    'playback_realtime': True,
}
playback = AudioEngine({})._playback_args(context)
check('OE translated TS is read at media rate',
      playback.count('-re') == 1 and
      playback.index('-re') < playback.index('pipe:0'))
context['playback_realtime'] = False
check('legacy OE playback keeps its original rate behavior',
      '-re' not in AudioEngine({})._playback_args(context))
print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
