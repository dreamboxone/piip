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
"""Settings screen."""

import os

from Components.ActionMap import ActionMap
from Components.config import (getConfigListEntry, config, configfile,
                               ConfigNothing, ConfigDirectory)
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from ..utils import skin as sk
from ..utils.uisafe import safe_actions
from ..utils.compat import native

from ..plugin import NAME, VERSION

_c = config.plugins.piip

def build_skin():
    """The settings panel, in the reference plugin's colours."""
    desktop = sk.desktop_width()
    factor = (4.0 / 3.0 if desktop >= 2560 else
              (1.0 if desktop >= 1920 else 2.0 / 3.0))
    q = lambda value: int(round(value * factor))
    W, H = q(1400), q(700)
    head, foot, pad = q(80), q(80), q(30)
    item = q(52)

    # The reference puts the version in the right-hand corner here, and a
    # settings panel is the one screen where that is the useful thing.
    body = [sk.header('Settings', '%s v%s' % (NAME, VERSION),
                      width=W, height=head, wide=True)]
    list_h = q(480)
    body.append(
        '<widget name="config" position="%d,%d" size="%d,%d" '
        'scrollbarMode="showOnDemand" %s itemHeight="%d" zPosition="1"/>'
        % (pad, q(100), W - 2 * pad, list_h, sk.list_attrs(), item))
    # Hybrid keeps help out of the settings geometry.  Retain the widget so
    # existing code can still update it without painting over the config.
    body.append(
        '<widget name="help" position="0,0" size="1,1" font="Regular;10" '
        'foregroundColor="%s" transparent="1"/>' % sk.TEXT_DIM)

    fy = q(605)
    body.append('<eLabel position="0,%d" size="%d,2" backgroundColor="%s"/>'
                % (fy - 10, W, sk.BTN_BLUE))
    body.append('<eLabel position="0,%d" size="%d,%d" backgroundColor="%s" '
                'transparent="0"/>' % (fy, W, foot, sk.HEADER))
    cw, ch, gap = q(240), q(52), q(30)
    x, cy = q(590), q(619)
    body.append(sk.chip('Red - Clear Cache', x, cy, sk.BTN_RED, cw, ch,
                        font=q(24), wide=True))
    body.append(sk.chip('Green - Save', x + cw + gap, cy, sk.BTN_GREEN,
                        cw, ch, font=q(24), wide=True, fg='#000000'))
    body.append(sk.chip('Exit - Cancel', x + 2 * (cw + gap), cy, sk.BTN_GREY,
                        cw, ch, font=q(24), wide=True, fg='#000000'))
    # Widgets the base class expects even though the chips replace them.
    body.append('<widget name="key_red" position="0,0" size="1,1" '
                'font="Regular;10" transparent="1"/>')
    body.append('<widget name="key_green" position="0,0" size="1,1" '
                'font="Regular;10" transparent="1"/>')
    return sk.dialog('FarsiSetup', (chr(10) + '  ').join(body),
                     width=W, height=H, wide=True)

