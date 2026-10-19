"""Guards for the Metal backend integration points.

These do not run the GPU: they assert that the pieces which make the backend
reachable stay wired up, so a later edit cannot silently drop the CMake option,
the probe hook in the regression suite, or the wrapper script's flag.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MetalIntegrationTest(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text()

    def test_wrapper_is_syntactically_valid_and_executable(self):
        script = ROOT / 'scripts/metal_build.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111, 'metal_build.sh must be executable')
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrapper_configures_with_the_metal_flag(self):
        text = self.read('scripts/metal_build.sh')
        self.assertIn('-DWSCLEAN_MX_METAL=ON', text)
        self.assertIn('--target mx-metal-probe', text)
        self.assertIn('for dep in aocommon schaapcommon radler', text)
        self.assertIn('FETCHCONTENT_SOURCE_DIR_${upper}=$ROOT/work/$dep', text,
                      'every patched dependency must keep pointing at the work tree')

    def test_cmake_option_defaults_to_off(self):
        text = self.read('work/wsclean/CMakeLists.txt')
        # The description contains parentheses, so match the whole statement.
        pattern = re.compile(r'option\(\s*WSCLEAN_MX_METAL\s+"[^"]*"\s+OFF\s*\)', re.S)
        self.assertIsNotNone(pattern.search(text),
                             'WSCLEAN_MX_METAL must exist and default to OFF')
        self.assertIn('add_subdirectory(metal)', text)

    def test_regression_suite_runs_or_skips_the_probe(self):
        text = self.read('scripts/test.sh')
        self.assertIn('$BUILD/metal/mx-metal-probe', text)
        self.assertIn('Metal probe absent', text,
                      'a build without the flag must say so rather than pass silently')

    def test_probe_keeps_its_differential_assertions(self):
        source = self.read('work/wsclean/metal/probe_main.cpp')
        for anchor in ('referenceGrid', 'kTolerance', 'mismatched_zero', 'missed_significant'):
            self.assertIn(anchor, source)
        self.assertIn('status=', source, 'the probe must print a machine-readable verdict')
        shader = self.read('work/wsclean/metal/mxshaders.h')
        # Centred rounding is the fix for the one-cell placement divergence.
        self.assertIn('const float fx = u - rounded_u;', shader)


if __name__ == '__main__':
    unittest.main()
