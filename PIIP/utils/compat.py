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
"""Python 2.7 / 3.x compatibility, and the native-str discipline the GUI needs.

Enigma2 images in the field still run Python 2.7. Its widgets are SWIG
wrappers around C++ std::string, and the typemap accepts only the native
`str` type. On Python 2 that means UTF-8 encoded bytes, and handing it a
`unicode` raises

    TypeError: in method 'eLabel_setText', argument 2 of type
               'std::string const &'

which takes the whole receiver down. Anything read from a file, a socket or
a JSON payload arrives as `unicode` on Python 2, so every string that
reaches a widget has to go through native() first.
"""

import os
import subprocess
import sys

PY2 = sys.version_info[0] == 2

if PY2:                                              # pragma: no cover
    string_types = (str, unicode)                    # noqa: F821
    text_type = unicode                              # noqa: F821
    binary_type = str
else:
    string_types = (str,)
    text_type = str
    binary_type = bytes


def native(value, encoding='utf-8'):
    """Coerce anything to the interpreter's native `str`.

    This is what every widget, service reference and window title must be
    given. On Python 2 the result is UTF-8 bytes, which is exactly what
    Enigma2 renders; on Python 3 it is a normal str.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ''
    if PY2:                                          # pragma: no cover
        if isinstance(value, text_type):
            return value.encode(encoding, 'replace')
        return str(value)
    if isinstance(value, bytes):
        return value.decode(encoding, 'replace')
    return str(value)


def unicode_text(value, encoding='utf-8'):
    """Coerce to the unicode type, for parsing and comparison."""
    if isinstance(value, text_type):
        return value
    if value is None:
        return text_type('')
    if isinstance(value, binary_type):
        return value.decode(encoding, 'replace')
    return text_type(value)


def to_bytes(value, encoding='utf-8'):
    """Coerce to bytes, for sockets and files opened in binary mode."""
    if isinstance(value, binary_type):
        return value
    if isinstance(value, text_type):
        return value.encode(encoding, 'replace')
    return native(value).encode(encoding, 'replace') if not PY2 else str(value)


def byte_values(data):
    """Iterate a byte string as integers on both Pythons.

    Indexing bytes gives ints on Python 3 but one-character strs on
    Python 2, which silently breaks any XOR or arithmetic on them.
    """
    return bytearray(data)


def devnull():
    """subprocess.DEVNULL does not exist on Python 2."""
    handle = getattr(subprocess, 'DEVNULL', None)
    if handle is not None:
        return handle
    return open(os.devnull, 'r+b')


def popen_keep_fds(kwargs, fds):
    """Ask Popen to keep the given fds open in the child.

    Python 3 has pass_fds. Python 2 has no such option, so the fds are kept
    by not closing any, which is safe here because the child is spawned
    immediately after they are created.
    """
    if PY2:                                          # pragma: no cover
        kwargs['close_fds'] = False
    else:
        kwargs['pass_fds'] = tuple(fds)
        kwargs['close_fds'] = True
    return kwargs


def replace_file(src, dst):
    """Atomic overwrite. os.replace is Python 3 only; rename works on POSIX."""
    replace = getattr(os, 'replace', None)
    if replace is not None:
        replace(src, dst)
    else:                                            # pragma: no cover
        os.rename(src, dst)