HELP = {
    'API key': 'Optional here: a key in /root/apikey.txt or /home/root/apikey.txt (or apikey.txt beside '
               'the plugin) is used first. Without any key, channels still play '
               'but nothing is translated.',
    'Delay': 'How far the picture is held back so the translated speech can '
             'catch up. Raise it if the translation arrives late.',
    'Max backlog': 'When the translation falls further behind than this, the '
                   'oldest translated audio is dropped to re-sync with the picture.',
    'Stream bitrate while translating': 'On a slow or unstable connection '
                                        'pick a lower rate: the channel is read '
                                        'from a lighter version and the picture '
                                        'freezes less. Automatic uses the best.',
    'Channel volume': 'Volume of the original channel audio in the mix.',
    'Translation volume': 'Volume of the Persian translation in the mix.',
    'ffmpeg': 'Path to the ffmpeg binary on the receiver. Run "which ffmpeg" '
              'over SSH if unsure.',
    'Translated audio in bouquets': 'When on, zapping to an exported channel '
                                    'starts the translation engine. Costs a '
                                    'few seconds per zap.',
    'Resolver port': 'Local port the bouquet entries point at. Changing it '
                     'means re-exporting the bouquets.',
    'OpenSubtitles API Key': 'Free key from opensubtitles.com. Either service '
                             'is enough; both give more results.',
    'SubDL API key': 'Free key from subdl.com. Often better for Persian.',
    'Model override': 'Leave empty to use Gemini 3.5 Live Translate. Only '
                      'set this if a newer translation model is released.',
    'Portal list URL': 'Where LOAD ONLINE fetches a Stalker portal list '
                       'from, on the saved-servers screen (MENU, then INFO).',
    'XMLTV URL': 'Only needed for M3U playlists that carry no url-tvg '
                 'attribute. Xtream and Stalker fetch the guide themselves.',
    'Guide enabled': 'Turn off to skip all guide lookups, which makes '
                     'channel lists load faster on a slow receiver.',
    'Download / Subtitle Directory': 'Where movies, episodes and subtitles are saved.',
    'Poster / Art Cache Directory': 'Persistent cache for channel and VOD artwork.',
    'Show +18 Adult Content': 'Show categories and titles normally hidden by the adult filter.',
    'Items per Page (Poster Count)': 'Number of cover entries prefetched for each page.',
    'VOD/Series Skin Style': 'Default list, Hybrid carousel, or cover collection layout.',
    'Default VOD Stream Type': 'Default Enigma2 player used for movies and episodes.',
    'Default Live Stream Type': 'Default Enigma2 player used for live channels.',
    'TMDB API key': 'Optional key for movie/series metadata, backdrops and logos.',
}


