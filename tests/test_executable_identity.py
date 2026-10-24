# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Release identity integration gates; no imaging or Measurement Set access.

Set WSCLEAN_MX_IDENTITY_BUILD to a configured MX build to run native gates.
"""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('WSCLEAN_MX_IDENTITY_BUILD'), 'configured native build required')
class ExecutableIdentityTests(unittest.TestCase):
    def setUp(self):
        self.build = Path(os.environ['WSCLEAN_MX_IDENTITY_BUILD']).resolve()
        self.cmake = os.environ.get('IDENTITY_CMAKE', '/opt/homebrew/bin/cmake')

    def run_command(self, *command, env=None):
        result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(result.stdout, end='')
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def assert_loads_threading_runtime(self, binary, runtime):
        # Inspect dyld's actual loaded image, without inherited library overrides.
        env = {key: value for key, value in os.environ.items() if not key.startswith('DYLD_')}
        env['DYLD_PRINT_LIBRARIES'] = '1'
        output = self.run_command(str(binary), '-version', env=env)
        loaded = [line for line in output.splitlines() if 'libschaapthreading.dylib' in line]
        self.assertEqual(len(loaded), 1, output)
        self.assertTrue(loaded[0].endswith(' ' + str(runtime.resolve())), loaded[0])

    def test_primary_target_builds_and_installs_native_mx_executable(self):
        self.run_command(self.cmake, '--build', str(self.build), '--target', 'wsclean', '-j4')
        binary = self.build / 'wsclean-mx'
        self.assertTrue(binary.is_file() and os.access(binary, os.X_OK), str(binary))
        self.assertEqual(binary.read_bytes()[:4], b'\xcf\xfa\xed\xfe', 'expected native arm64 Mach-O, not an alias')
        self.assert_loads_threading_runtime(binary, self.build / 'libschaapthreading.dylib')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            prefix = Path(directory) / 'installed'
            self.run_command(self.cmake, '--install', str(self.build), '--prefix', str(prefix),
                             '--component', 'wsclean-mx')
            # Relocate the entire component before startup to test its own rpath.
            relocated = Path(directory) / 'relocated'
            prefix.rename(relocated)
            installed = relocated / 'bin/wsclean-mx'
            runtime = relocated / 'lib/libschaapthreading.dylib'
            self.assertTrue(installed.is_file() and os.access(installed, os.X_OK), str(installed))
            self.assertFalse((relocated / 'bin/wsclean').exists())
            self.assertFalse((relocated / 'bin/wsclean-mp').exists())
            self.assertTrue(runtime.is_file(), str(runtime))
            self.assert_loads_threading_runtime(installed, runtime)

    def test_cli_distinguishes_mx_release_from_upstream_version(self):
        self.run_command(self.cmake, '--build', str(self.build), '--target', 'wsclean', '-j4')
        binary = str(self.build / 'wsclean-mx')
        for arguments in (('-version',), ('-help',), ()):
            with self.subTest(arguments=arguments):
                output = self.run_command(binary, *arguments)
                self.assertRegex(output, r'(?m)^wsclean-mx version 0\.1\.1$')
                self.assertRegex(output, r'(?m)^WSClean version 3\.7 \(')
                if arguments != ('-version',):
                    self.assertIn('Syntax: wsclean-mx [options]', output)
                    self.assertIn('Print the wsclean-mx and upstream WSClean versions and exit.', output)


class PythonIntegrationConfigTests(unittest.TestCase):
    def test_configured_python_tests_invoke_renamed_executable(self):
        root = Path(__file__).resolve().parents[1]
        template = root / 'work/wsclean/tests/python/config_vars.py.in'
        cmake = os.environ.get('IDENTITY_CMAKE', '/opt/homebrew/bin/cmake')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            directory = Path(directory)
            script = directory / 'configure.cmake'
            output = directory / 'config_vars.py'
            script.write_text('set(CMAKE_BINARY_DIR "${OUTPUT_DIR}")\n'
                              'configure_file("${INPUT}" "${OUTPUT}" @ONLY)\n')
            subprocess.run([cmake, f'-DINPUT={template}', f'-DOUTPUT={output}',
                            f'-DOUTPUT_DIR={directory}', '-P', str(script)], check=True)
            assignments = {
                node.targets[0].id: ast.literal_eval(node.value)
                for node in ast.parse(output.read_text()).body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            }
            self.assertEqual(Path(assignments['WSCLEAN']), directory / 'wsclean-mx')
            self.assertEqual(Path(assignments['WSCLEAN_MP']), directory / 'wsclean-mp')


if __name__ == '__main__':
    unittest.main()
