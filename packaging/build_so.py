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
"""Compile the plugin to .so modules with Cython.

Stage 1 (Cython -> C) runs anywhere. Stage 2 (C -> .so) needs a compiler
that targets the receiver, so on a non-matching host it is skipped and the
generated C is left in place for a Linux/OE build box to finish.

Two files deliberately stay as plain Python:

  plugin.py    Enigma2's loader looks for this exact file and calls Plugins()
  engine.py    it is spawned as a script, and a .so cannot be executed;
               it becomes a small launcher around the compiled engine_impl
"""

import os
import shutil
import subprocess
import sys
import sysconfig

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, 'PIIP')
BUILD = os.path.join(ROOT, 'build')
RELEASE = os.path.join(ROOT, 'release', 'PIIP')

# Never compiled: shipped verbatim.
KEEP_PY = {'plugin.py'}
KEEP_DIRS = {'tests'}                      # not shipped in a release build
VERBATIM = {'icon.png', 'LICENSE', 'README.md'}

ENGINE_LAUNCHER = '''# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Telegram : https://t.me/routekernel1
# YouTube  : https://youtube.com/@routekernel
# Project  : https://github.com/dreamboxone/piip
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
#
"""Launcher for the compiled translation engine.

A .so cannot be handed to the interpreter as a script, so this stub is what
gets spawned; the engine itself lives in engine_impl.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from translate.engine_impl import main

if __name__ == '__main__':
    sys.exit(main(sys.argv))
'''


def log(*parts):
    print(' '.join(str(p) for p in parts))


