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
"""Tests for subtitle parsing, timing and the search services."""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import srt
from providers import subtitles as subs

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


SAMPLE = (
    u'1\n'
    u'00:00:01,000 --> 00:00:04,000\n'
    u'First line\n'
    u'Second line\n'
    u'\n'
    u'2\n'
    u'00:00:05,500 --> 00:00:07,250\n'
    u'<i>Italic</i> text\n'
    u'\n'
    u'3\n'
    u'00:01:00,000 --> 00:01:02,000\n'
    u'{\\an8}Positioned\n'
)

# --------------------------------------------------------------------- parse
print('parsing')
cues = srt.parse(SAMPLE)
check('all cues parsed', len(cues) == 3, str(len(cues)))
check('start time in ms', cues[0].start == 1000)
check('end time in ms', cues[0].end == 4000)
check('multi-line text joined', cues[0].text == 'First line\nSecond line')
check('fractional seconds', cues[1].start == 5500 and cues[1].end == 7250)
check('html tags stripped', cues[1].text == 'Italic text', cues[1].text)
check('ass override blocks stripped', cues[2].text == 'Positioned', cues[2].text)
check('minutes carried into ms', cues[2].start == 62000 - 2000)
check('duration computed', cues[0].duration == 3000)

vtt = u'WEBVTT\n\n00:00:02.000 --> 00:00:03.000\nVTT cue\n'
check('webvtt dot separator accepted',
      len(srt.parse(vtt)) == 1 and srt.parse(vtt)[0].start == 2000)

check('empty input gives nothing', srt.parse(u'') == [])
check('garbage gives nothing', srt.parse(u'no timings here') == [])
check('cue with no text is dropped',
      srt.parse(u'1\n00:00:01,000 --> 00:00:02,000\n\n') == [])
check('zero-length cue is dropped',
      srt.parse(u'1\n00:00:01,000 --> 00:00:01,000\nx\n') == [])

unsorted_input = (u'1\n00:00:09,000 --> 00:00:10,000\nLater\n\n'
                  u'2\n00:00:01,000 --> 00:00:02,000\nEarlier\n')
check('cues sorted by time',
      [c.text for c in srt.parse(unsorted_input)] == ['Earlier', 'Later'])

# ------------------------------------------------------------------ encoding
print('\nencoding')
FA = u'سلام دنیا'
body = u'1\n00:00:01,000 --> 00:00:02,000\n%s\n' % FA
check('utf-8 decoded', srt.parse(body.encode('utf-8'))[0].text == FA)
check('utf-8 with BOM decoded',
      srt.parse(b'\xef\xbb\xbf' + body.encode('utf-8'))[0].text == FA)
# cp1256 is the Arabic codepage: it has no Farsi yeh (U+06CC), so the
# legacy-encoding check uses text that actually fits in it.
AR = u'سلام دنيا'
ar_body = u'1\n00:00:01,000 --> 00:00:02,000\n%s\n' % AR
check('windows-1256 decoded',
      srt.parse(ar_body.encode('cp1256'))[0].text == AR)
check('undecodable bytes do not raise',
      isinstance(srt.decode(b'\xff\xfe\x00\x01'), type(u'')))

# ---------------------------------------------------------------------- zip
print('\nzip archives')
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    zf.writestr('readme.txt', 'ignore me')
    # writestr wants bytes on Python 2.
    zf.writestr('movie.srt', SAMPLE.encode('utf-8'))
blob = buf.getvalue()
check('zip detected by magic bytes', blob[:2] == b'PK')
check('srt picked out of the zip', len(srt.load(blob)) == 3)
check('raw subtitle still works', len(srt.load(SAMPLE.encode('utf-8'))) == 3)

empty = io.BytesIO()
with zipfile.ZipFile(empty, 'w') as zf:
    pass
check('empty zip gives nothing', srt.from_zip(empty.getvalue()) == [])

