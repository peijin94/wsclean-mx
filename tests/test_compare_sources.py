# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Regressions for the source-level science gate (bench/compare_sources.py).

The gate's contract: a candidate is judged against the reference's own rerun
envelope, with a predeclared float32 floor, and the process exits non-zero on
any exceeded metric - including sources that are detectable but never match.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from astropy.io import fits

from bench import compare_sources


def synthetic_image(peak_xy=(32, 32), peak_amplitude=100.0, noise_sigma=1.0, seed=7,
                    shape=(64, 64)):
    rng = np.random.default_rng(seed)
    image = rng.normal(0.0, noise_sigma, shape)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    sigma = 2.0
    image += peak_amplitude * np.exp(
        -(((yy - peak_xy[0]) ** 2 + (xx - peak_xy[1]) ** 2) / (2.0 * sigma ** 2)))
    return image.astype(np.float32)


class CompareSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.product = 'img-dirty.fits'

    def write(self, directory, image, name=None):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (name or self.product)
        fits.writeto(path, image, overwrite=True)
        return directory

    def cli(self, candidate, *references):
        return subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate), *[str(r) for r in references]],
            text=True, capture_output=True, check=False)

    # --- scalar metrics -----------------------------------------------------

    def test_identical_candidate_passes(self):
        reference = self.write(self.root / 'ref', synthetic_image())
        candidate = self.write(self.root / 'cand', synthetic_image())
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('GATE PASSED', result.stdout)

    def test_float32_rounding_is_below_the_floor(self):
        image = synthetic_image()
        reference = self.write(self.root / 'ref', image)
        candidate = self.write(self.root / 'cand', image * np.float32(1.0 + 1e-6))
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_visible_flux_change_fails(self):
        image = synthetic_image()
        reference = self.write(self.root / 'ref', image)
        candidate = self.write(self.root / 'cand', image * np.float32(1.003))
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 1)
        self.assertIn('total_flux', result.stdout)
        self.assertIn('GATE FAILED', result.stdout)

    def test_candidate_inside_reference_envelope_passes(self):
        image = synthetic_image()
        first = self.write(self.root / 'r1', image)
        second = self.write(self.root / 'r2', image * np.float32(1.002))
        candidate = self.write(self.root / 'cand', image * np.float32(1.0005))
        result = self.cli(candidate, first, second)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_candidate_outside_reference_envelope_fails(self):
        image = synthetic_image()
        first = self.write(self.root / 'r1', image)
        second = self.write(self.root / 'r2', image * np.float32(1.002))
        candidate = self.write(self.root / 'cand', image * np.float32(0.98))
        result = self.cli(candidate, first, second)
        self.assertEqual(result.returncode, 1)

    def test_non_finite_pixels_are_refused(self):
        image = synthetic_image()
        reference = self.write(self.root / 'ref', image)
        broken = image.copy()
        broken[3, 4] = np.nan
        candidate = self.write(self.root / 'cand', broken)
        result = self.cli(candidate, reference)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-finite', result.stdout + result.stderr)

    def test_no_common_products_is_an_error(self):
        reference = self.write(self.root / 'ref', synthetic_image())
        candidate = self.write(self.root / 'cand', synthetic_image(), name='other.fits')
        result = self.cli(candidate, reference)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no common product names', result.stdout + result.stderr)

    # --- source matching ----------------------------------------------------

    def test_shifted_source_is_a_failure(self):
        reference = self.write(self.root / 'ref', synthetic_image())
        candidate = self.write(self.root / 'cand', synthetic_image(peak_xy=(33, 32)))
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 1)
        self.assertIn('source position', result.stdout)

    def test_displaced_source_is_reported_as_unmatched(self):
        # Same noise seed on both sides, so everything except the strong peak
        # matches exactly; the peak itself lands 5 px away, beyond the match
        # radius, and must be reported as unmatched rather than silently paired.
        reference = self.write(self.root / 'ref', synthetic_image())
        candidate = self.write(self.root / 'cand', synthetic_image(peak_xy=(32, 37)))
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 1)
        self.assertIn('unmatched source', result.stdout)
        self.assertIn('GATE FAILED', result.stdout)

    def test_unmatched_sources_are_reported_by_the_matcher(self):
        reference = np.array([[10.0, 10.0, 5.0]])
        matched = compare_sources.compare_sources(reference, np.array([[11.0, 10.0, 5.0]]))
        self.assertEqual((matched['matched'], matched['unmatched'],
                          matched['unmatched_candidate']), (1, 0, 0))
        unmatched = compare_sources.compare_sources(reference, np.array([[20.0, 20.0, 5.0]]))
        self.assertEqual((unmatched['matched'], unmatched['unmatched'],
                          unmatched['unmatched_candidate']), (0, 1, 1))

    def test_extra_candidate_source_fails_the_gate(self):
        # Both images share one source; the candidate has a second one that the
        # reference never detects, which is a difference even though matching
        # itself succeeded.
        reference = self.write(self.root / 'ref', synthetic_image(noise_sigma=1e-6))
        image = synthetic_image(noise_sigma=1e-6)
        yy, xx = np.mgrid[0:64, 0:64]
        image += 80.0 * np.exp(-(((yy - 50) ** 2 + (xx - 12) ** 2) / 8.0))
        candidate = self.write(self.root / 'cand', image.astype(np.float32))
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 1)
        self.assertIn('unmatched source', result.stdout)

    def test_pure_noise_has_no_source_failure(self):
        rng = np.random.default_rng(11)
        image = rng.normal(0.0, 1.0, (64, 64)).astype(np.float32)
        reference = self.write(self.root / 'ref', image)
        candidate = self.write(self.root / 'cand', image.copy())
        result = self.cli(candidate, reference)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('none detectable', result.stdout)

    # --- helpers ------------------------------------------------------------

    def test_detect_sources_finds_the_peak(self):
        image = synthetic_image(peak_xy=(20, 41))
        sources = compare_sources.detect_sources(image, compare_sources.mad_rms(image))
        self.assertGreaterEqual(len(sources), 1)
        y, x, value = sources[0]
        self.assertEqual((int(y), int(x)), (20, 41))
        self.assertGreater(value, 50.0)

    def test_jsonable_strips_internal_arrays(self):
        report = {'product': {'_sources': np.zeros((2, 3)), 'total_flux': np.float32(3.0)}}
        stripped = compare_sources.jsonable(report)
        self.assertNotIn('_sources', stripped['product'])
        self.assertEqual(stripped['product']['total_flux'], 3.0)
        json.dumps(stripped)  # must remain serialisable

    def test_json_output_omits_internal_arrays(self):
        image = synthetic_image()
        reference = self.write(self.root / 'ref', image)
        candidate = self.write(self.root / 'cand', image.copy())
        destination = self.root / 'report.json'
        result = subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate), str(reference), '--json', str(destination)],
            text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(destination.read_text())
        self.assertIn(self.product, report)
        self.assertTrue(all('_sources' not in value for value in report[self.product].values()
                            if isinstance(value, dict)))


if __name__ == '__main__':
    unittest.main()
