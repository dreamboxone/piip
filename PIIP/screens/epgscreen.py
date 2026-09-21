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
"""Programme guide for one channel."""

import time

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Components.ProgressBar import ProgressBar
from Screens.Screen import Screen

from ..plugin import config
from ..providers import epg as epgmod
from ..providers.models import MediaItem, MOVIE
from ..utils.uisafe import safe_actions, BackgroundTask
from ..utils import skin as sk
from ..utils.backdrop import backdrop
from ..utils.compat import native

_c = config.plugins.piip

def build_skin(title='Programme guide'):
    return sk.list_screen(
        'FarsiEPG', title, 'PIIP',
        buttons=[],
        hint='EXIT - Back',
        header_widget='channel', progress='progress',
        # The selected programme's time, title and description get a tall
        # block under the list; one line clipped them into the status.
        info=('desc', 'now', 'status'), item_height=48, layout='summary')


class FarsiEPG(Screen):

    def __init__(self, session, item, loader=None, catchup=None,
                 catchup_mode=False):
        """`loader` is a callable returning [Programme]; run off the UI thread.

        `catchup_mode` is the reference's CATCHUP screen: the same guide,
        opened from the list's catch-up key and worded for recordings.
        """
        self.catchup_mode = bool(catchup_mode and catchup)
        self.skin = build_skin('CATCHUP' if self.catchup_mode
                               else 'Programme guide')
        Screen.__init__(self, session)
        self.session = session
        self.item = item
        self.loader = loader
        self.catchup = catchup
        self.programmes = []
        self.error = None

        self['bg'] = Pixmap()
        self['channel'] = Label(item.name)
        self['now'] = Label('')
        self['progress'] = ProgressBar()
        self['list'] = MenuList([])
        self['desc'] = Label('')
        self['status'] = Label('Loading EPG...' if self.catchup_mode
                               else 'Loading guide...')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'ColorActions'],
            safe_actions(self, {
                'ok': self.openSelected,
                'cancel': self.close,
                'up': self.up,
                'down': self.down,
                'red': self.close,
            }), -1)

        self.task = BackgroundTask(self, self._worker, self._loaded, 'epg')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.load)
        self.onClose.append(self.task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self)

    def load(self):
        self.task.start()

    def _worker(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            self.programmes = list(self.loader() if self.loader else [])
        except Exception as e:
            self.error = '%s: %s' % (type(e).__name__, e)

    def _loaded(self, _result, error):
        if error and not self.error:
            self.error = error
        self.loaded()

    def loaded(self):
        if self.error:
            self['status'].setText(native(self.error))
            return
        if not self.programmes:
            self['status'].setText(native('No guide data for this channel.'))
            return
        now = int(time.time())
        rows = []
        recorded = 0
        for p in self.programmes:
            if p.running_at(now):
                marker = '>'
            elif self.catchup and p.stop and p.stop <= now:
                marker = '*'            # finished: OK plays the recording
                recorded += 1
            else:
                marker = ' '
            rows.append('%s %s  %s' % (marker, p.span() or '--:--', p.title))
        self['list'].setList(rows)

        current = None
        for idx, p in enumerate(self.programmes):
            if p.running_at(now):
                current = p
                self['list'].moveToIndex(idx)
                break
        if current:
            self['now'].setText(native('Now: %s' % current.title))
            self['progress'].setValue(current.progress_at(now))
        if self.catchup_mode:
            self['status'].setText(native(
                '%d program(s) available%s' % (recorded, '   |   * OK - play'
                                               if recorded else '')))
        else:
            self['status'].setText(native(
                '%d programmes%s' % (len(self.programmes),
                                     '   |   * OK - play recording'
                                     if recorded else '')))
        self.showDetail()

    def _current(self):
        idx = self['list'].getSelectedIndex()
        if idx is None or idx >= len(self.programmes):
            return None
        return self.programmes[idx]

    def showDetail(self):
        p = self._current()
        if not p:
            self['desc'].setText(native(''))
            return
        parts = [p.span(), p.title]
        if p.desc:
            parts.append(p.desc)
        self['desc'].setText(native('\n'.join(x for x in parts if x)[:600]))

    def openSelected(self):
        programme = self._current()
        if not programme or programme.stop > int(time.time()) or not self.catchup:
            self.showDetail()
            return
        self['status'].setText(native('Resolving catchup stream...'))
        try:
            url = self.catchup(programme)
        except Exception as exc:
            self['status'].setText(native('Catch-up failed: %s' % exc))
            return
        item = MediaItem('%s — %s' % (self.item.name, programme.title),
                         url=url, kind=MOVIE,
                         duration=programme.duration, plot=programme.desc,
                         logo=self.item.logo)
        from .player import FarsiPlayer
        self.session.open(FarsiPlayer, item)

    def up(self):
        self['list'].up()
        self.showDetail()

    def down(self):
        self['list'].down()
        self.showDetail()


def loader_for(item, source, stalker=None, xtream=None, index=None,
               full=False):
    """Build a zero-argument callable that fetches this channel's guide.

    `full` asks for past programmes too, which is what a guide needs to
    offer catch-up; the player's now/next line only wants the short one.
    """
    def _load():
        if source == 'stalker' and stalker is not None:
            if full:
                return stalker.full_epg(item.item_id,
                                        days=getattr(item, 'archive', 0))
            return stalker.short_epg(item.item_id, size=24)
        if source == 'xtream' and xtream is not None:
            if full:
                # The day table carries the finished programmes catch-up
                # plays; the short guide only looks ahead.
                progs = xtream.full_epg(item.item_id)
                return progs or xtream.short_epg(item.item_id, limit=24)
            progs = xtream.short_epg(item.item_id, limit=24)
            return progs or xtream.full_epg(item.item_id)
        if index is not None:
            key = item.tvg_id or item.tvg_name or item.name
            progs = index.upcoming(key)
            if progs:
                return progs
        if source == 'm3u':
            # No XMLTV entry: the receiver may have the channel's guide
            # itself, from the satellite service the stream carries.
            from ..utils import e2epg
            return e2epg.programmes(item)
        return []
    return _load


def catchup_for(item, source, stalker=None, xtream=None):
    if source == 'stalker' and stalker is not None:
        from ..providers.stalker import token_of
        cmd = token_of(item)
        if cmd:
            return lambda programme: stalker.catchup_link(
                cmd, programme.start, programme.duration)
    if source == 'xtream' and xtream is not None and item.item_id:
        return lambda programme: xtream.catchup_url(
            item.item_id, programme.start, programme.duration,
            item.ext or 'ts')
    return None