def sources(root):
    """-> [(abs path, package-relative path)] for everything to be shipped."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ('__pycache__', '.git') and
                             d not in KEEP_DIRS)
        for name in sorted(filenames):
            if name.endswith(('.pyc', '.pyo')) or name == 'engine_test.log':
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            out.append((full, rel))
    return out


def module_name(rel):
    """providers/m3u.py -> providers.m3u"""
    return rel[:-3].replace('/', '.')


def prepare(clean=True):
    """Lay out a build tree of .pyx files ready for Cython."""
    if clean and os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    if not os.path.isdir(BUILD):
        os.makedirs(BUILD)

    plan = []                       # (pyx path, module name, output .so rel)
    copies = []                     # (source, dest rel) shipped as-is

    for full, rel in sources(SOURCE):
        name = os.path.basename(rel)
        dest_dir = os.path.join(BUILD, os.path.dirname(rel))
        if dest_dir and not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)

        if name in VERBATIM or not name.endswith('.py'):
            copies.append((full, rel))
            continue
        if name in KEEP_PY or name == '__init__.py':
            copies.append((full, rel))
            continue

        if rel == 'translate/engine.py':
            # The implementation is compiled; a launcher takes its place.
            target_rel = 'translate/engine_impl.pyx'
            mod = 'translate.engine_impl'
            so_rel = 'translate/engine_impl.so'
        else:
            target_rel = rel[:-3] + '.pyx'
            mod = module_name(rel)
            so_rel = rel[:-3] + '.so'

        shutil.copy2(full, os.path.join(BUILD, target_rel))
        plan.append((target_rel, mod, so_rel))

    return plan, copies


def cythonize(plan, language_level=3):
    """Stage 1: .pyx -> .c. Returns the list of generated C files."""
    try:
        from Cython.Compiler import Options
        from Cython.Compiler.Main import compile as cy_compile
        from Cython.Compiler.Options import get_directive_defaults
    except ImportError:
        raise SystemExit(
            'Cython is not installed. Install it with:\n'
            '    pip install cython')

    directives = get_directive_defaults()
    directives['language_level'] = language_level
    # Cython on its own leaks a great deal: docstrings, qualified names and,
    # once compiled with debug info, every local variable name. These three
    # settings plus -g0/-s below close the obvious holes.
    # docstrings is a global option, not a compiler directive: setting it
    # in the directive dict silently does nothing.
    Options.docstrings = False
    directives['embedsignature'] = False
    directives['emit_code_comments'] = False
    directives['binding'] = False

    generated = []
    for pyx_rel, mod, _so_rel in plan:
        pyx = os.path.join(BUILD, pyx_rel)
        result = cy_compile(pyx, full_module_name=mod,
                            compiler_directives=directives)
        if result.num_errors:
            raise SystemExit('Cython failed on %s' % pyx_rel)
        c_file = pyx[:-4] + '.c'
        if not os.path.exists(c_file):
            raise SystemExit('no C output for %s' % pyx_rel)
        generated.append((c_file, mod, _so_rel))
    return generated


def compiler_settings(cc=None, python_include=None):
    return {
        'cc': cc or os.environ.get('CC') or 'gcc',
        'include': python_include or os.environ.get('PYTHON_INCLUDE')
                   or sysconfig.get_paths().get('include', ''),
        # -g0 keeps DWARF out of the binary: with it, every Python local
        # variable name is recoverable from the .so.
        'cflags': os.environ.get('CFLAGS',
                                 '-O2 -fPIC -w -g0 -fvisibility=hidden'),
        # -s strips the symbol table, which otherwise names every function.
        'ldflags': os.environ.get('LDFLAGS', '-shared -s'),
    }


def can_compile(settings):
    try:
        subprocess.check_output([settings['cc'], '--version'],
                                stderr=subprocess.STDOUT)
        return True
    except Exception:
        return False


def compile_all(generated, settings):
    """Stage 2: .c -> .so. Only valid when CC targets the receiver."""
    built = []
    for c_file, mod, so_rel in generated:
        out = os.path.join(BUILD, so_rel)
        outdir = os.path.dirname(out)
        if outdir and not os.path.isdir(outdir):
            os.makedirs(outdir)
        cmd = ([settings['cc']] + settings['cflags'].split() +
               ['-I' + settings['include'], c_file] +
               settings['ldflags'].split() + ['-o', out])
        log('  cc', so_rel)
        subprocess.check_call(cmd)
        built.append(so_rel)
    return built


def assemble(plan, copies, built):
    """Lay out the release tree: .so modules plus the verbatim files."""
    if os.path.isdir(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(RELEASE)

    for _src, rel in copies:
        dest = os.path.join(RELEASE, rel)
        d = os.path.dirname(dest)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        shutil.copy2(os.path.join(BUILD, rel), dest)

    for so_rel in built:
        dest = os.path.join(RELEASE, so_rel)
        d = os.path.dirname(dest)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        shutil.copy2(os.path.join(BUILD, so_rel), dest)

    launcher = os.path.join(RELEASE, 'translate', 'engine.py')
    d = os.path.dirname(launcher)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(launcher, 'w') as fh:
        fh.write(ENGINE_LAUNCHER)
    return RELEASE


def main(argv):
    settings = compiler_settings()
    log('source :', SOURCE)
    log('build  :', BUILD)
    log('cc     :', settings['cc'])
    log('headers:', settings['include'] or '(none found)')
    log('')

    log('stage 0: laying out the build tree')
    plan, copies = prepare()
    log('  %d modules to compile, %d files shipped verbatim'
        % (len(plan), len(copies)))

    log('stage 1: Cython -> C')
    generated = cythonize(plan)
    total_c = sum(os.path.getsize(c) for c, _, _ in generated)
    log('  %d C files, %.1f MB' % (len(generated), total_c / 1048576.0))

    if '--c-only' in argv:
        log('\nstopping after stage 1 as asked')
        return 0

    if not can_compile(settings):
        log('')
        log('stage 2: SKIPPED — no working compiler at %r' % settings['cc'])
        log('')
        log('The generated C is in %s' % BUILD)
        log('Finish the build on a machine whose toolchain targets the')
        log('receiver, for example:')
        log('')
        log('    CC=aarch64-oe-linux-gcc \\')
        log('    PYTHON_INCLUDE=/path/to/target/include/python3.11 \\')
        log('    python packaging/build_so.py')
        log('')
        return 2

    log('stage 2: C -> .so')
    built = compile_all(generated, settings)
    log('stage 3: assembling the release tree')
    out = assemble(plan, copies, built)
    log('  %s' % out)
    log('')
    log('done: %d compiled modules' % len(built))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
