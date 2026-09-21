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
"""What one connected server holds: live TV, films, series, bouquets.

The reference plugin opens exactly this once a portal answers - a second
carousel, inside the server, rather than a list.
"""

from .carousel import CarouselScreen, build_skin as _build
from ..utils import servers, skin as sk
from ..utils.compat import native
from ..utils.uisafe import BackgroundTask
from ..plugin import config

_c = config.plugins.piip

CHIPS = (('EXIT  Back', sk.BTN_RED),
         ('OK  Open', sk.BTN_GREEN),
         ('< >  Browse', sk.ACCENT_WARM),
         ('INFO  Guide', sk.BTN_BLUE))


def build_skin():
    return _build('FarsiHome', CHIPS, subtitle=True)


class FarsiHome(CarouselScreen):
    NAME = 'FarsiHome'
    TITLE = 'PIIP'
    CHIPS = CHIPS
    SUBTITLE = True
    ITEMS = (
        ('Live TV', 'channels', 'live',
         'Watch live TV with Persian translation', 'bg_main.png'),
        ('Movies', 'movies', 'movies',
         'Films on demand, with resume', 'bg_main.png'),
        ('Series', 'series', 'series',
         'Series by season and episode', 'bg_main.png'),
        ('Bouquets', 'bouquets', 'bouquets',
         'Add these channels to the receiver list for normal zapping',
         'bg_main.png'),
        ('Downloads', 'downloads', 'movies',
         'Manage queued and completed downloads', 'bg_main.png'),
    )

    def __init__(self, session):
        CarouselScreen.__init__(self, session)
        self['title'].setText(native(
            (_c.active_server.value or 'PIIP').upper()))
        self.account_task = BackgroundTask(self, self._accountWorker,
                                           self._accountReady, 'home-account')
        self.onLayoutFinish.append(self.loadAccount)
        self.onClose.append(self.account_task.stop)

    # ------------------------------------------------------------- account

    def loadAccount(self):
        """Stalker and Xtream servers know when the subscription ends."""
        if servers.active().get('type') in ('stalker', 'xtream'):
            self['subtitle'].setText(native('Checking subscription...'))
            self.account_task.start()

    def _accountWorker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        if servers.active().get('type') == 'xtream':
            from .catalogue import make_xtream
            from ..providers.xtream import format_expiry
            api = make_xtream()
            info = api.login()
            return format_expiry(info.get('exp_date'))
        from ..plugin import make_stalker
        portal = make_stalker()
        portal.connect()
        return portal.expiry()

    def _accountReady(self, expiry, error):
        if error:
            self['subtitle'].setText('')
        elif expiry:
            self['subtitle'].setText(native('Expires: %s' % expiry))
        else:
            self['subtitle'].setText(native('Expiry: unlimited / not reported'))

    def refresh(self):
        entry = servers.active()
        where = servers.address(entry)
        if '://' in where:
            where = where.split('://', 1)[1].split('/', 1)[0]
        self['status'].setText(native(
            '%s: %s   |   translation %s to %s   |   API key %s   |   delay %ds'
            % (entry.get('type', '?').upper(),
               where or '(not set)',
               'on' if _c.translate.value else 'off',
               _c.language.value,
               'set' if _apikey() else 'MISSING',
               _c.delay.value)))

    def select(self):
        action = self.item()[1]
        kind = {'channels': 'live', 'movies': 'movies',
                'series': 'series'}.get(action)
        if kind and _c.source.value in ('xtream', 'stalker'):
            # As the reference: a server's categories come first.
            from .categories import FarsiCategories
            self.session.open(FarsiCategories, kind)
        elif action == 'channels':
            from .channels import FarsiChannels
            self.session.open(FarsiChannels)
        elif action == 'movies':
            from .vod import FarsiMovies
            self.session.open(FarsiMovies)
        elif action == 'series':
            from .vod import FarsiSeries
            self.session.open(FarsiSeries)
        elif action == 'bouquets':
            from .bouquets import FarsiBouquets
            self.session.open(FarsiBouquets)
        elif action == 'downloads':
            from .downloadmanager import FarsiDownloads
            self.session.open(FarsiDownloads)


def _apikey():
    from ..plugin import api_key
    return api_key()
