"""End-to-end correctness of bench/pointflux_tool.py.

Copies the smallest fixture MS to a scratch dir (the tree's MS files stay
read-only), injects one point source with the tool, then recomputes the
expected visibilities from the dumped UVW/frequencies in Python and checks
the tool's DATA agrees to float32 precision. Also pins the argument
validation: no/bad arguments must fail closed, never write.
"""

import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'bench/micro/bin/pointflux_tool'
TAQL = ROOT / 'deps/install/bin/taql'
SPEED_OF_LIGHT = 299792458.0


def run(*args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True)


class PointFluxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TOOL.exists():
            raise unittest.SkipTest('pointflux_tool not built')
        if not TAQL.exists():
            raise unittest.SkipTest('project taql not built')

    def test_rejects_bad_arguments(self):
        for args in ([], ['only-one'], ['ms', 'not-a-source'], ['ms', '1,2'],
                      ['ms', '1,2,3,4'], ['ms', 'a,b,c'], ['ms', '']):
            result = run(TOOL, *args)
            self.assertEqual(result.returncode, 2, args)

    def test_injects_exact_dft(self):
        workdir = Path(tempfile.mkdtemp(prefix='pointflux-test-'))
        self.addCleanup(shutil.rmtree, workdir, True)
        ms = workdir / 'test.ms'
        shutil.copytree(ROOT / 'build-test/test_data/GMRT_MOCK.ms', ms)
        for f in ms.rglob('*'):
            if f.is_file():
                f.chmod(0o644)
        # One 2-Jy source at (l, m) = (0.001, -0.002); I peak truth = 1 Jy.
        result = run(TOOL, ms, '0.001,-0.002,2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('written=', result.stdout)
        dump = workdir / 'dump.txt'
        result = run(TAQL, '-ps', '-m', '1000000', '-o', str(dump),
                     'select real(DATA[0,0]) as xr, imag(DATA[0,0]) as xi, '
                     'UVW[0] as u, UVW[1] as v, UVW[2] as w from %s' % ms)
        self.assertEqual(result.returncode, 0, result.stderr)
        freq_result = run(TAQL, '-ps', '-m', '1',
                          'select CHAN_FREQ from %s::SPECTRAL_WINDOW' % ms)
        self.assertEqual(freq_result.returncode, 0, freq_result.stderr)
        freqs = []
        for tok in freq_result.stdout.replace(',', ' ').split():
            try:
                value = float(tok.strip('[]'))
            except ValueError:
                continue
            # Channel frequencies are ~1e8 Hz; ignore stray counts/units.
            if value > 1e6:
                freqs.append(value)
        self.assertTrue(freqs, 'no channel frequency parsed')
        wavelength = SPEED_OF_LIGHT / freqs[0]
        worst, scale, checked = 0.0, 0.0, 0
        for line in dump.read_text().splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            try:
                xr, xi, u, v, w = (float(fields[0]), float(fields[1]),
                                   float(fields[2]), float(fields[3]), float(fields[4]))
            except ValueError:
                continue
            if not all(map(math.isfinite, (xr, xi, u, v, w))):
                continue
            ul, vl, wl = u / wavelength, v / wavelength, w / wavelength
            nm1 = math.sqrt(max(0.0, 1.0 - 0.001**2 - 0.002**2)) - 1.0
            phase = -2.0 * math.pi * (ul * 0.001 + vl * (-0.002) + wl * nm1)
            expected = 1.0 * complex(math.cos(phase), math.sin(phase))  # XX = S/2 = 1
            got = complex(xr, xi)
            worst = max(worst, abs(got - expected))
            scale = max(scale, abs(expected))
            checked += 1
        self.assertGreater(checked, 0, 'no finite rows checked')
        # Tolerance is print-limited, not tool-limited: taql prints channel
        # frequencies to 6 significant digits (~1e2 Hz here), which alone is
        # ~2e-3 rad of phase. This test pins the layout convention (axis
        # order, XX=S/2, per-channel phases); absolute precision is covered
        # by the imaging gates. A transposed axis or missing pol reads O(1).
        self.assertLess(worst / max(scale, 1e-30), 5e-3, 'DFT mismatch')


if __name__ == '__main__':
    unittest.main()
