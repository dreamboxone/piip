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
"""Playback screen: translation controls, guide, seeking and subtitles.

The picture comes from the local engine, not from the provider directly:
Enigma2 plays http://127.0.0.1:<port>/live.ts while the engine holds the
real stream back by the configured delay and mixes the translated speech in.

Movies and episodes go through exactly the same path, with two differences:
ffmpeg reads them at native rate (-re), and seeking is done by restarting
the pipeline at a new offset, because a live pipe cannot be seeked.

Subtitle timing follows the engine's reported position rather than the
service position, so the delay buffer is already accounted for.
"""

import os
import re
import tempfile
import time

try:
    from urllib.request import Request, urlopen
except ImportError:                                  # Python 2
    from urllib2 import Request, urlopen

from enigma import eServiceReference, eTimer

from Components.ActionMap import ActionMap, NumberActionMap
from Components.config import configfile
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from ..plugin import config, engine_config, api_key
from ..providers.models import human_duration
from ..translate.control import EngineHandle
from ..utils import resume as resume_store
from ..utils import servicerefs
from ..utils.uisafe import BackgroundTask, safe_actions, safe_callback
from ..utils.compat import native

try:
    from Components.ServiceEventTracker import ServiceEventTracker
    from enigma import iPlayableService
except ImportError:                                  # development test stub
    ServiceEventTracker = None
    iPlayableService = None

_c = config.plugins.piip

SEEK_STEP = 60
SUB_STEP = 500                      # milliseconds per sync nudge
SUB_FPS = (0.0, 23.976, 24.0, 25.0, 29.97, 30.0)

SUB_SIZE = {'small': 30, 'medium': 38, 'large': 46, 'extra': 56}
SUB_TOP = {'top': 80, 'middle': 430, 'bottom': 600}
SUB_TOP_HD = {'top': 54, 'middle': 286, 'bottom': 396}
SUB_SIZE_HD = {'small': 20, 'medium': 26, 'large': 32, 'extra': 38}
SUB_COLOR = {'white': '#00ffffff', 'yellow': '#00ffff00', 'green': '#0080ff80'}

OSD_WIDGETS = ('osd_bg', 'channel', 'state', 'bitrate', 'picon', 'cover',
               'bar_pos', 'time', 'epg', 'epg_next', 'hint', 'streamcat',
               'streamtype', 'extension', 'clock', 'vwidth', 'vheight',
               'vfps', 'vcodec', 'vaspect', 'vtag')

# The panel covers a third of the picture, so it leaves on its own; any key
# brings it back for another five seconds.
OSD_HIDE_SECONDS = 5


def reveal_osd(screen, action):
    """Bring the panel back on any key but MENU, which toggles it itself."""
    if action != 'menu':
        try:
            screen.showOSD()
        except Exception:
            pass


# Enigma2's ActionMap is an old-style class on Python 2, so these carry no
# mix-in: a new-style base beside it is a TypeError at import time.
class OSDActionMap(ActionMap):
    def __init__(self, screen, contexts, actions=None, prio=0):
        ActionMap.__init__(self, contexts, actions, prio)
        self.screen = screen

    def action(self, context, action):
        reveal_osd(self.screen, action)
        return ActionMap.action(self, context, action)


class OSDNumberActionMap(NumberActionMap):
    def __init__(self, screen, contexts, actions=None, prio=0):
        NumberActionMap.__init__(self, contexts, actions, prio)
        self.screen = screen

    def action(self, context, action):
        reveal_osd(self.screen, action)
        return NumberActionMap.action(self, context, action)

# Enigma2 colours are #TTRRGGBB where TT is TRANSPARENCY: 00 is opaque and
# ff is invisible. The screen itself must be fully transparent or it hides
# the video layer underneath.
SKIN_1920 = """
<screen name="FarsiPlayer" position="0,0" size="1920,1080" flags="wfNoBorder"
        backgroundColor="#ff000000" title="PIIP">
  <widget name="subtitle" position="160,%(sub_top)d" size="1600,150" zPosition="4"
          font="Regular;%(sub_size)d" halign="center" valign="bottom"
          foregroundColor="%(sub_color)s" backgroundColor="#50000000"
          transparent="0" />

  <widget name="osd_bg" position="0,760" size="1920,320" zPosition="1"
          backgroundColor="#a0101018" transparent="0" />
  <widget name="channel" position="60,776" size="1240,54" zPosition="2"
          font="Regular;40" foregroundColor="#00ffffff" transparent="1" />
  <widget name="streamtype" position="1712,782" size="148,44" zPosition="2"
     font="Regular;26" halign="right" valign="center" foregroundColor="#00d4ff" transparent="1"/>
  <widget name="state" position="1320,782" size="380,44" zPosition="2"
          font="Regular;28" halign="right" foregroundColor="#0080ff80"
          transparent="1" />
  <widget name="bitrate" position="1320,824" size="540,34" zPosition="2"
          font="Regular;24" halign="right" foregroundColor="#00d4ff" transparent="1" />
  <widget name="picon" position="60,900" size="170,96" zPosition="3" scale="stretch" alphatest="on" />
  <widget name="cover" position="250,874" size="100,140" zPosition="3" scale="stretch" alphatest="on" />
  <widget name="epg" position="60,834" size="1800,34" zPosition="2"
          font="Regular;26" foregroundColor="#00ffcc66" transparent="1" />
  <widget name="bar_pos" position="60,878" size="1660,14" zPosition="2"
          borderWidth="1" borderColor="#00888888" />
  <widget name="time" position="1740,872" size="120,30" zPosition="2"
          font="Regular;24" halign="right" foregroundColor="#00cccccc"
          transparent="1" />
  <widget name="hint" position="380,912" size="1480,76" zPosition="2"
          font="Regular;24" foregroundColor="#00a8b2c0" transparent="1" />
</screen>
"""

