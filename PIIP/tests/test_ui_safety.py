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
"""Drive every screen against a strict Enigma2 stub.

An exception escaping a key handler crashes the whole receiver, so this
suite opens each screen, applies its layout and presses every key, checking
that nothing raises and that no widget is ever handed a non-str.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)                     # .../PIIP
sys.path.insert(0, HERE)
# The plugin uses relative imports, so it has to be imported as a package,
# exactly the way Enigma2 imports Plugins.Extensions.PIIP.
sys.path.insert(0, os.path.dirname(PKG))
PACKAGE = os.path.basename(PKG)

import enigma_stub
enigma_stub.install()

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


def guarded(name, fn, *args, **kwargs):
    """Run something the way Enigma2 would: any exception is a crash."""
    try:
        fn(*args, **kwargs)
        return True, ''
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)


# Imported after the stub is installed, exactly as Enigma2 would.
import importlib

_pkg = importlib.import_module(PACKAGE)


def _mod(name):
    return importlib.import_module('%s.%s' % (PACKAGE, name))


plugin_mod = _mod('plugin')
main_mod = _mod('main')
channels_mod = _mod('screens.channels')
vod_mod = _mod('screens.vod')
bouquets_mod = _mod('screens.bouquets')
setup_mod = _mod('screens.setup')
epg_mod = _mod('screens.epgscreen')
player_mod = _mod('screens.player')
subs_mod = _mod('screens.subtitlepicker')
diag_mod = _mod('screens.diagnose')
_models = _mod('providers.models')
MediaItem, LIVE, MOVIE = _models.MediaItem, _models.LIVE, _models.MOVIE

_c = plugin_mod.config.plugins.piip
Session = enigma_stub.Session

print('plugin module')
check('config tree built', hasattr(_c, 'source'))
check('Plugins() returns descriptors',
      len(plugin_mod.Plugins()) >= 1)
ok, err = guarded('engine_config', plugin_mod.engine_config, 'http://x/1.ts')
check('engine_config builds without a receiver', ok, err)
check('api_key never returns None', isinstance(plugin_mod.api_key(), str))

# ------------------------------------------------------------ the crash
print('\nthe reported crash: main menu -> Check receiver requirements')
session = Session()
screen = main_mod.FarsiMain(session)
screen.layoutFinished()

text = screen.checkRequirements()
check('checkRequirements returns a real str', isinstance(text, str),
      '%s: %r' % (type(text).__name__, str(text)[:120]))

# The receiver crashed inside MessageBox's Label, so go through it.
# It hangs off the Tools chip now rather than being a carousel entry.
ok, err = guarded('select-check', screen.toolPicked, ('Check', 'check'))
check('opening the requirements dialog does not crash', ok, err)

# ------------------------------------------------------- every menu entry
print('\nmain menu carousel: every entry')
for idx, item in enumerate(main_mod.FarsiMain.ITEMS):
    label, action, icon, hint = item[:4]
    check('menu label %r is a str' % label, isinstance(label, str))
    check('hint for %r is a str' % label, isinstance(hint, str))
    for suffix in ('.png', '_s.png'):
        art = os.path.join(PKG, 'icons', icon + suffix)
        check('artwork %s%s exists' % (icon, suffix), os.path.exists(art), art)
    s = Session()
    scr = main_mod.FarsiMain(s)
    scr.applySkin()
    scr.layoutFinished()
    scr.index = idx
    ok, err = guarded('updateUI', scr.updateUI)
    check('showing %r does not crash' % label, ok, err)
    ok, err = guarded(action, scr.select)
    check('selecting %r does not crash' % label, ok, err)

print('\ncarousel movement')
s = Session()
scr = main_mod.FarsiMain(s)
scr.applySkin()
scr.layoutFinished()
n = len(main_mod.FarsiMain.ITEMS)
scr.index = 0
scr.moveLeft()
check('moving left from the first wraps to the last', scr.index == n - 1, str(scr.index))
scr.moveRight()
check('moving right wraps back', scr.index == 0)
for _ in range(n):
    scr.moveRight()
check('a full turn returns to the start', scr.index == 0)
check('the middle icon is loaded', scr['icon_mid'].filename is not None)
check('the side icons are the small ones', scr['icon_left'].filename.endswith('_s.png')
      and scr['icon_right'].filename.endswith('_s.png'))
# Each provider brings its own wallpaper, as in the reference plugin.
check('the background is loaded', scr['bg'].filename is not None)
check('the background follows the selection',
      scr['bg'].filename.endswith(scr.item()[4]),
      '%s != %s' % (scr['bg'].filename, scr.item()[4]))
check('the name label is a str', isinstance(scr['name'].getText(), str))
check('the position dots mark the selection', '*' in scr['dots'].getText(), scr['dots'].getText())

# ------------------------------------------------------------- each screen
print('\nscreen construction and key handling')

ITEM_LIVE = MediaItem('Test Channel', 'http://x/live/1.ts', kind=LIVE,
                      item_id='1', group='News')
ITEM_MOVIE = MediaItem('Test Movie', 'http://x/movie/1.mkv', kind=MOVIE,
                       item_id='9', duration=5400, group='Action')

SCREENS = [
    ('FarsiChannels', lambda s: channels_mod.FarsiChannels(s)),
    ('FarsiMovies', lambda s: vod_mod.FarsiMovies(s)),
    ('FarsiSeries', lambda s: vod_mod.FarsiSeries(s)),
    ('FarsiBouquets', lambda s: bouquets_mod.FarsiBouquets(s)),
    ('FarsiSetup', lambda s: setup_mod.FarsiSetup(s)),
    ('FarsiEPG', lambda s: epg_mod.FarsiEPG(s, ITEM_LIVE, lambda: [])),
    ('FarsiSubtitles', lambda s: subs_mod.FarsiSubtitles(s, ITEM_MOVIE)),
    ('FarsiDiagnose', lambda s: diag_mod.FarsiDiagnose(s)),
]

for name, factory in SCREENS:
    s = Session()
    ok, err = guarded(name, factory, s)
    check('%s constructs' % name, ok, err)
    if not ok:
        continue
    scr = factory(s)
    ok, err = guarded(name, scr.applySkin)
    check('%s survives skinning' % name, ok, err)
    ok, err = guarded(name, scr.layoutFinished)
    check('%s applies its layout' % name, ok, err)

    # Screen is a dict subclass: an attribute with the same name as a dict
    # method breaks Enigma2's own skinning loop.
    shadowed = [n for n in ('items', 'keys', 'values', 'get', 'update',
                            'pop', 'clear', 'copy', 'setdefault')
                if not callable(getattr(scr, n, None))]
    check('%s shadows no dict method' % name, not shadowed, str(shadowed))

    actions = {}
    for key, widget in list(dict.items(scr)):
        if isinstance(widget, enigma_stub.ActionMap):
            actions.update(widget.actions)
    check('%s binds keys' % name, bool(actions), str(sorted(actions)))
    for keyname, fn in sorted(actions.items()):
        ok, err = guarded(keyname, fn)
        check('%s: %s does not crash' % (name, keyname), ok, err)

# ----------------------------------------------------------- the player
print('\nplayer')
s = Session()
ok, err = guarded('player', player_mod.FarsiPlayer, s, ITEM_LIVE)
check('player constructs for a live channel', ok, err)

s = Session()
p = player_mod.FarsiPlayer(s, ITEM_LIVE)
check('player skin is a str', isinstance(p.skin, str))
_player_api_key = player_mod.api_key
player_mod.api_key = lambda: ''
try:
    for keyname, fn in sorted(dict(p['actions'].actions,
                                   **p['numbers'].actions).items()):
        ok, err = guarded(keyname, fn)
        check('player: %s does not crash without an engine' % keyname, ok, err)
finally:
    player_mod.api_key = _player_api_key

s = Session()
pm = player_mod.FarsiPlayer(s, ITEM_MOVIE)
check('player constructs for a movie', True)
check('movie is seekable in the player', pm.seekable is True)
ok, err = guarded('updateProgress', pm.updateProgress)
check('progress renders for a movie', ok, err)
pm.position, pm.duration = 1200.0, 5400
pm.updateProgress()
check('time label is a str', isinstance(pm['time'].getText(), str))

pl = player_mod.FarsiPlayer(Session(), ITEM_LIVE)
ok, err = guarded('updateProgress-live', pl.updateProgress)
check('progress renders for a live channel', ok, err)
check('live shows LIVE', pl['time'].getText() == 'LIVE',
      pl['time'].getText())

class _EngineProbe(object):
    def __init__(self):
        self.stops = 0
    def stop(self):
        self.stops += 1

art_session = Session()
art_player = player_mod.FarsiPlayer(art_session, ITEM_LIVE)
art_player.applySkin()
art_player.engine = _EngineProbe()
art_session.nav.playing = 'active-service'
ok, err = guarded('artwork-ready', art_player._artworkReady,
                  {'picon': '/tmp/test-picon.png'}, None)
check('picon completion does not crash', ok, err)
check('picon completion does not stop translation engine',
      art_player.engine.stops == 0, str(art_player.engine.stops))
check('picon completion does not stop Enigma service',
      art_session.nav.playing == 'active-service',
      str(art_session.nav.playing))
engine_probe = art_player.engine
art_player.cleanup()
check('closing player stops its engine', engine_probe.stops == 1,
      str(engine_probe.stops))


# ------------------------------------------------- enigma2 threading rules
print('')
print('thread safety (a timer started off the main loop aborts Enigma2)')
import ast as _ast

_screens_dir = os.path.join(PKG, 'screens')
_offenders = []
for _name in sorted(os.listdir(_screens_dir)):
    if not _name.endswith('.py'):
        continue
    with open(os.path.join(_screens_dir, _name), 'rb') as _fh:
        _tree = _ast.parse(_fh.read(), filename=_name)
    _workers = set()
    for _node in _ast.walk(_tree):
        if isinstance(_node, _ast.Call):
            _f = _node.func
            if isinstance(_f, _ast.Attribute) and _f.attr == 'Thread':
                for _kw in _node.keywords:
                    if _kw.arg == 'target' and isinstance(_kw.value, _ast.Attribute):
                        _workers.add(_kw.value.attr)
    for _node in _ast.walk(_tree):
        if isinstance(_node, _ast.FunctionDef) and _node.name in _workers:
            for _sub in _ast.walk(_node):
                if isinstance(_sub, _ast.Call) and isinstance(_sub.func, _ast.Attribute) and _sub.func.attr == 'start':
                    _label = getattr(_sub.func.value, 'attr', '')
                    if 'timer' in _label.lower():
                        _offenders.append('%s:%d %s.start()' % (_name, _sub.lineno, _label))

check('no worker thread starts an eTimer', not _offenders, str(_offenders[:5]))

BackgroundTask = _mod('utils.uisafe').BackgroundTask
_users = []
for _name in ('channels.py', 'vod.py', 'bouquets.py', 'epgscreen.py',
              'subtitlepicker.py', 'diagnose.py'):
    with open(os.path.join(_screens_dir, _name), 'rb') as _fh:
        _src = _fh.read().decode('utf-8')
    if 'BackgroundTask(' in _src:
        _users.append(_name)
check('loading screens use BackgroundTask', len(_users) == 6, str(_users))

_t = BackgroundTask(None, lambda: 'ok', lambda r, e: None, 'unit')
check('BackgroundTask is idle before start', _t.running() is False)
check('stop() before start() is safe', _t.stop() is None)
check('result and error start empty', _t.result is None and _t.error is None)

# ------------------------------------------------------- rendered values
print('\nwidget values')
check('every setText received a str',
      all(isinstance(t, str) for t in enigma_stub.RENDERED),
      str([t for t in enigma_stub.RENDERED if not isinstance(t, str)][:3]))
check('something was actually rendered', len(enigma_stub.RENDERED) > 50,
      str(len(enigma_stub.RENDERED)))

# ------------------------------------------------- the stub is strict
print('\nstub self-check (it must catch what the receiver caught)')
# A background task must not deliver into a screen that has closed: the
# receiver showed "KeyError: 'note'" after EXIT during a portal check.
print('')
print('a result that arrives after the screen closed is dropped')
from PIIP.utils.uisafe import BackgroundTask, alive
probe = enigma_stub.Screen(Session())
probe['thing'] = enigma_stub.Label('x')
check('an open screen is alive', alive(probe))
delivered = []
task = BackgroundTask(probe, lambda: 'done', lambda r, e: delivered.append(r),
                      'probe')
task.start()
while task.running():
    pass
probe.doClose()
check('the screen is not alive once closed', not alive(probe))
ok, err = guarded('tick-after-close', task._tick)
check('the late result does not raise', ok, err)
check('and it is not delivered', delivered == [], str(delivered))

probe2 = enigma_stub.Screen(Session())
probe2['thing'] = enigma_stub.Label('x')
landed = []
task2 = BackgroundTask(probe2, lambda: 'done', lambda r, e: landed.append(r),
                       'probe2')
task2.start()
while task2.running():
    pass
task2._tick()
check('a live screen still gets its result', landed == ['done'], str(landed))

task3 = BackgroundTask(probe2, lambda: 'x', lambda r, e: landed.append('late'),
                       'probe3')
task3.start()
task3.stop()
task3._tick()
check('a stopped task delivers nothing', 'late' not in landed, str(landed))

check('alive() copes with None', not alive(None))

# Enigma2 execs anything in onLayoutFinish that is not a bound method,
# so a closure there is a TypeError and a screen that never opens. The
# stub has to be as strict, or the receiver finds it instead.
probe = enigma_stub.Screen(Session())
probe.onLayoutFinish.append(lambda: None)
ok, err = guarded('lambda-callback', probe.layoutFinished)
check('a closure in onLayoutFinish is rejected', not ok, err)
probe = enigma_stub.Screen(Session())
probe.onLayoutFinish.append(probe.doClose)
ok, err = guarded('method-callback', probe.layoutFinished)
check('a bound method is accepted', ok, err)

lbl = enigma_stub.Label('ok')
if bytes is not str:                    # on Python 2 bytes IS str
    ok, err = guarded('setText-bytes', lbl.setText, b'bytes')
    check('bytes are rejected like SWIG rejects them', not ok, err)
ok, err = guarded('setText-int', lbl.setText, 42)
check('ints are rejected', not ok)
ok, err = guarded('setText-none', lbl.setText, None)
check('None is rejected', not ok)
ok, err = guarded('setText-list', lbl.setText, ['a'])
check('lists are rejected', not ok)
ok, _ = guarded('setText-str', lbl.setText, 'fine')
check('plain str is accepted', ok)

print('')
print('every number key in the player survives being pressed')
# Enigma2 hands the digit to the handler, so a handler that takes no
# argument is a TypeError on the receiver and a key that does nothing.
from PIIP.screens import player as player_mod
from PIIP.providers.models import MediaItem, LIVE
from Components.config import config as _cfg

_pc = _cfg.plugins.piip
_pc.service_type.value = '4097'
_chan = MediaItem(name='A channel', url='http://h/live.ts', kind=LIVE)
_sess = Session()
_play = player_mod.FarsiPlayer(_sess, _chan, channels=[_chan], index=0)
_play.applySkin()
_play.layoutFinished()
numbers = _play['numbers']
for digit in sorted(numbers.actions):
    ok, err = guarded('number-%s' % digit, numbers.action,
                      'NumberActions', digit)
    check('key %s works' % digit, ok, err)

print('')
print('switching the service player while watching')
from PIIP.screens import player as player_mod
from PIIP.providers.models import MediaItem, LIVE
from Components.config import config as _cfg

_pc = _cfg.plugins.piip
_pc.service_type.value = '4097'
chan = MediaItem(name='A channel', url='http://h/live.ts', kind=LIVE)
sess = Session()
play = player_mod.FarsiPlayer(sess, chan, channels=[chan], index=0)
play.applySkin()

check('it starts on the configured player', play.stream_type == '4097',
      play.stream_type)
check('and says so on screen', play['streamtype'].getText() == '4097',
      play['streamtype'].getText())
check('serviceType is the number Enigma2 wants',
      play.serviceType() == 4097, str(play.serviceType()))

ring = play.streamTypes()
check('every configured player is offered', len(ring) >= 3, str(ring))
seen = []
for _ in range(len(ring)):
    ok, err = guarded('toggle', play.toggleStreamType)
    check('toggling does not raise', ok, err)
    seen.append(play.stream_type)
check('the ring visits every player once', sorted(seen) == sorted(ring),
      '%s vs %s' % (seen, ring))
check('and comes back to where it started', play.stream_type == '4097',
      play.stream_type)
check('the widget follows', play['streamtype'].getText() == '4097',
      play['streamtype'].getText())
check('the choice is kept for the next channel',
      _pc.service_type.value == '4097', _pc.service_type.value)

# A value typed into the setting by hand must stay in the ring, or the
# toggle would step off it and never return.
_pc.service_type.value = '8197'
sess2 = Session()
play2 = player_mod.FarsiPlayer(sess2, chan, channels=[chan], index=0)
play2.applySkin()
check('a hand-set player is honoured', play2.stream_type == '8197',
      play2.stream_type)
check('and is part of the ring', '8197' in play2.streamTypes(),
      str(play2.streamTypes()))
for _ in range(len(play2.streamTypes())):
    play2.toggleStreamType()
check('the ring returns to it', play2.stream_type == '8197',
      play2.stream_type)

# What actually matters: the reference that gets played uses the new value.
_pc.service_type.value = '4097'
sess3 = Session()
play3 = player_mod.FarsiPlayer(sess3, chan, channels=[chan], index=0)
play3.applySkin()
play3.layoutFinished()
play3.stream_type = '8193'
ok, err = guarded('playDirect', play3.playDirect)
check('playing again does not raise', ok, err)
ref = sess3.nav.playing
check('the service reference carries the new player',
      ref is not None and ref.type == 8193, str(getattr(ref, 'type', ref)))

print('')
print('Hybrid settings order and independent VOD player')
settings = setup_mod.FarsiSetup(Session())
labels = [entry[0] for entry in settings['config'].list]
hybrid_labels = [
    'OpenSubtitles API Key',
    'Download / Subtitle Directory',
    'Poster / Art Cache Directory',
    'Subtitle Position',
    'Subtitle Size',
    'Subtitle Color',
    'Default VOD Stream Type',
    'Show +18 Adult Content',
    'Items per Page (Poster Count)',
    'VOD/Series Skin Style',
]
check('Hybrid options retain their observed order',
      labels[0:10] == hybrid_labels, str(labels[0:10]))
check('translation settings are the final section',
      labels[-10] == '--- Translation ---' and
      labels[-1] == 'Translation volume', str(labels[-10:]))

_pc.service_type.value = '4097'
_pc.vod_streamtype.value = '8193'
vod_player = player_mod.FarsiPlayer(Session(), ITEM_MOVIE)
check('VOD starts with its independent configured player',
      vod_player.stream_type == '8193', vod_player.stream_type)
check('live starts with the live configured player',
      player_mod.FarsiPlayer(Session(), ITEM_LIVE).stream_type == '4097')
vod_player.applySkin()
vod_player.toggleStreamType()
check('changing the VOD player does not change live setting',
      _pc.service_type.value == '4097', _pc.service_type.value)
check('changing the VOD player is persisted in VOD setting',
      _pc.vod_streamtype.value == vod_player.stream_type,
      _pc.vod_streamtype.value)

fps_player = player_mod.FarsiPlayer(Session(), ITEM_MOVIE)
fps_player.applySkin()
_srt = __import__('PIIP.utils.srt', fromlist=['Subtitles', 'Cue'])
fps_player.subs = _srt.Subtitles([_srt.Cue(0, 1000, 'x')])
fps_player.active_video_fps = 25.0
fps_player.cycleSubtitleFPS(1)
check('subtitle FPS cycle starts at 23.976',
      fps_player.active_sub_fps == 23.976, str(fps_player.active_sub_fps))
check('Hybrid number 2 maps to subtitle sync minus',
      fps_player['numbers'].actions.get('2').wrapped == fps_player.subSyncBack)
check('Hybrid number 8 maps to subtitle sync plus',
      fps_player['numbers'].actions.get('8').wrapped == fps_player.subSyncForward)
check('Hybrid numbers 4/6 map to FPS cycling',
      fps_player['numbers'].actions.get('4').wrapped == fps_player.subFpsBack and
      fps_player['numbers'].actions.get('6').wrapped == fps_player.subFpsForward)

exit_session = Session()
exit_player = player_mod.FarsiPlayer(exit_session, ITEM_LIVE)
exit_player.leavePlayer()
check('leaving player asks for confirmation',
      bool(exit_session.dialogs) and exit_player._exit_pending)
exit_session.dialogs[-1]._callback(False)
check('declining exit keeps player open',
      not exit_player._exit_pending and not hasattr(exit_player, 'closed_with'))

play3.stream_type = 'not a number'
check('serviceType never raises on rubbish',
      play3.serviceType() == 4097, str(play3.serviceType()))

# ---------------------------------------------------- stalker parity extras
print('\nstalker: catch-up from the list, portal search, expiry line')


class _FakeStalker(object):
    def full_epg(self, channel_id, days=0):
        return []

    def short_epg(self, channel_id, size=12):
        return []

    def catchup_link(self, cmd, start, duration):
        return 'http://p/archive'

    def search_vod(self, query):
        return [MediaItem('Remote Only', kind=MOVIE, item_id='r1', group='7')]


saved_source = _c.source.value
_c.source.value = 'stalker'
try:
    s = Session()
    ch = channels_mod.FarsiChannels(s)
    ch.stalker = _FakeStalker()
    ch.channels = [MediaItem('No Archive', kind=LIVE, item_id='1', plot='c1'),
                   MediaItem('Archived', kind=LIVE, item_id='2', plot='c2',
                             archive=3)]
    ch.error = None
    ch.loaded()
    check('yellow is catch-up on the channel list',
          ch['actions'].actions.get('yellow').wrapped == ch.openCatchup)
    before = len(s.dialogs)
    ch.openCatchup()
    check('a channel without archive says so',
          len(s.dialogs) == before + 1 and
          type(s.dialogs[-1]).__name__ == 'MessageBox',
          type(s.dialogs[-1]).__name__ if s.dialogs else 'nothing')
    ch.down()
    ch.openCatchup()
    check('an archived channel opens its guide with catch-up',
          type(s.dialogs[-1]).__name__ == 'FarsiEPG' and
          s.dialogs[-1].catchup is not None,
          type(s.dialogs[-1]).__name__)

    s = Session()
    mv = vod_mod.FarsiMovies(s)
    mv.stalker = _FakeStalker()
    mv._vod_names = {'7': 'Drama'}
    mv.entries = [MediaItem('Local Film', kind=MOVIE, item_id='l1',
                            group='Action')]
    mv.error = None
    mv.loaded()
    mv.query = 'zzz'
    mv._search_query = 'zzz'
    result = mv._searchWorker()
    check('portal search runs off the UI thread and returns items',
          [i.item_id for i in result[1]] == ['r1'])
    mv._searchReady(result, None)
    check('portal results are merged and shown despite the name filter',
          [i.item_id for i in mv.visible()] == ['r1'],
          str([i.item_id for i in mv.visible()]))
    check('merged results take the category name', mv.entries[-1].group == 'Drama')
    check('the new category is offered', 'Drama' in mv.groups)
    check('status stays a str', isinstance(mv['status'].getText(), str))
    stale = mv._searchWorker()
    mv.query = 'other'
    ok, err = guarded('stale search', mv._searchReady, stale, None)
    check('an answer for an older query is ignored safely', ok, err)
finally:
    _c.source.value = saved_source

print('\nplayer guide follows a channel change')
epg_types = _mod('providers.epg')
_now = int(__import__('time').time())


def _guide(item):
    prog = epg_types.Programme(item.item_id, _now - 60, _now + 600,
                               'Show on %s' % item.name)
    return ((lambda: [prog]), (lambda: [prog]),
            (lambda programme: 'http://p/%s' % item.item_id))


zap_a = MediaItem('Chan A', 'http://x/a.ts', kind=LIVE, item_id='a')
zap_b = MediaItem('Chan B', 'http://x/b.ts', kind=LIVE, item_id='b')
s = Session()
loader, guide, catcher = _guide(zap_a)
zp = player_mod.FarsiPlayer(s, zap_a, epg_loader=loader, guide_loader=guide,
                            catchup=catcher, channels=[zap_a, zap_b],
                            index=0, epg_factory=_guide)
zp.refreshEPG()
check('first channel shows its own programme',
      'Chan A' in zp['epg'].getText(), zp['epg'].getText())
ok, err = guarded('zap', zp.nextChannel)
check('changing channel does not crash', ok, err)
zp.refreshEPG()
check('after the change the now line is the new channel\'s',
      'Chan B' in zp['epg'].getText(), zp['epg'].getText())
check('the guide loader follows the channel',
      zp.guide_loader()[0].title == 'Show on Chan B')
check('catch-up follows the channel', zp.catchup(None) == 'http://p/b')

s = Session()
bare = player_mod.FarsiPlayer(s, zap_a, epg_loader=loader,
                              channels=[zap_a, zap_b], index=0)
bare.nextChannel()
check('without a factory the stale guide is dropped, not shown',
      bare.epg_loader is None and bare.guide_loader is None
      and bare.catchup is None)

print('\nm3u: groups screen between loading and channels')
groups_mod = _mod('screens.m3ugroups')
serversetup_mod = _mod('screens.serversetup')
m3u_items = [MediaItem('One', 'http://x/1', kind=LIVE, group='News'),
             MediaItem('Two', 'http://x/2', kind=LIVE, group='Sport'),
             MediaItem('Three', 'http://x/3', kind=LIVE, group='News')]
check('group rows count channels, All first',
      groups_mod.group_rows(m3u_items) ==
      [('All channels', 3), ('News', 2), ('Sport', 1)])
check('folder artwork shipped',
      os.path.exists(os.path.join(PKG, 'icons', 'folder.png')))
s = Session()
ok, err = guarded('groups', s.open, groups_mod.FarsiM3UGroups, m3u_items)
check('groups screen opens and lays out', ok, err)
gs = s.dialogs[-1]
check('groups listed', len(gs['list'].list) == 3, str(gs['list'].list))
check('every row is a str', all(isinstance(r, str) for r in gs['list'].list))
for keyname, fn in sorted(gs['actions'].actions.items()):
    if keyname in ('ok', 'green', 'yellow', 'menu'):
        continue
    ok, err = guarded(keyname, fn)
    check('groups: %s does not crash' % keyname, ok, err)
gs['list'].moveToIndex(2)
gs.open()
opened = s.dialogs[-1]
check('OK opens the channels of that group',
      type(opened).__name__ == 'FarsiChannels', type(opened).__name__)
opened.loaded()
check('channel list starts on the chosen group',
      opened.current_group() == 'Sport', opened.current_group())
check('only that group is shown',
      [c.name for c in opened.visible()] == ['Two'])
gs.searched('thr')
found = s.dialogs[-1]
found.loaded()
check('search from the groups screen filters every channel',
      [c.name for c in found.visible()] == ['Three'])
check('the groups skin names the widgets the screen builds',
      all(('name="%s"' % w) in groups_mod.build_skin()
          for w in ('bg', 'list', 'head', 'status')))

saved_source = _c.source.value
_c.source.value = 'm3u'
try:
    s = Session()
    setup = serversetup_mod.FarsiServerSetup(s, 'm3u')
    setup._probeDone({'kind': 'm3u', 'count': 3, 'items': m3u_items}, None)
    check('connecting a playlist opens its groups',
          type(s.dialogs[-1]).__name__ == 'FarsiM3UGroups',
          type(s.dialogs[-1]).__name__ if s.dialogs else 'nothing')
finally:
    _c.source.value = saved_source

print('\nxtream/stalker: category screen between Home and the lists')
cats_mod = _mod('screens.categories')


def msg_text(dialog):
    try:
        return dialog['text'].getText()
    except Exception:
        return ''


catalogue_mod = _mod('screens.catalogue')
bouquet_mod = _mod('utils.bouquet')
SERIES_KIND = _models.SERIES
live_items = [MediaItem('News 1', 'http://x/1', kind=LIVE, group='News', item_id='1',
                        archive=0),
              MediaItem('Sport 1', 'http://x/2', kind=LIVE, group='Sport', item_id='2',
                        archive=2),
              MediaItem('News 2', 'http://x/3', kind=LIVE, group='News', item_id='3')]
film_items = [MediaItem('Newest', 'http://x/m1', kind=MOVIE, group='Drama', item_id='m1',
                        added=30),
              MediaItem('Older', 'http://x/m2', kind=MOVIE, group='Action', item_id='m2',
                        added=10)]
fake_api = object()
fetch_calls = []


def fake_fetch(kind, source=None):
    fetch_calls.append(kind)
    return (list(live_items) if kind == 'live' else list(film_items),
            {'xtream': fake_api})


real_fetch, real_save = catalogue_mod.fetch, catalogue_mod.save
catalogue_mod.fetch = fake_fetch
catalogue_mod.save = lambda kind, items: True
saved_source = _c.source.value
_c.source.value = 'xtream'
try:
    check('live rows: all channels first, then categories with counts',
          cats_mod.category_rows('live', live_items) ==
          [('All channels', 3), ('News', 2), ('Sport', 1)])
    check('film rows start with LATEST ADDED',
          cats_mod.category_rows('movies', film_items)[0] == ('LATEST ADDED', 2))
    check('skin is titled like the reference',
          'XTREAM LIVE TV CATEGORIES' in cats_mod.build_skin('live', 'xtream'))
    check('hint names the category keys and fits its tab',
          '0 - Search    MENU - Bouquet' in cats_mod.build_skin('live', 'xtream'))
    check('xtream offers SYNC DB, stalker a reload',
          'SYNC DB' in cats_mod.build_skin('live', 'xtream') and
          'RELOAD' in cats_mod.build_skin('movies', 'stalker'))

    s = Session()
    ok, err = guarded('categories', s.open, cats_mod.FarsiCategories, 'live')
    check('category screen opens', ok, err)
    cs = s.dialogs[-1]
    cs._loaded(cs._loadWorker(), None)
    check('categories listed', len(cs['list'].list) == 3, str(cs['list'].list))
    check('rows are str', all(isinstance(r, str) for r in cs['list'].list))
    check('count of categories in the header',
          cs['head'].getText() == '2 category(s) found', cs['head'].getText())
    check('0 opens search', cs['numbers'].actions.get('0').wrapped == cs.openSearch)
    check('blue syncs the database',
          cs['actions'].actions.get('blue').wrapped == cs.syncDatabase)
    for keyname in ('up', 'down', 'red'):
        ok, err = guarded(keyname, cs['actions'].actions[keyname])
        check('categories: %s does not crash' % keyname, ok, err)

    s = Session()
    cs = s.open(cats_mod.FarsiCategories, 'live')
    cs._loaded(cs._loadWorker(), None)
    cs['list'].moveToIndex(2)
    cs.open()
    opened = s.dialogs[-1]
    check('OK opens the channel list', type(opened).__name__ == 'FarsiChannels',
          type(opened).__name__)
    opened.loaded()
    check('it starts on the chosen category', opened.current_group() == 'Sport')
    check('and keeps the connected client', opened.xtream is fake_api)

    opened.openCatchup()
    check('catch-up on an archived xtream channel opens the CATCHUP guide',
          type(s.dialogs[-1]).__name__ == 'FarsiEPG' and
          s.dialogs[-1].catchup_mode, type(s.dialogs[-1]).__name__)
    s2 = Session()
    plain = s2.open(channels_mod.FarsiChannels, live_items, group='News',
                    providers={'xtream': fake_api})
    plain.loaded()
    plain.openCatchup()
    check('a channel without archive gets the reference message',
          type(s2.dialogs[-1]).__name__ == 'MessageBox' and
          'Catchup is not available' in msg_text(s2.dialogs[-1]),
          msg_text(s2.dialogs[-1]))

    s = Session()
    cs = s.open(cats_mod.FarsiCategories, 'movies')
    cs._loaded(cs._loadWorker(), None)
    cs.open()
    films = s.dialogs[-1]
    check('films open from their categories', type(films).__name__ == 'FarsiMovies')
    films.task.stop()
    before = len(fetch_calls)
    films.entries = films.fetch()
    films.error = None
    films.loaded()
    check('the film list starts on LATEST ADDED', films.current_group() == 'LATEST ADDED')
    check('newest film first', films.visible()[0].name == 'Newest')
    check('the handed-over catalogue is not fetched again',
          len(fetch_calls) == before, str(fetch_calls))

    cs.openMenuOptions()
    check('bouquet export refused for films with the reference message',
          'only allowed for Live TV' in msg_text(s.dialogs[-1]))

    s = Session()
    cs = s.open(cats_mod.FarsiCategories, 'live')
    cs._loaded(cs._loadWorker(), None)
    cs['list'].moveToIndex(1)
    cs.openMenuOptions()
    check('MENU asks before exporting a live category',
          "add the category 'News'" in msg_text(s.dialogs[-1]))
    exported = {}
    real_export = bouquet_mod.export
    bouquet_mod.export = lambda items, **kw: exported.update(items=items, **kw) or \
        {'count': len(items), 'filename': 'userbouquet.piip_x.tv'}
    try:
        result = cs._exportWorker()
    finally:
        bouquet_mod.export = real_export
    check('only that category is exported',
          [c.name for c in exported['items']] == ['News 1', 'News 2'])
    check('each category gets its own bouquet file',
          exported.get('slug') == 'xtream_news', exported.get('slug'))

    catalogue_mod.fetch = lambda kind, source=None: (_ for _ in ()).throw(
        IOError('down'))
    catalogue_mod_load = catalogue_mod.load_saved
    catalogue_mod.load_saved = lambda kind: list(live_items)
    try:
        s = Session()
        cs = s.open(cats_mod.FarsiCategories, 'live')
        cs._loaded(cs._loadWorker(), None)
        check('offline copy used when the server is down',
              len(cs.channels) == 3 and 'Offline' in cs['status'].getText(),
              cs['status'].getText())
    finally:
        catalogue_mod.load_saved = catalogue_mod_load

    s = Session()
    ser = s.open(vod_mod.FarsiMovies, preloaded=[
        MediaItem('Show', kind=SERIES_KIND, item_id='s1', group='G')])
    ser.task.stop()
    ser.entries = ser.fetch()
    ser.error = None
    ser.loaded()
    ser.downloadSelected()
    check('a whole series is not downloaded',
          'open the series' in msg_text(s.dialogs[-1]))
finally:
    catalogue_mod.fetch, catalogue_mod.save = real_fetch, real_save
    _c.source.value = saved_source

print('\nstalker films: categories first, each read a page at a time')


class PagedPortal(object):
    def __init__(self, total):
        self.total = total
        self.pages = []

    def connect(self):
        return 'T'

    def vod_categories(self):
        return [('*', 'All'), ('5', 'Drama'), ('6', 'Action')]

    def vod_list(self, category='*', page=1, search=''):
        self.pages.append((category, page))
        start = (page - 1) * 14
        count = max(0, min(14, self.total - start))
        return ([MediaItem('Film %d' % (start + i), kind=MOVIE, group='5',
                           item_id='%s-%d' % (category, start + i))
                 for i in range(count)], self.total)


def finish(task):
    """Wait for a background task the screen started and deliver it."""
    if task._thread is not None:
        task._thread.join(30)
    task.stop()
    task.done(task.result, task.error)


portal = PagedPortal(33204)
real_make = catalogue_mod.make_stalker
catalogue_mod.make_stalker = lambda: portal
_c.source.value = 'stalker'
try:
    check('stalker films are paged', catalogue_mod.paged('movies', 'stalker'))
    check('stalker live and xtream films are not',
          not catalogue_mod.paged('live', 'stalker') and
          not catalogue_mod.paged('movies', 'xtream'))
    s = Session()
    cs = s.open(cats_mod.FarsiCategories, 'movies')
    finish(cs.task)
    check('only one page is read to list the categories',
          portal.pages == [('*', 1)], str(portal.pages))
    check('latest added shows the whole catalogue count',
          cs.rows[0] == ('LATEST ADDED', 33204), str(cs.rows[:2]))
    check('named categories listed without reading them',
          [r[0] for r in cs.rows[1:]] == ['Drama', 'Action'])
    check('category rows are str', all(isinstance(r, str) for r in cs['list'].list))
    portal.pages[:] = []
    cs['list'].moveToIndex(1)
    cs.open()
    films = s.dialogs[-1]
    finish(films.task)
    check('opening a category reads just enough pages for one screen',
          portal.pages == [('5', 1), ('5', 2)], str(portal.pages))
    check('the list stays on its category', films.groups == ['Drama'])
    check('page count comes from the server total',
          films.filteredCount() == 33204, str(films.filteredCount()))
    films.nextPage()
    check('the next page is fetched in the background, not all at once',
          films._pending_page == 1 and films.more_task.running() or
          films.more_task._thread is not None)
    finish(films.more_task)
    check('and shown once it arrives',
          films.page == 1 and len(films.visible()) == 20 and
          len(portal.pages) <= 4, '%d pages read' % len(portal.pages))
    check('status is a str', isinstance(films['status'].getText(), str))
finally:
    catalogue_mod.make_stalker = real_make
    _c.source.value = saved_source

home_mod = _mod('screens.home')
_c.source.value = 'xtream'
try:
    s = Session()
    hs = home_mod.FarsiHome(s)
    hs.index = 0
    real_open = s.open
    opened_kinds = []
    s.open = lambda screen, *a, **k: opened_kinds.append((screen.__name__, a))
    hs.select()
    check('Live TV on an xtream server opens its categories',
          opened_kinds and opened_kinds[0] == ('FarsiCategories', ('live',)),
          str(opened_kinds))
finally:
    _c.source.value = saved_source
s = Session()
hs = home_mod.FarsiHome(s)
check('the home skin carries the subtitle line',
      'name="subtitle"' in hs.skin)
hs._accountReady('2027-01-31', None)
check('expiry shown on the home screen',
      hs['subtitle'].getText() == 'Expires: 2027-01-31', hs['subtitle'].getText())
hs._accountReady(None, 'boom')
check('a failed account check leaves the line blank',
      hs['subtitle'].getText() == '')
main_skin = main_mod.FarsiMain(Session()).skin
check('the provider carousel has no subtitle widget',
      'name="subtitle"' not in main_skin)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
