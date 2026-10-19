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

    def test_kernel_extraction_script_stays_wired(self):
        script = ROOT / 'scripts/metal_kernel_coeffs.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111, 'must be executable')
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = script.read_text()
        # wsclean's default -wgridder-accuracy; the row it selects is documented
        # in docs/metal-plan.md and must stay the default here too.
        self.assertIn('EPSILON=1e-4', text)
        self.assertIn('ducc0_kernel_tool.cpp', text)
        for source in ('gridding_kernel.cc', 'gl_integrator.cc', 'threading.cc',
                       'string_utils.cc', 'mav.cc'):
            self.assertIn(source, text, f'{source} must be linked into the extractor')

    def test_probe_reads_row_parameters_from_the_coefficient_file(self):
        source = self.read('work/wsclean/metal/probe_main.cpp')
        # Hard-coding beta/e0 while the coefficients come from a file previously
        # compared two different ducc0 kernels.
        self.assertIn('beta_norm', source)
        self.assertIn('loadKernelCoefficients', source)
        self.assertIn('--kernel-coeffs', source)
        shader = self.read('work/wsclean/metal/mxshaders.h')
        self.assertIn('poly_sample', shader)
        self.assertIn('grid_accumulate_poly_hoisted', shader)

    def test_probe_keeps_its_differential_assertions(self):
        source = self.read('work/wsclean/metal/probe_main.cpp')
        for anchor in ('referenceGrid', 'kTolerance', 'mismatched_zero', 'missed_significant'):
            self.assertIn(anchor, source)
        self.assertIn('status=', source, 'the probe must print a machine-readable verdict')
        shader = self.read('work/wsclean/metal/mxshaders.h')
        # Centred rounding is the fix for the one-cell placement divergence.
        self.assertIn('const float fx = u - rounded_u;', shader)

    def test_roundtrip_mode_checks_the_adjoint_identity(self):
        source = self.read('work/wsclean/metal/probe_main.cpp')
        # The adjoint check is what catches a gridding/degridding mismatch that
        # both directions' twins would miss, so it must not be droppable.
        self.assertIn('roundtrip', source)
        self.assertIn('adjoint', source)
        shader = self.read('work/wsclean/metal/mxshaders.h')
        self.assertIn('grid_degrid_poly', shader)

    def test_cpu_baseline_script_stays_wired(self):
        script = ROOT / 'scripts/metal_cpu_baseline.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111, 'must be executable')
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = script.read_text()
        for anchor in ('ducc0_wgridder_tool.cpp', '-march=native', 'libomp',
                       'cpu-ducc0-baseline.txt'):
            self.assertIn(anchor, text)
        for source in ('gridding_kernel.cc', 'gl_integrator.cc', 'threading.cc',
                       'string_utils.cc', 'mav.cc'):
            self.assertIn(source, text, f'{source} must be linked into the baseline')
        # The parameters that took debugging to find must not drift back.
        tool = self.read('bench/metal/ducc0_wgridder_tool.cpp')
        self.assertIn('ms2dirty_bda', tool, 'wsclean uses the BDA entry point, not ms2dirty')
        self.assertIn('dirty2ms_bda', tool)
        self.assertIn('kSigmaMin = 1.1', tool)
        self.assertIn('kSigmaMax = 2.0', tool, 'the uv extent here explodes the w-plane count')
        self.assertIn('pixel_size = 1.0 / (lambda_per_cell * static_cast<double>(nu))', tool)

    def test_realdata_mode_stays_wired(self):
        # The real-uv-coverage measurement changed the headline number, so the
        # path that produces it must not rot: probe op, loader, and the shared
        # flags on both tools.
        probe = self.read('work/wsclean/metal/probe_main.cpp')
        for anchor in ('realdata', '--uvw-file', '--freq', '--lambda-per-cell',
                       'LoadUvwFile'):
            self.assertIn(anchor, probe)
        loader = self.read('work/wsclean/metal/uvw_file.h')
        for anchor in ('flagged', 'nonfinite', 'kSpeedOfLight', 'RealVisibility'):
            self.assertIn(anchor, loader)
        cpu = self.read('bench/metal/ducc0_wgridder_tool.cpp')
        for anchor in ('--uvw-file', '--freq', '--lambda-per-cell', 'uvw_file.h',
                       'distinct_footprint_origins', 'lambda_per_cell'):
            self.assertIn(anchor, cpu)
        # A wrong pixel size or scaling collapses the data into one cell; the
        # coverage guard is what catches that, so it must stay printed.
        self.assertIn('origins.size()', cpu)


if __name__ == '__main__':
    unittest.main()
