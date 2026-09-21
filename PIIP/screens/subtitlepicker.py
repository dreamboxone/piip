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
"""Search for and download a subtitle for whatever is playing."""

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.MenuList import MenuList
from Screens.Screen import Screen

from ..plugin import config
from ..providers.subtitles import SubtitleFinder, clean_title
from ..utils import srt
from ..utils.backdrop import backdrop
from ..utils.uisafe import safe_actions, BackgroundTask
from ..utils import skin as sk
from ..utils.compat import native

_c = config.plugins.piip

def build_skin():
    return sk.list_screen(
        'FarsiSubtitles', 'Subtitles', 'PIIP',
        buttons=[('BACK', sk.BTN_RED), ('DOWNLOAD', sk.BTN_GREEN),
                 ('LOCAL FILE', sk.ACCENT_WARM), ('EDIT TITLE', sk.BTN_BLUE)],
        hint='OK - Download   YELLOW - Local   BLUE/MENU - Edit title   EXIT - Back',
        header_widget='head', info=('status',), item_height=48)


class FarsiSubtitles(Screen):
    """Returns a srt.Subtitles instance through the close() callback."""


    def __init__(self, session, item):
        self.skin = build_skin()
        Screen.__init__(self, session)
        self.session = session
        self.item = item
        self.finder = SubtitleFinder(
            opensubtitles_key=_c.opensubtitles_key.value,
            subdl_key=_c.subdl_key.value,
            language=_c.sub_language.value)
        self.results = []
        self.errors = []
        self.error = None
        self.downloading = False
        self.search_title = clean_title(item.name)

        self['bg'] = Pixmap()
        self['head'] = Label('Searching for: %s' % self.search_title)
        self['list'] = MenuList([])
        self['status'] = Label('')
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions', 'MenuActions'],
            safe_actions(self, {'ok': self.choose, 'green': self.choose,
                                'cancel': self.cancel, 'red': self.cancel,
                                'yellow': self.openLocal,
                                'blue': self.editTitle,
                                'menu': self.editTitle}), -1)

        self.search_task = BackgroundTask(self, self._search, self._searched,
                                          'subtitle-search')
        self.download_task = BackgroundTask(self, self._download,
                                            self._downloaded,
                                            'subtitle-download')
        self.onLayoutFinish.append(self.paintBackdrop)
        self.onLayoutFinish.append(self.begin)
        self.onClose.append(self.search_task.stop)
        self.onClose.append(self.download_task.stop)

    def paintBackdrop(self):
        """A bound method, not a closure: Enigma2 execs anything else."""
        backdrop(self)

    # -------------------------------------------------------------- search

    def begin(self):
        if not self.finder.configured:
            self['status'].setText(native(
                'No subtitle API key configured.\n'
                'Add an OpenSubtitles or SubDL key in Settings.'))
            return
        self['status'].setText(native('Searching %s...'
                               % ', '.join(sorted(self.finder.services))))
        self.search_task.start()

    def _search(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            self.results, self.errors = self.finder.search(self.search_title)
        except Exception as e:
            self.error = '%s: %s' % (type(e).__name__, e)

    def _searched(self, _result, error):
        if error and not self.error:
            self.error = error
        self.searched()

    def searched(self):
        if self.error:
            self['status'].setText(native(self.error))
            return
        if not self.results:
            msg = 'Nothing found.'
            if self.errors:
                msg += '\n' + '\n'.join(self.errors)
            self['status'].setText(native(msg))
            return
        self['list'].setList([c.label() for c in self.results])
        note = '%d results   |   OK to download' % len(self.results)
        if self.errors:
            note += '\n' + '\n'.join(self.errors)
        self['status'].setText(native(note))

    # ------------------------------------------------------------ download

    def choose(self):
        if self.downloading or not self.results:
            return
        idx = self['list'].getSelectedIndex()
        if idx is None or idx >= len(self.results):
            return
        self.downloading = True
        self.chosen = self.results[idx]
        self.payload = None
        self['status'].setText(native('Downloading %s...' % self.chosen.name))
        self.download_task.start()

    def _download(self):
        """Runs on a worker thread: must not touch a widget or a timer."""
        try:
            self.payload = self.finder.download(self.chosen)
        except Exception as e:
            self.error = '%s: %s' % (type(e).__name__, e)

    def _downloaded(self, _result, error):
        if error and not self.error:
            self.error = error
        self.downloaded()

    def downloaded(self):
        self.downloading = False
        if self.error or not self.payload:
            self['status'].setText(native(self.error or 'Download failed.'))
            self.error = None
            return
        try:
            cues = srt.load(self.payload)
        except Exception as e:
            self['status'].setText(native('Could not parse subtitle: %s' % e))
            return
        if not cues:
            self['status'].setText(native('That file contained no subtitles.'))
            return
        self.close(srt.Subtitles(cues, source_name=self.chosen.name))

    def cancel(self):
        self.close(None)

    def editTitle(self):
        try:
            from Screens.VirtualKeyBoard import VirtualKeyBoard
            self.session.openWithCallback(self.titleEdited, VirtualKeyBoard,
                                          title='Subtitle search title',
                                          text=self.search_title)
        except ImportError:
            pass

    def titleEdited(self, text=None):
        if text is None:
            return
        self.search_title = native(text).strip()
        if not self.search_title:
            return
        self['head'].setText(native('Searching for: %s' % self.search_title))
        self.results, self.errors, self.error = [], [], None
        self['list'].setList([])
        self['status'].setText(native('Searching %s...' % self.search_title))
        self.search_task.start()

    def openLocal(self):
        """Pick an already-downloaded SRT file from the subtitle folder."""
        import os
        folder = native(_c.download_dir.value or '/media/hdd/movie/')
        try:
            names = sorted(x for x in os.listdir(folder)
                           if x.lower().endswith(('.srt', '.vtt')))
        except OSError:
            names = []
        if not names:
            self['status'].setText(native('No local SRT/VTT files in %s' % folder))
            return
        try:
            from Screens.ChoiceBox import ChoiceBox
            choices = [(native(name), os.path.join(folder, name))
                       for name in names]
            self.session.openWithCallback(self.localPicked, ChoiceBox,
                                          title='Local subtitles', list=choices)
        except ImportError:
            self.localPicked(choices[0])

    def localPicked(self, choice=None):
        if not choice:
            return
        path = choice[1] if isinstance(choice, (tuple, list)) else choice
        try:
            cues = srt.load(path)
            if not cues:
                raise ValueError('file contains no subtitle cues')
            self.close(srt.Subtitles(cues, source_name=native(path)))
        except Exception as exc:
            self['status'].setText(native('Could not open subtitle: %s' % exc))