# ------------------------------------------------------------------- lookup
print('\nlookup and sync')
s = srt.Subtitles(cues)
check('cue found inside its window', s.text_at(2000) == 'First line\nSecond line')
check('nothing between cues', s.text_at(4500) == '')
check('second cue found', s.text_at(6000) == 'Italic text')
check('nothing before the first cue', s.text_at(0) == '')
check('nothing after the last cue', s.text_at(999999) == '')
check('seeking backwards still resolves', s.text_at(2000) != '')

s2 = srt.Subtitles(cues)
check('positive offset delays the cue', s2.text_at(3000) != '')
s2.shift(2000)
check('after shifting, the old time is empty', s2.text_at(2000) == '')
check('the cue now appears later', s2.text_at(4000) != '')
check('offset accumulates', s2.shift(-1000) == 1000)

fps = srt.Subtitles(cues, source_name='release.25fps.srt')
check('subtitle source filename is retained', fps.source_name.endswith('25fps.srt'))
check('FPS scale is calculated', abs(fps.set_fps(25, 23.976) -
                                      (25.0 / 23.976)) < 0.00001)
check('FPS conversion stretches subtitle timing', fps.text_at(4100) != '')
check('Original FPS restores unscaled timing',
      fps.set_fps(0, 23.976) == 1.0 and fps.text_at(4100) == '')

check('empty subtitle set is safe', srt.Subtitles([]).text_at(1000) == '')

# ------------------------------------------------------------- title cleanup
print('\ntitle cleaning')
check('release noise stripped',
      subs.clean_title('Dune.Part.Two.2024.1080p.WEB-DL.x265') == 'Dune Part Two',
      subs.clean_title('Dune.Part.Two.2024.1080p.WEB-DL.x265'))
check('episode marker stripped',
      subs.clean_title('Show.Name.S02E07.720p.HDTV') == 'Show Name',
      subs.clean_title('Show.Name.S02E07.720p.HDTV'))
check('extension removed',
      subs.clean_title('Movie Title.mkv') == 'Movie Title')
check('brackets removed',
      subs.clean_title('Film [YTS] (2020)') == 'Film')
check('plain title untouched', subs.clean_title('Simple Name') == 'Simple Name')
check('season and episode extracted',
      subs.season_episode('Show S02E07 Pilot') == (2, 7))
check('no episode marker gives zeros',
      subs.season_episode('A Movie') == (0, 0))

# ----------------------------------------------------------------- services
print('\nservices')
finder = subs.SubtitleFinder()
check('no keys means not configured', finder.configured is False)
check('search with no services returns nothing', finder.search('x') == ([], []))

finder = subs.SubtitleFinder(opensubtitles_key='k1', subdl_key='k2')
check('both services registered',
      sorted(finder.services) == ['OpenSubtitles', 'SubDL'])


class FakeOS(object):
    def search(self, query, language, season, episode):
        return [subs.Candidate('OpenSubtitles', 'eng.srt', 'en', 500, 1),
                subs.Candidate('OpenSubtitles', 'fa-low.srt', 'fa', 10, 2)]

    def download(self, c):
        return b'downloaded'


class Broken(object):
    def search(self, *a):
        raise RuntimeError('service down')


finder.services = {'OpenSubtitles': FakeOS(), 'Broken': Broken()}
results, errors = finder.search('Some Film')
check('results merged', len(results) == 2)
check('persian ranked above english',
      results[0].language == 'fa', results[0].language)
check('a failing service is reported, not fatal',
      len(errors) == 1 and 'service down' in errors[0], str(errors))

check('download routed to the right service',
      finder.download(results[0]) == b'downloaded')
try:
    finder.download(subs.Candidate('Nope', 'x', 'fa'))
    ok = False
except subs.SubtitleError:
    ok = True
check('downloading from an unknown service raises', ok)

c = subs.Candidate('SubDL', 'file.srt', 'fa', 42, '/x.zip')
check('candidate label shows name, count and source',
      'file.srt' in c.label() and '(42)' in c.label() and '[SubDL]' in c.label(),
      c.label())

check('opensubtitles language mapped', subs.LANG_OS['Persian'] == 'fa')
check('subdl language mapped', subs.LANG_SUBDL['Persian'] == 'FA')

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
