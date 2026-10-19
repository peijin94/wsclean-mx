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

    def test_wlayer_harness_stays_wired(self):
        # The w-layer bisection harness is what makes that work tractable; keep
        # it building and keep the fixes it found in place.
        script = ROOT / 'scripts/metal_wlayer_check.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111)
        self.assertEqual(subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode, 0)
        tool = self.read('bench/metal/wlayer_check.cpp')
        self.assertIn('metal/metalinversion.h', tool)
        self.assertIn('ms2dirty_bda', tool)
        impl = self.read('work/wsclean/metal/metalinversion.mm')
        # 1. kernel-weighted spread over planes, not hard assignment
        self.assertIn('plane_items', impl)
        self.assertIn('wWeight', impl)
        # 2. the whole-image nm1 scan (corners alone give nm1min == nm1max and
        #    a dw 50x too large), and no bogus FFT normalisation factor
        self.assertIn('Scan the WHOLE image', impl)
        self.assertNotIn('4.0 / (static_cast<double>(grid)', impl)
        # 3. ducc0's w-tap formula, and explicitly not PolynomialKernel::eval
        self.assertIn('z = (z_off - nth)*2 + (W-1)', impl)
        self.assertIn('nth piece of the same polynomial', impl)
        # the wired path must stay 2-D while the scale is open
        gridder = self.read('work/wsclean/wgridder/wgridder.h')
        self.assertIn('input.w_gridding = false;', gridder)

    def test_gpu_option_is_wired_and_gated(self):
        # -mgpu must exist, reach the w-gridder, and be gated: the backend only
        # runs when it does exactly the same maths as the ducc0 call it replaces.
        settings = self.read('work/wsclean/main/settings.h')
        self.assertIn('bool useGpu = false;', settings)
        cli = self.read('work/wsclean/main/commandline.cpp')
        self.assertIn('param == "mgpu"', cli)
        self.assertIn('settings.useGpu = true;', cli)
        gridder = self.read('work/wsclean/wgridder/wgridder.h')
        self.assertIn('mx::metal::inversion(input, tdirty.data())', gridder)
        self.assertIn('if constexpr (std::is_same<NumT, float>::value', gridder)
        self.assertIn('metal_done ? "used" : "refused, falling back to ducc0"', gridder)
        self.assertIn('input.w_gridding = false;', gridder)
        impl = self.read('work/wsclean/metal/metalinversion.mm')
        for anchor in ('inversionSupported', 'M_PI * w_max * lambda * lm_sq',
                       'w-term too large for a 2-D inversion', 'n_channels'):
            self.assertIn(anchor, impl, f'{anchor} is part of the 2-D gate')
        header = self.read('work/wsclean/metal/metalinversion.h')
        self.assertIn('bool inversion(const InversionInput& input, float* dirty);', header)

    def test_image_check_keeps_its_chain(self):
        # The image-level harness is the only place the Metal gridding meets
        # ducc0's actual gridding rather than a twin of itself, so its four
        # matched details must stay in place.
        script = ROOT / 'scripts/metal_image_check.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111)
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ducc0_image_check.cpp', script.read_text())
        tool = self.read('bench/metal/ducc0_image_check.cpp')
        for anchor in ('complex2hartley', 'hartley2_2D', 'corfunc', 'ms2dirty_bda',
                       'chooseKernel', 'rolled', 'vlim'):
            self.assertIn(anchor, tool, f'{anchor} is part of the reproduced chain')
        self.assertIn('kTolerance = 1.0e-3', tool)

    def test_split_dispatch_stays_wired(self):
        # The split is where the real-data win came from: one threadgroup per
        # bucket slice instead of per tile. Losing it silently would put the
        # gridder back at a third of its speed.
        shader = self.read('work/wsclean/metal/mxshaders.h')
        self.assertIn('grid_accumulate_poly_hoisted_split', shader)
        kernel = shader[shader.index('kernel void grid_accumulate_poly_hoisted_split'):]
        kernel = kernel[:kernel.index('// Pull model')]
        self.assertIn('work_items[3 * work_id.x + 0]', kernel)
        self.assertIn('work_items[3 * work_id.x + 1]', kernel)
        self.assertIn('work_items[3 * work_id.x + 2]', kernel)
        self.assertNotIn('bucket_start', kernel, 'the split kernel reads the work list')
        host = self.read('work/wsclean/metal/metaldevice.mm')
        self.assertIn('split_target', host)
        self.assertIn('work_items.push_back', host)
        self.assertIn('dispatchThreadgroups:MTLSizeMake(items, 1, 1)', host)
        self.assertIn('std::size_t split_target = 256;', self.read('work/wsclean/metal/metaldevice.h'))
        probe = self.read('work/wsclean/metal/probe_main.cpp')
        self.assertIn('--split', probe)
        self.assertIn('std::size_t split_target = 256;', probe)

    def test_every_poly_variant_is_compared_against_the_poly_reference(self):
        # A poly variant missing from this list is compared against the
        # NORMALISED analytic reference and reads as a ~4x error in an exact
        # kernel.
        probe = self.read('work/wsclean/metal/probe_main.cpp')
        block = probe[probe.index('const bool polynomial_reference'):]
        block = block[:block.index(';')]
        for variant in ('kPoly', 'kPolyHoisted', 'kPolyColumns'):
            self.assertIn(variant, block, f'{variant} must select the polynomial reference')
        # The pull kernel must keep its one-owner invariant: no atomics.
        shader = self.read('work/wsclean/metal/mxshaders.h')
        kernel = shader[shader.index('kernel void grid_accumulate_poly_columns'):]
        kernel = kernel[:kernel.index('// Degridding')]
        self.assertNotIn('atomic_add_float', kernel)
        self.assertIn('out[0] = acc.x', kernel)

    def test_dump_script_verifies_what_taql_silently_truncates(self):
        script = ROOT / 'scripts/dump_ms_uvw.sh'
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111, 'must be executable')
        result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = script.read_text()
        # -ps -m is the difference between 621 250 rows and 54; the project's own
        # casacore is the difference between a dump and a dyld error.
        self.assertIn('-ps -m', text)
        self.assertIn('deps/install/bin/taql', text)
        self.assertIn('refusing to overwrite', text)
        self.assertIn('incomplete dump', text)


if __name__ == '__main__':
    unittest.main()
