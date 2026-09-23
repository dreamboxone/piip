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
"""A stand-in for the Enigma2 runtime, strict where Enigma2 is strict.

Enigma2 has no mercy: an exception raised inside a key handler or during
screen construction takes the whole box down with a crash log. Its widgets
are SWIG wrappers around C++, so setText() rejects anything that is not a
real str with

    TypeError: in method 'eLabel_setText', argument 2 of type
               'std::string const &'

This module reproduces that behaviour so the same mistake fails here, on a
developer machine, instead of on a receiver in someone's living room.

Install it with install() before importing any plugin screen.
"""

import os
import sys
import types

# Every setText() value seen, so tests can assert on what the UI displays.
RENDERED = []
# Every screen instantiated through the fake session.
OPENED = []


class SwigTypeError(TypeError):
    """What Enigma2 raises when a widget is handed a non-str."""


def _check_text(value, method='eLabel_setText'):
    """Mimic the SWIG typemap for std::string."""
    if not isinstance(value, str):
        raise SwigTypeError(
            "in method '%s', argument 2 of type 'std::string const &' "
            "(got %s: %r)" % (method, type(value).__name__, value))
    return value


# --------------------------------------------------------------- widgets

class GUIComponent(object):
    def __init__(self, *a, **kw):
        self.visible = True

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def GUIcreate(self, parent=None):
        pass


class Label(GUIComponent):
    def __init__(self, text=''):
        GUIComponent.__init__(self)
        self.message = ''
        self.setText(text)

    def setText(self, text):
        _check_text(text)
        self.message = text
        RENDERED.append(text)

    def getText(self):
        return self.message


class ProgressBar(GUIComponent):
    def __init__(self, *a, **kw):
        GUIComponent.__init__(self)
        self.value = 0

    def setValue(self, value):
        if not isinstance(value, int) or isinstance(value, bool):
            raise SwigTypeError(
                "in method 'eSlider_setValue', argument 2 of type 'int' "
                "(got %s: %r)" % (type(value).__name__, value))
        self.value = value


class Pixmap(GUIComponent):
    """A picture widget. Enigma2 exposes the real work through .instance."""

    def __init__(self, *a, **kw):
        GUIComponent.__init__(self)
        self.filename = None
        self.instance = self

    def setPixmap(self, picture):
        self.filename = picture

    def setPixmapFromFile(self, path):
        if not isinstance(path, str):
            raise SwigTypeError(
                "in method 'ePixmap_setPixmapFromFile', argument 2 of type "
                "'std::string const &' (got %s)" % type(path).__name__)
        if not os.path.exists(path):
            raise IOError('no such image: %s' % path)
        self.filename = path


class MenuList(GUIComponent):
    def __init__(self, items=None, *a, **kw):
        GUIComponent.__init__(self)
        self.list = []
        self.index = 0
        self.setList(items or [])

    def setList(self, items):
        for item in items:
            if isinstance(item, str):
                continue
            if isinstance(item, tuple):
                continue
            raise SwigTypeError(
                'menu entries must be str or tuple, got %s: %r'
                % (type(item).__name__, item))
        self.list = list(items)
        if self.index >= len(self.list):
            self.index = 0

    def getSelectedIndex(self):
        return self.index if self.list else None

    def moveToIndex(self, index):
        if 0 <= index < len(self.list):
            self.index = index

    def up(self):
        if self.list:
            self.index = (self.index - 1) % len(self.list)

    def down(self):
        if self.list:
            self.index = (self.index + 1) % len(self.list)

    def getCurrent(self):
        return self.list[self.index] if self.list else None


class ActionMap(object):
    def __init__(self, contexts, actions=None, prio=0):
        self.actions = dict(actions or {})

    def action(self, context, action):
        fn = self.actions.get(action)
        return fn() if fn else None


class NumberActionMap(ActionMap):
    """Enigma2 passes the digit to a handler bound to a number key.

    NumberActionMap.action: `self.actions[action](int(action))`. A handler
    that takes no argument is a TypeError on the receiver, which is how
    the player's subtitle and guide keys were silently dead.
    """

    DIGITS = ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')

    def action(self, context, action):
        fn = self.actions.get(action)
        if fn is None:
            return None
        if action in self.DIGITS:
            return fn(int(action))
        return fn()


# ----------------------------------------------------------------- timers

class eTimer(object):
    """Records what was scheduled; nothing fires on its own."""

    instances = []

    def __init__(self):
        self.callback = []
        self.interval = None
        self.running = False
        eTimer.instances.append(self)

    def start(self, interval, singleshot=False):
        self.interval = interval
        self.running = True

    def stop(self):
        self.running = False

    def fire(self):
        """Run the callbacks the way the mainloop eventually would."""
        for cb in list(self.callback):
            cb()