SKIN_1280 = """
<screen name="FarsiPlayer" position="0,0" size="1280,720" flags="wfNoBorder"
        backgroundColor="#ff000000" title="PIIP">
  <widget name="subtitle" position="106,%(sub_top_hd)d" size="1068,100" zPosition="4"
          font="Regular;%(sub_size_hd)d" halign="center" valign="bottom"
          foregroundColor="%(sub_color)s" backgroundColor="#50000000"
          transparent="0" />

  <widget name="osd_bg" position="0,506" size="1280,214" zPosition="1"
          backgroundColor="#a0101018" transparent="0" />
  <widget name="channel" position="40,516" size="820,38" zPosition="2"
          font="Regular;28" foregroundColor="#00ffffff" transparent="1" />
  <widget name="streamtype" position="1142,520" size="98,32" zPosition="2"
     font="Regular;18" halign="right" valign="center" foregroundColor="#00d4ff" transparent="1"/>
  <widget name="state" position="880,520" size="250,32" zPosition="2"
          font="Regular;20" halign="right" foregroundColor="#0080ff80"
          transparent="1" />
  <widget name="bitrate" position="880,548" size="360,25" zPosition="2"
          font="Regular;17" halign="right" foregroundColor="#00d4ff" transparent="1" />
  <widget name="picon" position="40,600" size="114,64" zPosition="3" scale="stretch" alphatest="on" />
  <widget name="cover" position="166,582" size="67,94" zPosition="3" scale="stretch" alphatest="on" />
  <widget name="epg" position="40,556" size="1200,26" zPosition="2"
          font="Regular;19" foregroundColor="#00ffcc66" transparent="1" />
  <widget name="bar_pos" position="40,588" size="1110,10" zPosition="2"
          borderWidth="1" borderColor="#00888888" />
  <widget name="time" position="1160,583" size="90,24" zPosition="2"
          font="Regular;18" halign="right" foregroundColor="#00cccccc"
          transparent="1" />
  <widget name="hint" position="254,612" size="986,54" zPosition="2"
          font="Regular;17" foregroundColor="#00a8b2c0" transparent="1" />
</screen>
"""


def desktop_width():
    try:
        from enigma import getDesktop
        return getDesktop(0).size().width()
    except Exception:
        return 1920


def build_skin():
    """Hybrid-style infobar, scaled for 720p, 1080p and 1440p."""
    width = desktop_width()
    W, H = ((2560, 1440) if width >= 2560 else
            ((1920, 1080) if width >= 1920 else (1280, 720)))
    factor = W / 1920.0
    q = lambda value: int(round(value * factor))
    sub_top = (SUB_TOP.get(_c.sub_position.value, 600) if W >= 1920
               else SUB_TOP_HD.get(_c.sub_position.value, 396))
    sub_size = (SUB_SIZE.get(_c.sub_size.value, 38) if W >= 1920
                else SUB_SIZE_HD.get(_c.sub_size.value, 26))
    parts = [
        '<widget name="subtitle" position="%d,%d" size="%d,%d" zPosition="6" '
        'font="Regular;%d" halign="center" valign="bottom" foregroundColor="%s" '
        'backgroundColor="#50000000" transparent="0"/>' %
        (q(160), q(sub_top if W >= 1920 else sub_top / factor), q(1600), q(150),
         q(sub_size if W >= 1920 else sub_size / factor),
         SUB_COLOR.get(_c.sub_color.value, '#00ffffff')),
        '<widget name="osd_bg" position="0,%d" size="%d,%d" zPosition="1" '
        'backgroundColor="#b0000000" transparent="0"/>' % (q(864), W, q(216)),
        '<widget name="cover" position="%d,%d" size="%d,%d" alphatest="blend" '
        'zPosition="4" scale="stretch"/>' % (q(30), q(650), q(219), q(330)),
        '<widget name="picon" position="%d,%d" size="%d,%d" alphatest="blend" '
        'zPosition="4" scale="stretch"/>' % (q(30), q(888), q(219), q(150)),
        '<widget name="channel" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'noWrap="1" foregroundColor="#ffffff" transparent="1" zPosition="3"/>' %
        (q(321), q(888), q(900), q(48), q(36)),
        '<widget name="state" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'noWrap="1" foregroundColor="#ffff00" halign="right" transparent="1" zPosition="3"/>' %
        (q(1220), q(888), q(310), q(48), q(30)),
        '<widget name="epg" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'noWrap="1" foregroundColor="#ffffff" transparent="1" zPosition="4"/>' %
        (q(321), q(955), q(1143), q(48), q(30)),
        '<widget name="bar_pos" position="%d,%d" size="%d,%d" borderWidth="1" '
        'borderColor="#ffffff" foregroundColor="#57ffff" backgroundColor="#494f83" '
        'zPosition="4"/>' % (q(321), q(1002), q(1143), q(12)),
        '<widget name="epg_next" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'foregroundColor="#aaaaaa" transparent="1" zPosition="4"/>' %
        (q(321), q(1025), q(923), q(35), q(27)),
        '<widget name="bitrate" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'foregroundColor="#57ffff" halign="right" transparent="1" zPosition="4"/>' %
        (q(1244), q(1025), q(220), q(35), q(27)),
        '<widget name="time" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'foregroundColor="#ffffff" halign="right" transparent="1" zPosition="3"/>' %
        (q(1204), q(955), q(260), q(48), q(30)),
        '<widget name="hint" position="0,0" size="1,1" transparent="1"/>',
    ]
    # Three rows of Hybrid-style media tags: kind / resolution / codec,
    # service type / height / aspect, extension / fps. Every cell is one
    # named Label carrying its own plate, because an eLabel or a renderer
    # bound to a source cannot be hidden from code and stayed on the picture
    # after the panel had gone.
    for name, col_x, row_y in (
            ('streamcat', 1560, 939), ('streamtype', 1560, 981),
            ('extension', 1560, 1023), ('vwidth', 1656, 939),
            ('vheight', 1656, 981), ('vfps', 1656, 1023),
            ('vcodec', 1752, 939), ('vaspect', 1752, 981),
            ('vtag', 1752, 1023)):
        parts.append(
            '<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" '
            'foregroundColor="#000000" backgroundColor="#20ffffff" '
            'halign="center" valign="center" transparent="0" '
            'cornerRadius="%d" zPosition="3"/>'
            % (name, q(col_x), q(row_y), q(90), q(36), q(24), q(8)))
    parts.append(
        '<widget name="clock" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'foregroundColor="#ffffff" transparent="1" zPosition="3"/>'
        % (q(1560), q(888), q(318), q(48), q(30)))
    return ('<screen name="FarsiPlayer" position="0,0" size="%d,%d" flags="wfNoBorder" '
            'backgroundColor="#ff000000" title="PIIP">\n%s\n</screen>' %
            (W, H, '\n'.join(parts)))


