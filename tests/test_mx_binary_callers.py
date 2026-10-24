# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Tiny executable fixtures verify caller names only; these are not GPU gates."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MxBinaryCallerTests(unittest.TestCase):
    def test_direct_gpu_profile_uses_new_executable(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            root = Path(directory)
            (root / 'bench').mkdir()
            (root / 'scripts').mkdir()
            shutil.copy2(ROOT / 'scripts/wsclean_binary.py', root / 'scripts/wsclean_binary.py')
            script = root / 'bench/gpu_profile.sh'
            # Adapt only fixture output/tool paths; both binaries are tiny fakes.
            text = (ROOT / 'bench/gpu_profile.sh').read_text()
            text = text.replace('OUT=/tmp/gpubench', f'OUT="{root / "output"}"')
            text = text.replace('/usr/bin/time -l', '/usr/bin/time -p')
            script.write_text(text)
            build = root / 'build-mx-metal'
            build.mkdir()
            for name in ('wsclean-mx', 'wsclean'):
                binary = build / name
                binary.write_text('''#!/usr/bin/env python3
import os, sys
with open(os.environ['CALLER_LOG'], 'a') as output:
    output.write(sys.argv[0] + '\\n')
print('Inversion: CALLER FIXTURE')
print('maximum resident: CALLER FIXTURE (no measurement)')
''')
                binary.chmod(0o755)
            python = root / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            calls = root / 'calls'
            result = subprocess.run(['bash', str(script), '1'], text=True, capture_output=True,
                                    env=dict(os.environ, CALLER_LOG=str(calls)))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual([Path(x).name for x in calls.read_text().splitlines()], ['wsclean-mx'] * 2)

    def test_mx_build_script_reports_new_executable(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            shutil.copy2(ROOT / 'scripts/build_mx.sh', scripts / 'build_mx.sh')
            shutil.copy2(ROOT / 'scripts/wsclean_binary.py', scripts / 'wsclean_binary.py')
            (scripts / 'env.sh').write_text('CMAKE="$ROOT/fixture-cmake"\n')
            for script in ('mx_tree.sh', 'configure_wsclean.sh', 'check_headers.sh'):
                stub = scripts / script
                stub.write_text('#!/bin/sh\nexit 0\n')
                stub.chmod(0o755)
            cmake = root / 'fixture-cmake'
            cmake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ROOT/build-command"\n')
            cmake.chmod(0o755)
            build = root / 'build-mx'
            build.mkdir()
            for name, text in (('wsclean-mx', 'wsclean-mx version CALLER FIXTURE'),
                               ('wsclean', 'STALE LEGACY BINARY')):
                binary = build / name
                binary.write_text('#!/bin/sh\necho "' + text + '"\n')
                binary.chmod(0o755)
            result = subprocess.run(['bash', str(scripts / 'build_mx.sh')],
                                    env=dict(os.environ, ROOT=str(root)), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('wsclean-mx version CALLER FIXTURE', result.stdout)
            self.assertNotIn('STALE LEGACY BINARY', result.stdout)

    def test_gpu_checks_inspect_only_new_mx_executable(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            build = Path(directory)
            (build / 'compile_commands.json').write_text(json.dumps([
                {'file': '/fixture/main/main.cpp', 'command': 'c++ -DWSCLEAN_MX_METAL=1'}]))
            binary = build / 'wsclean-mx'
            binary.write_text('''#!/usr/bin/env python3
import os, sys
if '-mgpu' in sys.argv and os.environ.get('MX_METAL_ENGINE'):
    print('MX_METAL_ENGINE is retired')
    sys.exit(1)
print('wsclean-mx version CALLER FIXTURE')
''')
            binary.chmod(0o755)
            stale = build / 'wsclean'
            stale.write_text('#!/bin/sh\necho stale binary selected >&2\nexit 88\n')
            stale.chmod(0o755)
            nm = build / 'nm'
            nm.write_text('''#!/usr/bin/env python3
from pathlib import Path
import sys
binary = Path(sys.argv[-1])
if binary.name != 'wsclean-mx' or not binary.is_file():
    sys.exit('expected existing wsclean-mx; got ' + str(binary))
print('_mx_peak_find _mx_convolve_c2r _mx_convolve_many _mx_predict_register _mx_prediction_create')
''')
            nm.chmod(0o755)
            env = dict(os.environ, PATH=str(build) + os.pathsep + os.environ['PATH'])
            for script in ('gpu_activation_check.py', 'gpu_quarantine_check.py'):
                with self.subTest(script=script):
                    result = subprocess.run([sys.executable, str(ROOT / 'tests' / script), str(build)],
                                            env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            binary.unlink()
            for script in ('gpu_activation_check.py', 'gpu_quarantine_check.py'):
                with self.subTest(script=script, missing=True):
                    result = subprocess.run([sys.executable, str(ROOT / 'tests' / script), str(build)],
                                            env=env, text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('wsclean-mx', result.stderr)


if __name__ == '__main__':
    unittest.main()
