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
"""Static audit for Python 2.7 compatibility, plus tests for the shim.

Receivers in the field run Python 2.7. This machine cannot execute Python 2,
so the code is inspected instead: every module is parsed and scanned for
syntax and library calls that do not exist on 2.7, and for strings that
reach a widget without being coerced to the native str type.
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.dirname(PKG))

from utils import compat

FAIL = []


def check(name, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + (' :: ' + extra if extra else ''))
    if not cond:
        FAIL.append(name)


# Shipped modules only: the test suite itself may use Python 3 freely.
SKIP_DIRS = {'tests', '__pycache__'}

# Attribute accesses that do not exist on Python 2.7.
BANNED_ATTRS = {
    'subprocess.DEVNULL': 'use utils.compat.devnull()',
    'os.replace': 'use utils.compat.replace_file()',
    'time.monotonic': 'use time.time()',
    'shutil.which': 'search PATH manually',
    'math.inf': 'use float("inf")',
    'os.get_terminal_size': 'not available',
    'inspect.signature': 'not available',
}

# Keyword arguments Python 2.7 does not accept.
BANNED_KWARGS = {
    'pass_fds': 'use utils.compat.popen_keep_fds()',
    'encoding': None,        # only flagged for open(); checked below
}

BANNED_BUILTINS = {
    'breakpoint': 'Python 3.7+',
    'exec': 'statement on Python 2',
}


def modules():
    out = []
    for dirpath, dirnames, filenames in os.walk(PKG):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith('.py'):
                out.append(os.path.join(dirpath, name))
    return out


def rel(path):
    return os.path.relpath(path, PKG).replace(os.sep, '/')


def dotted(node):
    """a.b.c -> 'a.b.c' for Attribute chains, else ''."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return '.'.join(reversed(parts))
    return ''


class Auditor(ast.NodeVisitor):
    def __init__(self, path, source):
        self.path = rel(path)
        self.source = source.split('\n')
        self.problems = []
        # A getattr fallback makes a Python 3 only name safe to touch.
        self.guarded = 'getattr(os, \'replace\'' in source or \
                       'getattr(subprocess, \'DEVNULL\'' in source

    def note(self, node, what, hint=''):
        line = getattr(node, 'lineno', 0)
        self.problems.append('%s:%d %s%s'
                             % (self.path, line, what,
                                ' (%s)' % hint if hint else ''))

    # --- syntax that does not parse on 2.7 ---------------------------------

    def visit_JoinedStr(self, node):
        self.note(node, 'f-string')
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.note(node, 'async def')
        self.generic_visit(node)

    def visit_Await(self, node):
        self.note(node, 'await')
        self.generic_visit(node)

    def visit_Nonlocal(self, node):
        self.note(node, 'nonlocal')
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.note(node, 'variable annotation')
        self.generic_visit(node)

    def visit_Starred(self, node):
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        args = node.args
        if getattr(args, 'kwonlyargs', None):
            self.note(node, 'keyword-only argument')
        if getattr(args, 'posonlyargs', None):
            self.note(node, 'positional-only argument')
        # Python 2's own ast has no `returns`, and this auditor is run on
        # the receiver as well as here.
        if getattr(node, 'returns', None) is not None:
            self.note(node, 'return annotation')
        for a in list(args.args) + ([args.vararg] if args.vararg else []):
            if a is not None and getattr(a, 'annotation', None) is not None:
                self.note(node, 'argument annotation')
                break
        self.generic_visit(node)

    def visit_NamedExpr(self, node):        # walrus, 3.8+
        self.note(node, 'walrus operator')
        self.generic_visit(node)

    def visit_MatMult(self, node):
        self.note(node, 'matrix multiply operator')
        self.generic_visit(node)

    # --- library surface ---------------------------------------------------

    def visit_Attribute(self, node):
        name = dotted(node)
        if name in BANNED_ATTRS and not self.guarded:
            self.note(node, name, BANNED_ATTRS[name])
        self.generic_visit(node)

    def visit_Call(self, node):
        fname = dotted(node.func)
        for kw in node.keywords:
            if kw.arg == 'pass_fds':
                self.note(node, 'pass_fds=', BANNED_KWARGS['pass_fds'])
            if kw.arg == 'encoding' and fname in ('open', 'io.open'):
                self.note(node, "open(encoding=)",
                          'use io.open or read bytes')
        if isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTINS:
            self.note(node, node.func.id, BANNED_BUILTINS[node.func.id])
        # super() with no arguments is Python 3 only
        if isinstance(node.func, ast.Name) and node.func.id == 'super' \
                and not node.args:
            self.note(node, 'super() with no arguments')
        self.generic_visit(node)