class FarsiPlayer(Screen):
    def __init__(self, session, item, start_at=0.0, epg_loader=None,
                 channels=None, index=0, resolver=None, catchup=None,
                 guide_loader=None, epg_factory=None):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.item = item
        self.start_at = float(start_at or 0)
        self.epg_loader = epg_loader
        # The guide screen wants past programmes for catch-up as well.
        self.guide_loader = guide_loader or epg_loader
        self.catchup = catchup
        # The loaders above are bound to one channel. Given a factory,
        # item -> (epg_loader, guide_loader, catchup), a channel change
        # builds fresh ones; without it the old ones are dropped rather
        # than showing the first channel's guide over another channel.
        self.epg_factory = epg_factory
        # The whole list travels with the player so a channel change never
        # has to go back to the list screen.
        self.channels = list(channels or [])
        self.index = int(index or 0)
        self.resolver = resolver
        if not self.channels:
            self.channels = [item]
            self.index = 0
        self.engine = None
        self.osd_visible = True
        self.position = self.start_at
        self.duration = int(getattr(item, 'duration', 0) or 0)
        self.seekable = bool(getattr(item, 'seekable', False))
        self.subs = None
        self.subs_on = True
        self.active_sub_fps = 0.0
        self.active_video_fps = 0.0
        self._exit_pending = False
        # Everything goes through the engine: this receiver's GStreamer
        # cannot open the providers' HLS streams itself. With translation
        # off the engine merely copies the stream, which is nearly free.
        self.direct = not (_c.translate.value and api_key())
        self.epg_now = None
        self.epg_next = None
        self._epg_checked = 0
        # Which Enigma2 service player is in use. It starts at the setting
        # but can be changed while watching, because which one a provider
        # needs is not something you can know before trying.
        self.stream_type = self.streamTypeConfig(item).value
        self._ring = None
        self._retry_count = 0
        self._retrying = False
        self._last_net_bytes = None
        self._last_net_time = None
        self._last_kbps = 0.0
        self._art_files = []
        self.art_task = BackgroundTask(self, self._fetchArtwork,
                                       self._artworkReady, 'player-artwork')

        self['osd_bg'] = Label('')
        self['channel'] = Label(item.label() if hasattr(item, 'label')
                                else item.name)
        self['state'] = Label('starting...')
        self['bitrate'] = Label('0 kb/s')
        self['picon'] = Pixmap()
        self['cover'] = Pixmap()
        self['streamtype'] = Label(native(self.stream_type))
        self['streamcat'] = Label(native(str(item.kind or '').upper()[:5]))
        extension = item.ext or item.url.split('?', 1)[0].rsplit('.', 1)[-1]
        self['extension'] = Label(native(extension.upper()[:5]))
        for name in ('vwidth', 'vheight', 'vfps', 'vcodec', 'vaspect', 'vtag'):
            self[name] = Label('')
        self['clock'] = Label('')
        self['epg'] = Label('')
        self['epg_next'] = Label('')
        self['bar_pos'] = ProgressBar()
        self['time'] = Label('')
        self['subtitle'] = Label('')
        self._subtitle_shown = True
        self['hint'] = Label(self.hintText())

        self['actions'] = OSDActionMap(
            self,
            ['OkCancelActions', 'DirectionActions', 'ColorActions',
             'InfobarActions', 'EPGSelectActions'],
            safe_actions(self, {
                'ok': self.openZapList,
                'cancel': self.leavePlayer,
                'left': self.prevChannel,
                'right': self.nextChannel,
                'up': self.prevChannel,
                'down': self.nextChannel,
                'red': self.toggleTranslation,
                'green': self.cycleDelay,
                'yellow': self.seekBack,
                'blue': self.seekForward,
                'info': self.showStatus,
                'showEventInfo': self.openEPG,
                'menu': self.toggleOSD,
                'videoMode': self.nextAR,
            }), -1)
        self['numbers'] = OSDNumberActionMap(
            self,
            ['NumberActions'],
            safe_actions(self, {
                '0': self.toggleSubtitles,
                '1': self.openSubtitles,
                '2': self.subSyncBack,
                '3': self.toggleStreamType,
                '4': self.subFpsBack,
                '5': self.openEPG,
                '6': self.subFpsForward,
                '7': self.nextAR,
                '8': self.subSyncForward,
            }), -1)

        self.poll = eTimer()
        try:
            self.poll.callback.append(safe_callback(self, self.refresh))
        except AttributeError:                       # older enigma2
            self.poll_conn = self.poll.timeout.connect(safe_callback(self, self.refresh))
        self.subtimer = eTimer()
        try:
            self.subtimer.callback.append(safe_callback(self, self.tickSubtitles))
        except AttributeError:
            self.sub_conn = self.subtimer.timeout.connect(safe_callback(self, self.tickSubtitles))
        self.retry_timer = eTimer()
        try:
            self.retry_timer.callback.append(safe_callback(self, self._retryStream))
        except AttributeError:
            self.retry_conn = self.retry_timer.timeout.connect(safe_callback(self, self._retryStream))
        self.osd_timer = eTimer()
        try:
            self.osd_timer.callback.append(safe_callback(self, self.hideOSD))
        except AttributeError:
            self.osd_conn = self.osd_timer.timeout.connect(safe_callback(self, self.hideOSD))
        # The countdown starts with the picture, not with the screen: hiding
        # the panel over a black frame leaves the viewer with nothing to read
        # while the channel is still opening.
        self.osd_armed = False

        if ServiceEventTracker is not None:
            events = {iPlayableService.evEOF: self.doEofInternal}
            for event_name in ('evVideoSizeChanged', 'evGotVideoSize'):
                event = getattr(iPlayableService, event_name, None)
                if event is not None:
                    events[event] = self.armOSD
            # evUser is a generic service notification and is emitted during
            # normal startup on DreamOS. Treating it as a failure creates a
            # retry loop even when media is healthy.
            for event_name in ('evTuneFailed',):
                event = getattr(iPlayableService, event_name, None)
                if event is not None:
                    events[event] = self.handleError
            self._event_tracker = ServiceEventTracker(screen=self,
                                                       eventmap=events)

        self.onLayoutFinish.append(self.hideSubtitle)
        self.onLayoutFinish.append(self.loadArtwork)
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.cleanup)

    def hideSubtitle(self):
        self._subtitle_shown = False
        try:
            self['subtitle'].hide()
        except Exception:
            pass

    def hintText(self):
        bits = ['OK: channel list', 'UP/DOWN: change channel']
        if self.seekable:
            bits.append('YELLOW/BLUE: skip %ds' % SEEK_STEP)
        bits += ['RED: translation', 'GREEN: delay', '1: subtitles',
                 '2/8: subtitle sync', '4/6: subtitle FPS',
                 '3: player', '5: guide', '7: aspect',
                 'MENU: hide panel', 'EXIT: stop']
        return '    '.join(bits)

    # ---------------------------------------------------------- the engine

    def serviceType(self):
        """The Enigma2 service id currently in use."""
        try:
            return int(self.stream_type)
        except (TypeError, ValueError):
            return 4097

    def streamTypeConfig(self, item=None):
        """Keep Hybrid's VOD player choice separate from live television."""
        current = item if item is not None else self.item
        return _c.service_type if getattr(current, 'is_live', False) else _c.vod_streamtype

    def streamTypes(self):
        """The players offered, in the order the setting lists them.

        Worked out once and kept: recomputing it would drop a hand-set
        value out of the ring the moment the toggle stepped past it.
        """
        if self._ring is None:
            try:
                found = [value for value, _label in self.streamTypeConfig().choices]
            except Exception:
                found = []
            if self.stream_type not in found:
                found.insert(0, self.stream_type)
            self._ring = found or ['4097']
        return self._ring

    def toggleStreamType(self, number=None):
        """Play the same thing again under the next service player.

        A stream that shows nothing under gstreamer often plays under
        8193, and the only way to find out is to try it here.
        """
        ring = self.streamTypes()
        try:
            nxt = ring[(ring.index(self.stream_type) + 1) % len(ring)]
        except ValueError:
            nxt = ring[0]
        self.stream_type = nxt
        self['streamtype'].setText(native(nxt))
        self['state'].setText(native('player %s' % nxt))
        # Kept, so the next channel opens with whatever turned out to work.
        try:
            setting = self.streamTypeConfig()
            setting.value = nxt
            setting.save()
            configfile.save()
        except Exception:
            pass
        self.replay()

    def replay(self):
        """Restart the current stream under the current service player."""
        if self.engine is not None:
            self.playLocal()
        else:
            self.playDirect()

    # ------------------------------------------------------------ lifecycle

    def begin(self):
        self.updateBars()
        saved = resume_store.get(self.item) if self.seekable else 0
        if saved > 0 and self.start_at <= 0:
            self.session.openWithCallback(
                self.resumeAnswer, MessageBox,
                native('Resume from %s?' % human_duration(saved)),
                MessageBox.TYPE_YESNO, timeout=15, default=True)
        else:
            self.start()

    def resumeAnswer(self, answer):
        if answer:
            self.start_at = float(resume_store.get(self.item))
            self.position = self.start_at
        self.start()

    def diagBegin(self):
        """One diagnostics folder per player, kept across retries and zaps."""
        if getattr(self, 'diag_dir', None) is None:
            self.diag_dir = ''
            try:
                from ..utils import diaglog, diagagent
                self.diag_dir = diaglog.new_dir('play', self.item.name) or ''
                if self.diag_dir:
                    diagagent.attach(self.diag_dir, 'player')
            except Exception:
                self.diag_dir = ''
        self.diagNote('start %s translate=%s delay=%s player=%s url-host=%s' % (
            self.item.name, not self.direct, _c.delay.value, self.stream_type,
            (self.item.url.split('/') + ['', '', ''])[2]))

    def diagNote(self, text):
        folder = getattr(self, 'diag_dir', '')
        if folder:
            try:
                from ..utils import diaglog
                diaglog.append_text(os.path.join(folder, 'events.log'),
                                    'player %s' % text)
            except Exception:
                pass

    def start(self):
        self.started_at = time.time()
        self._retrying = False
        self.diagBegin()
        if self.direct:
            self.playDirect()
            return
        cfg = engine_config(self.item.url, self.item, self.start_at,
                            diag_dir=self.diag_dir)
        # Translation runs on the E2Dub audio engine (translate/dub.py).
        from ..translate.dub import DubPipeline
        from ..translate.gemini import language_code
        self.engine = DubPipeline(cfg, api_key(),
                                  language_code(_c.language.value),
                                  _c.vol_original.value, _c.ffmpeg.value)
        self._dub_buffer_set = False
        self._dub_track = None
        if not self.engine.start():
            reason = ''
            try:
                source = getattr(self.engine, 'source', None)
                reason = source.failure() if source is not None else ''
            except Exception:
                reason = ''
            self.diagNote('engine failed to start: %s' % (reason or 'unknown'))
            self['state'].setText(native('engine failed'))
            self.session.open(
                MessageBox,
                native('The translation engine did not start.\n\n%s\n\n'
                       'Check that ffmpeg exists on the receiver; the whole '
                       'reason is in /tmp/piip_engine_stderr.log.'
                       % (reason or 'No reason was reported.')),
                MessageBox.TYPE_ERROR, timeout=10)
            return
        self.started_at = time.time()
        if getattr(self.engine, 'helper_state', None) is not None:
            # As E2Dub does: play only once the delayed stream is ready. A
            # DVB/TS service opened on an empty local URL reports a tune
            # failure after a few seconds, which restarted the pipeline.
            self._dub_waiting = True
            self['state'].setText(native('buffering translation...'))
        else:
            self.playLocal()
        self.poll.start(1000, False)
        self.subtimer.start(250, False)

    def playDirect(self):
        """Straight to Enigma2, with the headers servicemp3 needs.

        This is the ordinary path: no engine, no re-muxing, no delay.
        """
        ref = servicerefs.make_ref(
            self.item.url,
            name=self.item.name,
            servicetype=self.serviceType(),
            user_agent=_c.user_agent.value,
            mac=_c.stalker_mac.value if _c.source.value == 'stalker' else None,
            portal=_c.stalker_portal.value if _c.source.value == 'stalker'
            else None,
            token=getattr(self.item, 'auth_token', '') or None)
        self.session.nav.stopService()
        self.session.nav.playService(ref)
        self['state'].setText(native('playing'))
        self.poll.start(2000, False)
        self.subtimer.start(250, False)

    def playLocal(self):
        if getattr(self.engine, 'helper_state', None) is not None:
            # As E2Dub plays it: a DVB/TS service on the local HTTP path, so
            # DreamOS demuxes both audio tracks natively.
            from ..translate.dub import LOCAL_DVB_REFERENCE
            ref = eServiceReference(LOCAL_DVB_REFERENCE)
            ref.type = getattr(eServiceReference, 'idDVB', 1)
            ref.setPath(self.engine.url)
            ref.setName(self.item.name)
            self.session.nav.stopService()
            self.session.nav.playService(ref)
            self['state'].setText(native('starting translation...'))
            return
        ref = eServiceReference(self.serviceType(), 0,
                                self.engine.url)
        ref.setName(self.item.name)
        self.session.nav.stopService()
        self.session.nav.playService(ref)
        self['state'].setText(native('starting...'))

    def stop(self):
        self.saveResume()
        self.close()

    def leavePlayer(self):
        """Respect Enigma2's ask-before-leaving preference like HybridIPTV."""
        if self._exit_pending:
            return
        ask = True
        try:
            ask = bool(config.usage.askBeforeLeaving.value)
        except Exception:
            pass
        if not ask:
            self.stop()
            return
        self._exit_pending = True
        self.session.openWithCallback(
            self.leavePlayerConfirmed, MessageBox,
            native('Stop playing and return to the channel list?'),
            MessageBox.TYPE_YESNO, timeout=10, default=True)

    def leavePlayerConfirmed(self, answer):
        self._exit_pending = False
        if answer:
            self.stop()

    def saveResume(self):
        if self.seekable and self.position > 0:
            resume_store.put(self.item, int(self.position), self.duration)

    def cleanup(self):
        self.diagNote('close')
        try:
            from ..utils import diagagent
            diagagent.detach(getattr(self, 'diag_dir', None))
        except Exception:
            pass
        self.art_task.stop()
        for t in (self.poll, self.subtimer, self.retry_timer, self.osd_timer):
            try:
                t.stop()
            except Exception:
                pass
        if self.engine:
            self.engine.stop()
            self.engine = None
        try:
            self.session.nav.stopService()
        except Exception:
            pass
        for path in self._art_files:
            try:
                os.unlink(path)
            except Exception:
                pass

    def _artworkUrls(self):
        logo = native(getattr(self.item, 'logo', '') or '')
        # Live providers expose a picon. VOD/episodes expose the same field as
        # poster art, so show it in the taller cover slot as well.
        return {'picon': logo if getattr(self.item, 'is_live', False) else '',
                'cover': logo if not getattr(self.item, 'is_live', False) else ''}

    def loadArtwork(self):
        self._applyModeVisibility()
        for name in ('picon', 'cover'):
            try:
                self[name].hide()
            except Exception:
                pass
        if any(self._artworkUrls().values()) and not self.art_task.running():
            self.art_task.start()

    def _applyModeVisibility(self):
        """Do not overlap Hybrid's mutually exclusive live and VOD fields."""
        if not self.osd_visible:
            return
        live = bool(getattr(self.item, 'is_live', False))
        for name in ('epg', 'epg_next', 'bitrate'):
            try:
                (self[name].show if live else self[name].hide)()
            except Exception:
                pass
        try:
            (self['time'].hide if live else self['time'].show)()
        except Exception:
            pass

    def _fetchArtwork(self):
        result = {}
        for widget, url in self._artworkUrls().items():
            if not url:
                continue
            if os.path.isfile(url):
                result[widget] = url
                continue
            suffix = os.path.splitext(url.split('?', 1)[0])[1].lower()
            if suffix not in ('.png', '.jpg', '.jpeg'):
                suffix = '.jpg'
            fd, path = tempfile.mkstemp(prefix='piip-art-', suffix=suffix)
            try:
                req = Request(url, headers={'User-Agent': _c.user_agent.value})
                response = urlopen(req, timeout=8)
                data = response.read(2 * 1024 * 1024 + 1)
                response.close()
                if not data or len(data) > 2 * 1024 * 1024:
                    raise IOError('invalid artwork size')
                os.write(fd, data)
                os.close(fd)
                fd = None
                result[widget] = path
            except Exception:
                if fd is not None:
                    os.close(fd)
                try:
                    os.unlink(path)
                except Exception:
                    pass
        return result

    def _artworkReady(self, result, error):
        if error or not result:
            return
        from ..utils.backdrop import pixmap
        for widget, path in result.items():
            try:
                instance = self[widget].instance
                picture = pixmap(path, instance.size())
                if picture is not None:
                    instance.setPixmap(picture)
                    self[widget].show()
                    if path.startswith(tempfile.gettempdir()):
                        self._art_files.append(path)
            except Exception:
                pass

    def _get_net_bytes(self):
        """Total received bytes, matching HybridIPTV's /proc/net/dev meter."""
        try:
            total = 0
            with open('/proc/net/dev', 'r') as handle:
                for line in handle:
                    if ':' in line:
                        total += int(line.split(':', 1)[1].split()[0])
            return total
        except Exception:
            return None

    def _updateBitrate(self):
        now = time.time()
        current = self._get_net_bytes()
        if current is not None and self._last_net_bytes is not None:
            elapsed = now - self._last_net_time
            delta = current - self._last_net_bytes
            if elapsed > 0 and delta >= 0:
                kbps = delta * 8.0 / elapsed / 1000.0
                self._last_kbps = kbps
                text = ('%.1f Mb/s' % (kbps / 1000.0) if kbps >= 1000
                        else '%d kb/s' % int(kbps))
                self['bitrate'].setText(native(text))
        self._last_net_bytes, self._last_net_time = current, now

    def handleError(self, error=None):
        """Schedule a bounded restart; repeated events cannot stack timers."""
        if self._retrying:
            return
        if getattr(self, '_dub_waiting', False) and error is None:
            # Service events of the previous channel while the translated
            # stream is still buffering are not failures of this playback.
            return
        self.pinOSD()
        self._retrying = True
        self._retry_count += 1
        delay = min(30, 2 ** min(self._retry_count - 1, 4))
        self.diagNote('error %s -> retry %d in %ds'
                      % (error, self._retry_count, delay))
        self['state'].setText(native('stream lost - retry in %ds' % delay))
        self.showOSD()
        self.retry_timer.start(delay * 1000, True)

    def doEofInternal(self, playing=True):
        if getattr(self.engine, 'helper_state', None) is not None and                 self.engine.alive():
            # The translated pipeline is still running: DreamOS' HTTP/TS
            # source reports EOF on a short stall. Reattach to the local
            # stream instead of rebuilding Gemini and the delay buffer.
            self.diagNote('eof on local translated stream; reattaching')
            self.playLocal()
            return
        self.handleError('eof')

    def _retryStream(self):
        self._retrying = False
        self['state'].setText(native('reconnecting...'))
        if self.engine:
            self.engine.stop()
            self.engine = None
        try:
            self.session.nav.stopService()
        except Exception:
            pass
        self.start()

    def nextAR(self, number=None):
        """Cycle Enigma2's configured 4:3 aspect policy like HybridIPTV."""
        try:
            from Components.config import config as avconfig
            policy = avconfig.av.policy_43
            choices = [x[0] if isinstance(x, (tuple, list)) else x
                       for x in policy.choices]
            index = choices.index(policy.value) if policy.value in choices else -1
            policy.value = choices[(index + 1) % len(choices)]
            policy.save()
            configfile.save()
            self['state'].setText(native('aspect: %s' % policy.value))
            self.showOSD()
        except Exception as exc:
            self['state'].setText(native('aspect unavailable: %s' % exc))

    # ------------------------------------------------------------- subtitles

    def openSubtitles(self, number=None):
        from .subtitlepicker import FarsiSubtitles
        self.session.openWithCallback(self.subtitlesChosen, FarsiSubtitles,
                                      self.item)

    def subtitlesChosen(self, subs=None):
        if subs is None:
            return
        subs.offset = int(_c.sub_offset.value)
        self.subs = subs
        self.subs_on = True
        self.active_video_fps = self.videoFPS()
        match = re.search(r'(?i)(23\.976|23\.98|24\.00|24|25\.00|25|29\.97|30\.00|30)\s*(?:fps)?',
                          getattr(subs, 'source_name', '') or '')
        if match and self.active_video_fps > 0:
            self.active_sub_fps = float(match.group(1))
            subs.set_fps(self.active_sub_fps, self.active_video_fps)
            scale_msg = '\nAuto-FPS Applied: %s (Video: %.3f)' % (
                match.group(1), self.active_video_fps)
        else:
            self.active_sub_fps = 0.0
            subs.set_fps(0, self.active_video_fps)
            scale_msg = ''
        self['state'].setText(native('Subtitles loaded successfully!%s' % scale_msg))
        self.showOSD()

    def toggleSubtitles(self, number=None):
        if not self.subs:
            self.openSubtitles()
            return
        self.subs_on = not self.subs_on
        if not self.subs_on:
            self['subtitle'].setText(native(''))
        self['state'].setText(native('subtitles %s' % ('on' if self.subs_on else 'off')))
        self.showOSD()

    def subSyncBack(self, number=None):
        self.nudgeSubtitles(-SUB_STEP)

    def subSyncForward(self, number=None):
        self.nudgeSubtitles(SUB_STEP)

    def videoFPS(self):
        """Return the active video frame rate as reported by Enigma2."""
        try:
            service = self.session.nav.getCurrentService()
            info = service and service.info()
            from enigma import iServiceInformation
            value = info and info.getInfo(iServiceInformation.sFrameRate)
            value = float(value or 0)
            return value / 1000.0 if value > 1000 else value
        except Exception:
            return 0.0

    def subFpsBack(self, number=None):
        self.cycleSubtitleFPS(-1)

    def subFpsForward(self, number=None):
        self.cycleSubtitleFPS(1)

    def cycleSubtitleFPS(self, direction):
        if not self.subs:
            self['state'].setText(native('No subtitle loaded. Press 1 to search.'))
            self.showOSD()
            return
        try:
            current = SUB_FPS.index(self.active_sub_fps)
        except ValueError:
            current = 0
        self.active_sub_fps = SUB_FPS[(current + direction) % len(SUB_FPS)]
        self.active_video_fps = self.videoFPS() or self.active_video_fps
        self.subs.set_fps(self.active_sub_fps, self.active_video_fps)
        label = ('Original' if not self.active_sub_fps
                 else ('%.3f' % self.active_sub_fps).rstrip('0').rstrip('.'))
        self['state'].setText(native('Subtitle FPS: %s (Video: %.3f)' %
                                     (label, self.active_video_fps)))
        self.showOSD()

    def nudgeSubtitles(self, delta):
        if not self.subs:
            return
        offset = self.subs.shift(delta)
        _c.sub_offset.value = max(-60000, min(60000, offset))
        _c.sub_offset.save()
        self['state'].setText(native('subtitle sync %+.1fs' % (offset / 1000.0)))
        self.showOSD()

    def tickSubtitles(self):
        text = ''
        if self.subs and self.subs_on:
            text = self.subs.text_at(int(self.position * 1000))
        if text != self['subtitle'].getText():
            self['subtitle'].setText(native(text))
        # The widget has a background, so an empty one would leave a band
        # sitting over the picture.
        want = bool(text)
        if want != self._subtitle_shown:
            self._subtitle_shown = want
            try:
                if want:
                    self['subtitle'].show()
                else:
                    self['subtitle'].hide()
            except Exception:
                pass

    # ------------------------------------------------------------------ epg

    def openEPG(self, number=None):
        if not self.guide_loader:
            self.session.open(MessageBox, native('No guide data for this channel.'),
                              MessageBox.TYPE_INFO, timeout=6)
            return
        from .epgscreen import FarsiEPG
        self.session.open(FarsiEPG, self.item, self.guide_loader, self.catchup)

    def bindGuide(self, item):
        """Point the now/next line, the guide and catch-up at `item`."""
        loader = guide = catcher = None
        if self.epg_factory is not None:
            try:
                loader, guide, catcher = self.epg_factory(item)
            except Exception:
                loader = guide = catcher = None
        self.epg_loader = loader
        self.guide_loader = guide or loader
        self.catchup = catcher

    def refreshEPG(self):
        """Pull now/next once a minute; cheap because the loader caches."""
        if not (_c.epg_enabled.value and self.epg_loader):
            return
        now = time.time()
        if now - self._epg_checked < 60:
            return
        self._epg_checked = now
        try:
            progs = self.epg_loader()
        except Exception:
            return
        at = int(now)
        self.epg_now = self.epg_next = None
        for p in progs or []:
            if p.running_at(at):
                self.epg_now = p
            elif p.start > at and self.epg_next is None:
                self.epg_next = p
        if self.epg_now:
            self['epg'].setText(native(
                'Now: %s  %s' % (self.epg_now.clock(), self.epg_now.title)))
        else:
            self['epg'].setText(native('No EPG'))
        if self.epg_next:
            self['epg_next'].setText(native(
                'Next: %s  %s' % (self.epg_next.clock(), self.epg_next.title)))
        else:
            self['epg_next'].setText('')

    # ------------------------------------------------------------- seeking

    def seekBack(self):
        self.seekBy(-SEEK_STEP)

    def seekForward(self):
        self.seekBy(SEEK_STEP)

    def seekBy(self, delta):
        if self.direct or not self.seekable or not self.engine:
            return
        target = max(0.0, self.position + delta)
        if self.duration and target >= self.duration - 5:
            target = max(0.0, self.duration - 5.0)
        self['state'].setText(native('seeking to %s...' % human_duration(int(target))))
        self['subtitle'].setText(native(''))
        self.showOSD()
        self.poll.stop()
        if self.engine.seek(target):
            self.position = target
            self.start_at = target
            self.playLocal()
            self.poll.start(2000, False)
        else:
            self['state'].setText(native('seek failed'))

    # -------------------------------------------------------------- volumes

    def _apply_gains(self):
        """Volume lives in Settings now; this only refreshes the engine."""
        if self.direct or not self.engine:
            return
        self.engine.set_gain(
            original=_c.vol_original.value / 100.0,
            translated=_c.vol_translated.value / 100.0)

    # ------------------------------------------------------- changing channel

    def nextChannel(self):
        self.switchTo(self.index + 1)

    def prevChannel(self):
        self.switchTo(self.index - 1)

    def openZapList(self):
        if len(self.channels) < 2:
            self.toggleOSD()
            return
        from .zaplist import FarsiZapList
        self.session.openWithCallback(
            self.zapChosen, FarsiZapList, self.channels, self.index)

    def zapChosen(self, index=None):
        if index is not None and index != self.index:
            self.switchTo(index)

    def switchTo(self, index):
        """Move to another channel without leaving the player."""
        if len(self.channels) < 2:
            return
        index = index % len(self.channels)
        if index == self.index:
            return

        self.saveResume()
        item = self.channels[index]

        # Stalker links are made on demand and expire, so resolve on the way in.
        if self.resolver is not None and not item.url:
            self['state'].setText(native('resolving...'))
            try:
                self.resolver(item)
            except Exception as exc:
                self['state'].setText(native('failed: %s' % exc))
                return

        self.index = index
        self.item = item
        self.stream_type = self.streamTypeConfig(item).value
        self._ring = None
        self['streamtype'].setText(native(self.stream_type))
        self.start_at = 0.0
        self.position = 0.0
        self.duration = int(getattr(item, 'duration', 0) or 0)
        self.seekable = bool(getattr(item, 'seekable', False))
        self.subs = None
        self.epg_now = self.epg_next = None
        self._epg_checked = 0
        self.bindGuide(item)
        self._retry_count = 0
        self._last_net_bytes = self._last_net_time = None

        self['channel'].setText(native(
            item.label() if hasattr(item, 'label') else item.name))
        self['epg'].setText('')
        self['epg_next'].setText('')
        self['streamcat'].setText(native(str(item.kind or '').upper()[:5]))
        extension = item.ext or item.url.split('?', 1)[0].rsplit('.', 1)[-1]
        self['extension'].setText(native(extension.upper()[:5]))
        self.hideSubtitle()
        self.loadArtwork()
        self.showOSD()

        if self.engine:
            self.engine.stop()
            self.engine = None
        self.poll.stop()
        self.subtimer.stop()
        self.start()

    def updateBars(self):
        """A no-op: volume is set in Settings, not from the player."""
        return

    def updateProgress(self):
        if not self.seekable:
            if self.epg_now:
                self['bar_pos'].setValue(self.epg_now.progress_at(int(time.time())))
                self['time'].setText(native(self.epg_now.span()))
            else:
                self['bar_pos'].setValue(0)
                self['time'].setText(native('LIVE'))
            return
        if self.duration > 0:
            pct = max(0, min(100, int(self.position * 100 / self.duration)))
            self['bar_pos'].setValue(pct)
            self['time'].setText(native('%s / %s' % (
                human_duration(int(self.position)),
                human_duration(self.duration))))
        else:
            self['bar_pos'].setValue(0)
            self['time'].setText(native(human_duration(int(self.position))))

    # -------------------------------------------------------------- actions

    def toggleTranslation(self):
        """Mute/unmute the translated track without touching the engine."""
        if _c.vol_translated.value > 0:
            self._saved_trans = _c.vol_translated.value
            _c.vol_translated.value = 0
        else:
            _c.vol_translated.value = getattr(self, '_saved_trans', 100)
        _c.vol_translated.save()
        self._apply_gains()
        self.showOSD()

    def cycleDelay(self):
        d = _c.delay.value + 1
        if d > 12:
            d = 1
        _c.delay.value = d
        _c.delay.save()
        if self.engine:
            self.engine.set_delay(float(d))
        self['state'].setText(native('delay %ds' % d))
        self.showOSD()

    def showStatus(self):
        if self.direct:
            self.session.open(
                MessageBox,
                native('Playing straight from the provider.\n\n'
                       'Translation is off, so nothing is re-muxed and there '
                       'is no added delay.'),
                MessageBox.TYPE_INFO, timeout=10)
            return
        st = self.engine.status() if self.engine else None
        if not st:
            self.session.open(MessageBox, native('Engine is not responding.'),
                              MessageBox.TYPE_ERROR, timeout=6)
            return
        s = st.get('stats', {})
        lines = [
            'Uptime: %ss' % st.get('uptime', 0),
            'Gemini: %s' % st.get('gemini', '?'),
            'Delay: %.1fs' % st.get('delay', 0),
            'Translation backlog: %.1fs' % st.get('backlog', 0),
            'Translation tempo: %.3fx' % st.get('translation_tempo', 1.0),
            'Channel volume: %d%%' % int(st.get('gain_original', 0) * 100),
            'Translation volume: %d%%' % int(st.get('gain_translated', 0) * 100),
            'Original fallback: %s' % ('active' if st.get('original_fallback')
                                       else 'standby'),
        ]
        if self.seekable:
            lines.append('Position: %s%s' % (
                human_duration(int(self.position)),
                ' / %s' % human_duration(self.duration) if self.duration else ''))
        if self.subs:
            lines.append('Subtitles: %d cues, sync %+.1fs'
                         % (len(self.subs), self.subs.offset / 1000.0))
        lines += [
            'Video in: %.1f MB' % (s.get('video_bytes', 0) / 1048576.0),
            'Stream out: %.1f MB' % (s.get('out_bytes', 0) / 1048576.0),
            'Audio clock max late: %dms' % st.get('clock_late_max_ms', 0),
            'Translation underruns: %d' % st.get('translation_underruns', 0),
        ]
        self.session.open(MessageBox, native('\n'.join(lines)),
                          MessageBox.TYPE_INFO, timeout=15)

    # ------------------------------------------------------------------ osd

    def toggleOSD(self):
        self.osd_visible = not self.osd_visible
        for name in OSD_WIDGETS:
            widget = self[name]
            if self.osd_visible:
                widget.show()
            else:
                widget.hide()
        if self.osd_visible:
            self._applyModeVisibility()
            if self.osd_armed:
                self.osd_timer.start(OSD_HIDE_SECONDS * 1000, True)
        else:
            self.osd_timer.stop()

    def armOSD(self):
        """The picture is up: let the panel go after its five seconds."""
        if self.osd_armed:
            return
        self.osd_armed = True
        self.showOSD()

    def pinOSD(self):
        """Keep the panel up: it is the only sign of what is happening."""
        self.osd_armed = False
        try:
            self.osd_timer.stop()
        except Exception:
            pass
        self.showOSD()

    def hideOSD(self):
        if self.osd_visible:
            self.toggleOSD()

    def showOSD(self):
        if not self.osd_visible:
            self.toggleOSD()
        elif self.osd_armed:
            self.osd_timer.start(OSD_HIDE_SECONDS * 1000, True)

    def dubTick(self, st):
        """Buffer and audio-track handling for the E2Dub pipeline."""
        from ..translate.dub import BUFFER_MS
        self.refreshEPG()
        service = self.session.nav.getCurrentService()
        if service is None:
            return
        if not self._dub_buffer_set:
            try:
                streamed = service.streamed()
                if streamed is not None:
                    streamed.setBufferDuration(BUFFER_MS)
                    self._dub_buffer_set = True
            except Exception:
                pass
        # The decoder has taken the stream: there is a picture to look at.
        if self._dub_buffer_set or self._last_kbps >= 8.0:
            self.armOSD()
        state = st.get('dub_state')
        # Track 0: translation mixed with the programme; track 1: the
        # programme at full level while Gemini is not yet (or no longer)
        # delivering speech.
        wanted = 0 if state == 'audio' else 1
        try:
            tracks = service.audioTracks()
            if tracks is not None and tracks.getNumberOfTracks() > wanted                     and tracks.getCurrentTrack() != wanted:
                tracks.selectTrack(wanted)
                self._dub_track = wanted
                self.diagNote('dub track %d (%s)' % (wanted, state))
        except Exception:
            pass
        self['state'].setText(native({
            'audio': 'translating',
            'audio_buffering': 'translation buffering...',
            'streaming': 'waiting for translation...',
            'connecting': 'connecting to Gemini...',
        }.get(state, state or 'starting...')))

    def updateMediaTags(self):
        """Clock and picture facts, from code so the panel can hide them."""
        if not self.osd_visible:
            return
        self['clock'].setText(native(time.strftime('%H:%M | %A')))
        width = height = 0
        widescreen = None
        try:
            from enigma import iServiceInformation
            service = self.session.nav.getCurrentService()
            info = service and service.info()
            if info is not None:
                width = int(info.getInfo(iServiceInformation.sVideoWidth) or 0)
                height = int(info.getInfo(iServiceInformation.sVideoHeight) or 0)
                aspect = info.getInfo(iServiceInformation.sAspect)
                # Enigma2 reports 4:3 as 1/2/5/6 and 16:9 as 3/4/7/8.
                widescreen = aspect in (3, 4, 7, 8) if aspect >= 0 else None
        except Exception:
            pass
        fps = self.videoFPS()
        self['vwidth'].setText(native(str(width) if width > 0 else ''))
        self['vheight'].setText(native(str(height) if height > 0 else ''))
        self['vfps'].setText(native('%g fps' % fps if fps > 0 else ''))
        self['vaspect'].setText(native('' if widescreen is None else
                                       ('16:9' if widescreen else '4:3')))

    def refresh(self):
        self.updateMediaTags()
        self._updateBitrate()
        if self.direct:
            self.updateProgress()
            self.refreshEPG()
            # Some DreamOS/GStreamer builds occasionally create playbin but
            # never start the first HTTP read. Replaying the identical 4097
            # service wakes it immediately. This stall emits no Enigma event,
            # so the ordinary handleError path cannot see it.
            waited = time.time() - getattr(self, 'started_at', time.time())
            if (waited >= 8 and self._last_kbps < 8.0 and
                    self._retry_count == 0 and not self._retrying):
                self.handleError('startup stalled')
            elif self._last_kbps >= 8.0:
                self._retry_count = 0
                self.armOSD()
            return
        if not self.engine:
            return
        if not self.engine.alive():
            self.saveResume()
            self.handleError('engine stopped')
            return
        if getattr(self, '_dub_waiting', False):
            from ..translate.dub import read_state, RELAY_STATE, HTTP_STATE
            if (read_state(RELAY_STATE).get('state') == 'ready' and
                    read_state(HTTP_STATE).get('state') == 'ready'):
                self._dub_waiting = False
                self.playLocal()
            else:
                waited = int(time.time() - getattr(self, 'started_at', time.time()))
                self.pinOSD()
                self['state'].setText(native('buffering translation... %ds' % waited))
                if waited > 90:
                    self._dub_waiting = False
                    self.handleError('translation stream not ready')
            return
        st = self.engine.status()
        if not st:
            return
        if 'dub_state' in st:
            self.dubTick(st)
            return
        try:
            self.position = float(st.get('position') or self.position)
        except (TypeError, ValueError):
            pass
        if not self.duration:
            self.duration = int(st.get('duration') or 0)
        self.refreshEPG()
        self.updateProgress()

        # Until media actually flows the screen is black, and saying
        # "playing" then reads as a failure.
        if not st.get('flowing'):
            waited = int(time.time() - getattr(self, 'started_at', time.time()))
            self['state'].setText(native('buffering... %ds' % waited))
            return
        self.armOSD()

        self._retry_count = 0

        g = st.get('gemini', '')
        backlog = st.get('backlog', 0)
        if self.direct:
            self['state'].setText(native('playing'))
        elif g == 'connected':
            self['state'].setText(native('translating  (+%.1fs)' % backlog))
        else:
            self['state'].setText(native(g or 'playing'))
