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
"""Keep plugin bugs from taking the receiver down.

Enigma2 runs key handlers straight off its main loop with nothing catching
exceptions: anything that escapes ends the process and writes a crash log.
Wrapping the handlers turns a plugin bug into a message on screen, which is
recoverable, instead of a reboot.
"""

import os
import threading
import time
import traceback

from .compat import native
from ..translate import redact

LOG = '/tmp/piip_ui.log'
_last_report = [0.0]
REPORT_INTERVAL = 3.0          # don't stack dialogs if a key is held down


def log_error(where, exc_text):
    try:
        with open(LOG, 'a') as fh:
            fh.write('%s %s\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'),
                                      where, redact.text(exc_text)))
    except (IOError, OSError):
        pass


def note(where, text):
    """Record something worth knowing that is not an error.

    enigma2's stdout is piped away on most images, so a print() is lost;
    this is the same file crashes are written to.
    """
    log_error(where, text)


def _notify(screen, where, message):
    """Show the failure without ever raising from the handler itself."""
    now = time.time()
    if now - _last_report[0] < REPORT_INTERVAL:
        return
    _last_report[0] = now
    session = getattr(screen, 'session', None)
    if session is None:
        return
    try:
        from Screens.MessageBox import MessageBox
        session.open(MessageBox,
                     native('PIIP hit a problem in %s:\n\n%s\n\n'
                            'The receiver kept running. Details are in %s'
                            % (where, message, LOG)),
                     MessageBox.TYPE_ERROR, timeout=12)
    except Exception:
        pass


def guarded(fn, screen=None, where=None):
    """Wrap a callable so an exception is reported instead of fatal."""
    label = where or getattr(fn, '__name__', 'action')

    def _run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            log_error(label, traceback.format_exc())
            _notify(screen, label, '%s: %s' % (type(exc).__name__, exc))
            return None

    _run.__name__ = getattr(fn, '__name__', 'guarded')
    _run.wrapped = fn
    return _run


def safe_actions(screen, actions):
    """Wrap every handler in an ActionMap dictionary."""
    out = {}
    for key, fn in actions.items():
        name = '%s.%s' % (type(screen).__name__,
                          getattr(fn, '__name__', key))
        out[key] = guarded(fn, screen, name)
    return out


def safe_callback(screen, fn, where=None):
    """Wrap a timer or thread completion callback the same way."""
    name = where or '%s.%s' % (type(screen).__name__,
                               getattr(fn, '__name__', 'callback'))
    return guarded(fn, screen, name)


def alive(screen):
    """Whether a screen is still open enough to be written to.

    Enigma2's Screen.doClose() deletes self.session and then clears the
    component dictionary, so a callback arriving afterwards raises KeyError
    on the first widget it touches.
    """
    if screen is None:
        return False
    if getattr(screen, 'session', None) is None:
        return False
    try:
        return len(screen) > 0
    except Exception:
        return True


class BackgroundTask(object):
    """Run slow work off the UI thread and deliver the result on the main loop.

    Enigma2 pins every eTimer to the thread that created it. Calling start()
    from a worker aborts the whole process with

        FATAL!: addTimer for instance 0x... must be called from thread N
                but is called from thread M

    so the usual "fire a one-shot timer from the worker to hop back" trick is
    not safe here. Instead the timer is started on the main thread and polls
    a flag the worker sets, which means start() and stop() are only ever
    called from the thread that owns the timer.
    """

    INTERVAL = 150          # ms between polls; fast enough to feel instant

    def __init__(self, screen, work, done, name='task'):
        self.screen = screen
        self.work = work
        self.done = done
        self.name = name
        self.result = None
        self.error = None
        self._finished = threading.Event()
        self._delivered = False
        self._thread = None
        self._timer = None

    # -- main thread ------------------------------------------------------

    def start(self):
        """Must be called from the Enigma2 main loop, e.g. onLayoutFinish."""
        from enigma import eTimer
        self.result = self.error = None
        self._finished.clear()
        self._delivered = False

        self._timer = eTimer()
        tick = guarded(self._tick, self.screen, '%s.tick' % self.name)
        try:
            self._timer.callback.append(tick)
        except AttributeError:                  # older enigma2 uses signals
            self._conn = self._timer.timeout.connect(tick)
        self._timer.start(self.INTERVAL, False)

        self._thread = threading.Thread(target=self._run,
                                        name='farsi-%s' % self.name)
        self._thread.daemon = True
        self._thread.start()

    def _tick(self):
        if not self._finished.is_set() or self._delivered:
            return
        self._delivered = True
        self.stop()
        if not alive(self.screen):
            # The screen went away while the work was running. Its widgets
            # are gone with it, so there is nothing to deliver to.
            return
        self.done(self.result, self.error)

    def stop(self):
        """Also main thread only; safe to call more than once."""
        self._delivered = True          # nothing lands after a stop
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def running(self):
        return self._thread is not None and not self._finished.is_set()

    # -- worker thread ----------------------------------------------------

    def _run(self):
        try:
            self.result = self.work()
        except Exception as exc:
            self.error = '%s: %s' % (type(exc).__name__, exc)
            log_error(self.name, traceback.format_exc())
        finally:
            self._finished.set()
