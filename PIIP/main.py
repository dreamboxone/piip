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
"""Main menu: pick the kind of provider you are connecting to.

The same shape as the reference plugin's front door - a ring of three
provider types, each with its own wallpaper, with saved servers on MENU
and settings on INFO. Choosing a type opens its setup screen; connecting
from there opens that server's own menu.
"""

import os
import subprocess

from Screens.MessageBox import MessageBox

from .plugin import config, NAME as PLUGIN_NAME, api_key
from .utils.apikey import describe
from .screens.carousel import CarouselScreen, build_skin as _build
from .screens.home import FarsiHome
from .screens.serverlist import FarsiServerList
from .screens.serversetup import FarsiServerSetup
from .screens.setup import FarsiSetup
from .screens.diagnose import FarsiDiagnose
from .utils import servers, skin as sk
from .utils.compat import native
from .utils.uisafe import note

_c = config.plugins.piip

CHIPS = (('Close', sk.BTN_RED),
         ('Downloads', sk.ACCENT),
         ('INFO - Settings', sk.ACCENT_WARM),
         ('MENU Servers', sk.ACCENT))


def build_skin():
    return _build('FarsiMain', CHIPS)


class FarsiMain(CarouselScreen):
    # NAME is the skin's name; the plugin's own name has to be spelt out
    # because the class attribute shadows the import inside this body.
    NAME = 'FarsiMain'
    TITLE = PLUGIN_NAME.upper()
    CHIPS = CHIPS
    # label, provider type, icon, hint, wallpaper
    ITEMS = (
        ('Xtream Codes', 'xtream', 'xtream',
         'Host, username and password from your provider', 'bg_xtream.png'),
        ('M3U Playlist', 'm3u', 'm3u',
         'A playlist URL, or the list in m3u.txt', 'bg_m3u.png'),
        ('Stalker Portal', 'stalker', 'stalker',
         'A portal address and the MAC it is registered to',
         'bg_stalker.png'),
    )

    def __init__(self, session):
        self.saved_service = None
        CarouselScreen.__init__(self, session)
        self.onClose.append(self.restoreService)

    def keymap(self):
        keys = CarouselScreen.keymap(self)
        keys.update({
            'green': self.openDownloads,
            # HybridIPTV's yellow/gold footer action opens the complete
            # settings page.  Keep INFO as an alias because the caption on
            # the reference skin says "INFO - Settings".
            'yellow': self.openSettings,
            'blue': self.openServers,
            'menu': self.openServers,
            'info': self.openSettings,
            'showEventInfo': self.openSettings,
        })
        return keys

    def startUI(self):
        self.stopService()
        CarouselScreen.startUI(self)

    # ---------------------------------------------------------------- tuner

    def stopService(self):
        """Silence the channel that was playing while the menu is up.

        The opaque ground already hides its picture, but the sound would
        otherwise carry on underneath the menu.
        """
        try:
            nav = self.session.nav
            self.saved_service = nav.getCurrentlyPlayingServiceReference()
            if self.saved_service is not None:
                nav.stopService()
        except Exception as exc:
            note('tuner', 'could not stop the service: %s' % exc)
            self.saved_service = None

    def restoreService(self):
        """Put the receiver back on the channel it was on."""
        if self.saved_service is None:
            return
        service, self.saved_service = self.saved_service, None
        try:
            self.session.nav.playService(service)
        except Exception as exc:
            note('tuner', 'could not restore the service: %s' % exc)

    # -------------------------------------------------------------- status

    def refresh(self):
        kind = self.item()[1]
        saved = len(servers.load(kind))
        active = _c.active_server.value
        self['status'].setText(native(
            '%d saved %s server%s   |   active: %s   |   '
            'translation %s   |   API key %s'
            % (saved, kind, '' if saved == 1 else 's',
               active or 'none',
               'on' if _c.translate.value else 'off',
               'set' if api_key() else 'MISSING')))

    # ------------------------------------------------------------- opening

    def select(self):
        """Open the setup screen for the selected provider type."""
        kind = self.item()[1]
        # Pre-filled from the active server when it is of this type, so
        # reconnecting to yesterday's server is one keypress away.
        entry = None
        if _c.source.value == kind and _c.active_server.value:
            entry = servers.active()
        self.session.openWithCallback(self.connected, FarsiServerSetup,
                                      kind, entry)

    def connected(self, entry=None):
        if entry:
            self.session.open(FarsiHome)
        self.updateUI()

    def openServers(self):
        self.session.openWithCallback(self.connected, FarsiServerList)

    def openDownloads(self):
        from .screens.downloadmanager import FarsiDownloads
        self.session.open(FarsiDownloads)

    def openSettings(self):
        self.session.openWithCallback(self.settingsDone, FarsiSetup)

    def settingsDone(self, saved=False):
        self.updateUI()

    # --------------------------------------------------------------- tools

    def openTools(self):
        try:
            from Screens.ChoiceBox import ChoiceBox
        except ImportError:
            self.session.open(FarsiDiagnose)
            return
        choices = [(native('Test playlists'), 'diagnose'),
                   (native('Check requirements'), 'check'),
                   (native('Browse IPTV-org'), 'iptvorg')]
        self.session.openWithCallback(self.toolPicked, ChoiceBox,
                                      title=native('Tools'), list=choices)

    def toolPicked(self, choice=None):
        if not choice:
            return
        if choice[1] == 'diagnose':
            self.session.open(FarsiDiagnose)
        elif choice[1] == 'check':
            self.session.open(MessageBox, native(self.checkRequirements()),
                              MessageBox.TYPE_INFO, timeout=30)
        elif choice[1] == 'iptvorg':
            from .screens.iptvorg import FarsiIPTVOrg
            self.session.open(FarsiIPTVOrg)

    # ---------------------------------------------------------- diagnostics

    def checkRequirements(self):
        lines = []

        ff = _c.ffmpeg.value
        try:
            out = subprocess.check_output([ff, '-version'],
                                          stderr=subprocess.STDOUT)
            # decode() returns unicode on Python 2 and the SWIG widgets
            # reject it: this is what crashed the receiver.
            first = native(out.decode('utf-8', 'replace').splitlines()[0])
            lines.append('[OK] ffmpeg: %s' % first[:60])
        except Exception as e:
            lines.append('[FAIL] ffmpeg not runnable (%s): %s' % (ff, e))

        try:
            import audioop            # noqa: F401
            lines.append('[OK] audio backend: audioop (stdlib)')
        except ImportError:
            try:
                import numpy         # noqa: F401
                lines.append('[OK] audio backend: numpy')
            except ImportError:
                lines.append('[FAIL] no audio backend: install python3-numpy')

        try:
            import ssl               # noqa: F401
            lines.append('[OK] ssl available (needed for Gemini)')
        except ImportError:
            lines.append('[FAIL] python ssl module missing')

        lines.append(('[OK] ' if api_key() else '[WARN] ')
                     + describe(_c.api_key.value))

        saved = servers.load_all()
        lines.append(('[OK] ' if saved else '[WARN] ')
                     + '%d saved server%s' % (len(saved),
                                              '' if len(saved) == 1 else 's'))

        try:
            from .translate import resolver
            lines.append(('[OK] ' if resolver.running() else '[WARN] ')
                         + 'resolver %s (bouquets need it)'
                         % ('running' if resolver.running() else 'not running'))
        except Exception as e:
            lines.append('[FAIL] resolver: %s' % e)

        subs = []
        if _c.opensubtitles_key.value.strip():
            subs.append('OpenSubtitles')
        if _c.subdl_key.value.strip():
            subs.append('SubDL')
        lines.append(('[OK] ' if subs else '[WARN] ')
                     + 'subtitle services: %s'
                     % (', '.join(subs) if subs else 'none configured'))

        try:
            from .utils import epgexport
            lines.append(('[OK] ' if epgexport.available() else '[WARN] ')
                         + 'EPGImport %s'
                         % ('available' if epgexport.available()
                            else 'not installed (in-plugin guide still works)'))
        except Exception as e:
            lines.append('[FAIL] epgexport: %s' % e)

        try:
            from .utils import playlists
            found = playlists.path()
            lines.append(('[OK] ' if found else '[WARN] ')
                         + playlists.describe())
        except Exception as e:
            lines.append('[FAIL] playlist list: %s' % e)

        log = '/tmp/piip_engine.log'
        if os.path.exists(log):
            lines.append('Engine log: %s (%d bytes)'
                         % (log, os.path.getsize(log)))

        # Belt and braces: coerce each line as well as the joined result.
        return native('\n'.join(native(line) for line in lines))