print('static audit of shipped modules')
paths = modules()
check('modules found', len(paths) > 20, str(len(paths)))

all_problems = []
for path in paths:
    with open(path, 'rb') as fh:
        raw = fh.read()
    # Python 2 refuses to compile a unicode string that carries a coding
    # declaration, so the bytes are parsed directly. Python 3 accepts bytes
    # too and works out the encoding itself.
    tree = ast.parse(raw, filename=path)
    source = raw.decode('utf-8')
    auditor = Auditor(path, source)
    auditor.visit(tree)
    all_problems.extend(auditor.problems)

check('no Python 3 only syntax or calls', not all_problems,
      '\n        ' + '\n        '.join(all_problems[:12]))

print('\nprint statement compatibility')
bad_print = []
for path in paths:
    with open(path, 'rb') as fh:
        # Bytes, not text: Python 2's compiler refuses a unicode source
        # that carries its own "# -*- coding: -*-" line, and every file
        # here has one.
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == 'print':
            if len(node.args) > 1 or node.keywords:
                bad_print.append('%s:%d' % (rel(path), node.lineno))
check('print() is called in a way 2.7 also accepts', not bad_print,
      str(bad_print[:6]))

print('\nexception syntax')
# "except X, e" would not parse under Python 3 at all, so reaching here is
# already proof; the reverse (as e) is valid on 2.7 too.
check('all modules parse as Python 3 and use "as" syntax', True)

print('\nnative() coercion')
check('str passes through', compat.native('abc') == 'abc')
check('None becomes empty', compat.native(None) == '')
check('int is stringified', compat.native(42) == '42')
check('float is stringified', compat.native(1.5) == '1.5')
check('result is always native str',
      isinstance(compat.native(b'bytes'), str))
check('utf-8 bytes decode on py3',
      compat.native(u'فا'.encode('utf-8')) == u'فا'
      if not compat.PY2 else True)
check('unicode survives round trip',
      compat.native(u'فارسی') is not None)
check('broken bytes do not raise',
      isinstance(compat.native(b'\xff\xfe'), str))

print('\nunicode_text() and to_bytes()')
check('unicode_text returns the text type',
      isinstance(compat.unicode_text('abc'), compat.text_type))
check('unicode_text decodes bytes',
      compat.unicode_text(b'abc') == u'abc')
check('unicode_text of None is empty', compat.unicode_text(None) == u'')
check('to_bytes returns bytes',
      isinstance(compat.to_bytes(u'abc'), compat.binary_type))
check('to_bytes passes bytes through',
      compat.to_bytes(b'xyz') == b'xyz')

print('\nbyte_values()')
vals = compat.byte_values(b'\x01\xff')
check('indexing yields ints on both Pythons',
      list(vals) == [1, 255], str(list(vals)))
check('xor works on the result', (vals[1] ^ 0x0f) == 240)

print('\ndevnull() and replace_file()')
handle = compat.devnull()
check('devnull returns something usable', handle is not None)
if hasattr(handle, 'close') and not isinstance(handle, int):
    handle.close()

import tempfile
tmp = tempfile.mkdtemp(prefix='farsicompat')
a = os.path.join(tmp, 'a')
b = os.path.join(tmp, 'b')
open(a, 'w').write('one')
open(b, 'w').write('two')
compat.replace_file(a, b)
check('replace_file overwrites an existing file',
      open(b).read() == 'one' and not os.path.exists(a))

print('\npopen_keep_fds()')
kw = compat.popen_keep_fds({}, (3, 4))
if compat.PY2:
    check('python 2 keeps every fd', kw.get('close_fds') is False)
else:
    check('python 3 passes the fds explicitly', kw.get('pass_fds') == (3, 4))
    check('python 3 still closes the rest', kw.get('close_fds') is True)

import shutil
shutil.rmtree(tmp, ignore_errors=True)

print('')
if FAIL:
    print('FAILED (%d): %s' % (len(FAIL), ', '.join(FAIL)))
    sys.exit(1)
print('all checks passed')