class eServiceReference(object):
    """Enigma2 builds these as (type, flags, path); record all three so a
    test can check the reference that would actually be played."""

    def __init__(self, *args):
        self.args = args
        self.name = ''
        self.type = None
        self.flags = None
        self.path = ''
        if len(args) >= 3:
            self.type, self.flags, self.path = args[0], args[1], args[2]
            # The real constructor is a SWIG binding: it takes native str.
            _check_text(self.path, 'eServiceReference_path')
        elif len(args) == 1 and isinstance(args[0], str):
            self.path = args[0]

    def setName(self, name):
        _check_text(name, 'eServiceReference_setName')
        self.name = name

    def toString(self):
        return '%s:%s:%s' % (self.type, self.flags, self.path)


class _Size(object):
    def __init__(self, w, h):
        self._w, self._h = w, h

    def width(self):
        return self._w

    def height(self):
        return self._h


class _Desktop(object):
    def size(self):
        return _Size(1920, 1080)


def getDesktop(_index=0):
    return _Desktop()


class eDVBDB(object):
    @staticmethod
    def getInstance():
        raise RuntimeError('no eDVBDB in the stub')


# --------------------------------------------------------------- screens

class Screen(dict):
    def __init__(self, session, *a, **kw):
        dict.__init__(self)
        self.session = session
        self.onLayoutFinish = []
        self.onClose = []
        self.onShow = []
        self.onHide = []
        self.instance = None
        self.skinName = None

    def setTitle(self, title):
        _check_text(title, 'eWindow_setTitle')

    def close(self, *args):
        self.closed_with = args

    def show(self):
        pass

    def hide(self):
        pass

    def applySkin(self):
        """What Components/GUISkin.py does: iterate self.items().

        Screen subclasses dict in Enigma2, so an attribute named items,
        keys, values or get shadows the method this loop relies on and the
        receiver crashes the moment the screen is skinned.
        """
        for key, val in self.items():
            create = getattr(val, 'GUIcreate', None)
            if create is not None:
                create(self.instance)

    def _checkCallback(self, fn, where):
        """Enigma2 execs anything that is not a bound method as source.

        GUISkin.createGUIScreen: `if not isinstance(f, type(self.close)):
        exec(f, ...)`. A lambda or a partial there is a TypeError on the
        receiver and a screen that never opens, so it is one here too.
        """
        if not isinstance(fn, type(self.close)):
            raise TypeError(
                'exec: arg 1 must be a string, file, or code object '
                '(%s registered %r, which Enigma2 would exec as source)'
                % (where, fn))

    def layoutFinished(self):
        """Run what Enigma2 runs once the skin has been applied."""
        for fn in list(self.onLayoutFinish):
            self._checkCallback(fn, 'onLayoutFinish')
            fn()

    def doClose(self):
        """Close the way Enigma2 closes.

        Screen.doClose() deletes self.session and then clears the component
        dictionary, so anything arriving afterwards - a background task's
        callback, say - hits a KeyError on the first widget it touches.
        """
        for fn in list(self.onClose):
            self._checkCallback(fn, 'onClose')
            fn()
        self.session = None
        self.clear()


class MessageBox(Screen):
    TYPE_YESNO = 0
    TYPE_INFO = 1
    TYPE_WARNING = 2
    TYPE_ERROR = 3

    def __init__(self, session, text, type=TYPE_YESNO, timeout=-1,
                 close_on_any_key=False, default=True, **kw):
        Screen.__init__(self, session)
        # This is the exact path that crashed a receiver: MessageBox puts the
        # text straight into a Label, and Label is a SWIG wrapper.
        self['text'] = Label(text)
        self.type = type


class ConfigListScreen(object):
    def __init__(self, entries, session=None, on_change=None, **kw):
        self.entries = list(entries or [])
        self.onChangeCallback = on_change
        self['config'] = _ConfigList(self.entries)

    def keyOK(self):
        pass


class _ConfigList(object):
    def __init__(self, entries):
        self.list = list(entries or [])
        self.l = self
        self.index = 0

    def setList(self, entries):
        self.list = list(entries or [])

    def getCurrent(self):
        return self.list[self.index] if self.list else None


class Session(object):
    """Records opened dialogs and runs their layout, as Enigma2 does."""

    def __init__(self):
        self.nav = _Nav()
        self.dialogs = []

    def open(self, screen, *args, **kwargs):
        dlg = screen(self, *args, **kwargs)
        OPENED.append(dlg)
        self.dialogs.append(dlg)
        # Enigma2 applies the skin immediately, which is where a bad
        # setText() value blows up.
        dlg.applySkin()
        dlg.layoutFinished()
        return dlg

    def openWithCallback(self, callback, screen, *args, **kwargs):
        dlg = self.open(screen, *args, **kwargs)
        dlg._callback = callback
        return dlg


class _Nav(object):
    def __init__(self):
        self.playing = None

    def playService(self, ref):
        self.playing = ref

    def stopService(self):
        self.playing = None

    def getCurrentService(self):
        return None

    def getCurrentlyPlayingServiceReference(self):
        return self.playing


# ---------------------------------------------------------------- config

class ConfigElement(object):
    def __init__(self, default=None, **kw):
        self.default = default
        self.value = default
        self.saved = False

    def save(self):
        self.saved = True

    def cancel(self):
        self.value = self.default