class FarsiSetup(Screen, ConfigListScreen):

    def __init__(self, session):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self['help'] = Label('')
        self['key_red'] = Label('Cancel')
        self['key_green'] = Label('Save')

        ConfigListScreen.__init__(self, [], session=session,
                                  on_change=self.changed)
        self.buildList()

        self['actions'] = ActionMap(
            ['SetupActions', 'ColorActions'],
            safe_actions(self, {
                'save': self.save,
                'green': self.save,
                'cancel': self.cancel,
                'red': self.clearCache,
                'ok': self.keyOK,
            }), -2)
        self.changed()

    def clearCache(self):
        """Ask before clearing downloaded artwork, as HybridIPTV does."""
        message = ('Are you sure you want to clear all downloaded posters, '
                   'backdrops and logos from the cache folder?')
        self.session.openWithCallback(self._doClearCache, MessageBox, message,
                                      MessageBox.TYPE_YESNO, default=False)

    def _doClearCache(self, answer):
        if not answer:
            return
        path = os.path.abspath(native(_c.picon_cache_dir.value or ''))
        # Never treat a broad path as a cache, even if it was entered by hand.
        if not path or path in ('/', '/root', '/media', '/media/hdd'):
            self.session.open(MessageBox, 'Unsafe cache directory',
                              MessageBox.TYPE_ERROR, timeout=5)
            return
        removed = 0
        try:
            for root, _dirs, files in os.walk(path):
                for filename in files:
                    os.unlink(os.path.join(root, filename))
                    removed += 1
            self.session.open(MessageBox,
                              native('Successfully cleared %d items from the cache!' % removed),
                              MessageBox.TYPE_INFO, timeout=4)
        except Exception as exc:
            self.session.open(MessageBox, native('Failed to clear cache: %s' % exc),
                              MessageBox.TYPE_ERROR, timeout=6)

    def sep(self, title):
        return getConfigListEntry('--- %s ---' % title, ConfigNothing())

    def keyOK(self):
        """Edit values; directory rows use Hybrid's LocationBox picker."""
        current = self['config'].getCurrent()
        if not current or len(current) < 2 or isinstance(current[1], ConfigNothing):
            return
        selected = current[1]
        if isinstance(selected, ConfigDirectory):
            try:
                from Screens.LocationBox import LocationBox
                self._location_setting = selected
                self.session.openWithCallback(
                    self.locationBoxCallback, LocationBox,
                    text='Select directory', currDir=native(selected.value))
                return
            except ImportError:
                pass
        try:
            ConfigListScreen.keyOK(self)
        except (AttributeError, TypeError):
            # Images without ConfigListScreen.keyOK still edit selections via
            # LEFT/RIGHT; importantly, OK must never save the whole page.
            return

    def locationBoxCallback(self, result=None):
        if not result:
            return
        setting = getattr(self, '_location_setting', None)
        if setting is not None:
            setting.value = native(result)
            self.changed()

    def buildList(self):
        # Which server you are on is chosen on the main menu and kept in
        # the saved-server list, not here.
        lst = [
            getConfigListEntry('OpenSubtitles API Key', _c.opensubtitles_key),
            getConfigListEntry('Download / Subtitle Directory', _c.download_dir),
            getConfigListEntry('Poster / Art Cache Directory', _c.picon_cache_dir),
            getConfigListEntry('Subtitle Position', _c.sub_position),
            getConfigListEntry('Subtitle Size', _c.sub_size),
            getConfigListEntry('Subtitle Color', _c.sub_color),
            getConfigListEntry('Default VOD Stream Type', _c.vod_streamtype),
            getConfigListEntry('Show +18 Adult Content', _c.show_adult),
            getConfigListEntry('Items per Page (Poster Count)', _c.poster_count),
            getConfigListEntry('VOD/Series Skin Style', _c.skin_style),
            self.sep('PIIP extras'),
            getConfigListEntry('SubDL API key', _c.subdl_key),
            getConfigListEntry('Subtitle Language', _c.sub_language),
            getConfigListEntry('TMDB API key', _c.tmdb_key),
            getConfigListEntry('WebIF port', _c.webif_port),
            self.sep('Guide'),
            getConfigListEntry('Guide enabled', _c.epg_enabled),
            getConfigListEntry('XMLTV URL', _c.xmltv_url),
            self.sep('Stalker portals'),
            getConfigListEntry('Portal list URL', _c.portal_list_url),
            self.sep('Bouquets'),
            getConfigListEntry('Translated audio in bouquets',
                               _c.bouquet_translate),
            getConfigListEntry('Resolver port', _c.resolver_port),
            self.sep('Advanced'),
            getConfigListEntry('Default Live Stream Type', _c.service_type),
            getConfigListEntry('ffmpeg', _c.ffmpeg),
            getConfigListEntry('Local stream port', _c.http_port),
            getConfigListEntry('Control port', _c.control_port),
            getConfigListEntry('User agent', _c.user_agent),
            self.sep('Translation'),
            getConfigListEntry('Translation enabled', _c.translate),
            getConfigListEntry('API key', _c.api_key),
            getConfigListEntry('Model override', _c.model_custom),
            getConfigListEntry('Target language', _c.language),
            getConfigListEntry('Delay', _c.delay),
            getConfigListEntry('Max backlog', _c.max_backlog),
            getConfigListEntry('Stream bitrate while translating',
                               _c.translate_max_bitrate),
            getConfigListEntry('Channel volume', _c.vol_original),
            getConfigListEntry('Translation volume', _c.vol_translated),
        ]
        self['config'].list = lst
        self['config'].l.setList(lst)

    def changed(self):
        try:
            entry = self['config'].getCurrent()
        except Exception:
            return
        if entry:
            self['help'].setText(native(HELP.get(entry[0], '')))

    def save(self):
        for item in self['config'].list:
            if len(item) > 1:
                item[1].save()
        configfile.save()
        self.close(True)

    def cancel(self):
        for item in self['config'].list:
            if len(item) > 1:
                item[1].cancel()
        self.close(False)