class ConfigText(ConfigElement):
    def __init__(self, default='', fixed_size=True, **kw):
        ConfigElement.__init__(self, default)


class ConfigPassword(ConfigText):
    pass


class ConfigDirectory(ConfigText):
    pass


class ConfigYesNo(ConfigElement):
    def __init__(self, default=False, **kw):
        ConfigElement.__init__(self, default)


class ConfigInteger(ConfigElement):
    def __init__(self, default=0, limits=(0, 100), **kw):
        ConfigElement.__init__(self, default)
        self.limits = limits


class ConfigSlider(ConfigElement):
    def __init__(self, default=0, increment=1, limits=(0, 100), **kw):
        ConfigElement.__init__(self, default)
        self.increment = increment
        self.limits = limits


class ConfigSelection(ConfigElement):
    def __init__(self, default=None, choices=None, **kw):
        self.choices = choices or []
        if default is None and self.choices:
            first = self.choices[0]
            default = first[0] if isinstance(first, tuple) else first
        ConfigElement.__init__(self, default)


class ConfigNothing(ConfigElement):
    pass


class ConfigLocations(ConfigElement):
    def __init__(self, default=None, **kw):
        ConfigElement.__init__(self, default or [])


class ConfigSubsection(object):
    pass


class _ConfigRoot(object):
    def __init__(self):
        self.plugins = ConfigSubsection()


def getConfigListEntry(*args):
    return tuple(args)


class _ConfigFile(object):
    def save(self):
        pass


# ---------------------------------------------------------------- plugin

class PluginDescriptor(object):
    WHERE_PLUGINMENU = 'menu'
    WHERE_EXTENSIONSMENU = 'ext'
    WHERE_SESSIONSTART = 'session'

    def __init__(self, name='', description='', where=None, icon=None,
                 fnc=None, **kw):
        self.name = name
        self.description = description
        self.where = where
        self.icon = icon
        self.fnc = fnc


# ------------------------------------------------------------- installer

def multi_content_entry(pos=None, size=None, font=0, flags=0, text=0,
                        color=None, color_sel=None, backcolor=None,
                        backcolor_sel=None, border_width=None,
                        border_color=None):
    """The signature a current image's MultiContentEntryText carries."""
    return (pos, size, font, flags, text, color)


def multi_content_pixmap(pos=None, size=None, png=None, backcolor=None,
                         backcolor_sel=None, flags=None, scale_flags=None):
    """Its pixmap entry, with the scale_flags older images do not have."""
    return (pos, size, png, flags, scale_flags)


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install():
    """Put the fake Enigma2 into sys.modules. Safe to call twice."""
    if 'enigma' in sys.modules and getattr(sys.modules['enigma'],
                                           '_farsi_stub', False):
        return

    # SCALE_STRETCH and the MultiContent helpers below model a current
    # image. Older receivers have neither, which the skin code detects and
    # works around; test_image_compat.py covers that path.
    _module('enigma', eTimer=eTimer, eServiceReference=eServiceReference,
            eDVBDB=eDVBDB, getDesktop=getDesktop, SCALE_STRETCH=1,
            BT_SCALE=2, _farsi_stub=True)

    for pkg in ('Components', 'Screens', 'Plugins', 'Tools'):
        m = _module(pkg)
        m.__path__ = []

    _module('Components.ActionMap', ActionMap=ActionMap,
            NumberActionMap=NumberActionMap)
    _module('Components.Label', Label=Label)
    _module('Components.MenuList', MenuList=MenuList)
    _module('Components.Pixmap', Pixmap=Pixmap)
    _module('Components.ProgressBar', ProgressBar=ProgressBar)
    _module('Components.GUIComponent', GUIComponent=GUIComponent)
    _module('Components.ConfigList', ConfigListScreen=ConfigListScreen)
    _module('Components.config',
            config=_ConfigRoot(), configfile=_ConfigFile(),
            ConfigSubsection=ConfigSubsection, ConfigText=ConfigText,
            ConfigPassword=ConfigPassword, ConfigYesNo=ConfigYesNo,
            ConfigSelection=ConfigSelection, ConfigInteger=ConfigInteger,
            ConfigSlider=ConfigSlider, ConfigNothing=ConfigNothing,
            ConfigDirectory=ConfigDirectory, ConfigLocations=ConfigLocations,
            getConfigListEntry=getConfigListEntry)
    _module('Tools.LoadPixmap',
            LoadPixmap=lambda path, *a, **kw: path)
    _module('Components.MultiContent',
            MultiContentEntryText=multi_content_entry,
            MultiContentEntryPixmapAlphaTest=multi_content_pixmap,
            MultiContentTemplateColor=lambda colour: colour)
    _module('Screens.Screen', Screen=Screen)
    _module('Screens.MessageBox', MessageBox=MessageBox)
    _module('Plugins.Plugin', PluginDescriptor=PluginDescriptor)


def reset():
    del RENDERED[:]
    del OPENED[:]
    del eTimer.instances[:]
