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

    def test_load_metrics_matches_direct_measurement(self):
        image = synthetic_image()
        directory = self.write(self.root / 'load', image)
        loaded = compare_sources.load_metrics(directory / self.product)
        direct = compare_sources.metrics(image.astype(np.float64))
        for key in compare_sources.PRODUCT_METRICS:
            self.assertEqual(loaded[key], direct[key])
        np.testing.assert_array_equal(loaded['_sources'], direct['_sources'])

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

    def test_reference_member_passes_with_decreasing_flux(self):
        # A member of the reference family must fit its own max envelope,
        # irrespective of whether its flux is the higher or lower endpoint.
        image = synthetic_image()
        high = self.write(self.root / 'high', image)
        low = self.write(self.root / 'low', image * np.float32(0.9))
        result = self.cli(high, high, low)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_envelope_is_independent_of_reference_order(self):
        image = synthetic_image()
        high = self.write(self.root / 'high', image)
        low = self.write(self.root / 'low', image * np.float32(0.9))
        for candidate in (high, low):
            for refs in ((high, low), (low, high)):
                with self.subTest(candidate=candidate.name, order=[p.name for p in refs]):
                    result = self.cli(candidate, *refs)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_distance_is_bidirectional(self):
        a = np.array([[0., 0., 100.], [0., 2., 80.]])
        b = np.array([[0., 0., 90.]])
        forward = compare_sources.compare_sources(a, b)
        backward = compare_sources.compare_sources(b, a)
        ab = compare_sources.source_distance(a, b)
        ba = compare_sources.source_distance(b, a)
        for key in ('flux_ratio_spread', 'position_offset_max_px'):
            self.assertEqual(ab[key], ba[key])
            self.assertEqual(ab[key], max(forward[key], backward[key]))
        self.assertEqual(ab['unmatched'] + ab['unmatched_candidate'],
                         ba['unmatched'] + ba['unmatched_candidate'])

    def test_candidate_outside_reference_envelope_fails(self):
        image = synthetic_image()
        first = self.write(self.root / 'r1', image)
        second = self.write(self.root / 'r2', image * np.float32(1.002))
        candidate = self.write(self.root / 'cand', image * np.float32(0.98))
        result = self.cli(candidate, first, second)
        self.assertEqual(result.returncode, 1)

    def test_envelope_reports_median_and_max_of_pairwise_deviations(self):
        image = synthetic_image()
        # Pairwise deviations are 2e-3, 4e-3 and 2e-3: max 4e-3, median 2e-3.
        self.write(self.root / 'r1', image)
        self.write(self.root / 'r2', image * np.float32(1.002))
        self.write(self.root / 'r3', image * np.float32(1.004))
        candidate = self.write(self.root / 'cand', image.copy())
        report = self.root / 'report.json'
        result = subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate), str(self.root / 'r1'), str(self.root / 'r2'),
             str(self.root / 'r3'), '--json', str(report)],
            text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        checks = json.loads(report.read_text())[self.product]['checks']
        envelope = checks['total_flux']['envelope']
        median = checks['total_flux']['envelope_median']
        self.assertAlmostEqual(envelope, 4e-3, delta=3e-4)
        self.assertAlmostEqual(median, 2e-3, delta=3e-4)
        self.assertLessEqual(median, envelope)

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
        # Either branch proves the point: a source that cannot be matched is a
        # failure whether or not other sources did match.
        self.assertTrue('unmatched source' in result.stdout or 'none matched' in result.stdout,
                        result.stdout)
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
        self.assertEqual((round(y), round(x)), (20, 41))
        self.assertGreater(value, 50.0)

    def test_source_position_is_sub_pixel(self):
        # A peak centred between pixels must be reported between pixels, not
        # snapped to whichever neighbour happens to hold the largest sample.
        image = synthetic_image(peak_xy=(20.5, 41.5), noise_sigma=1.0)
        sources = compare_sources.detect_sources(image, compare_sources.mad_rms(image))
        y, x, _ = sources[0]
        self.assertAlmostEqual(y, 20.5, delta=0.15)
        self.assertAlmostEqual(x, 41.5, delta=0.15)

    def test_components_below_the_peak_fraction_are_ignored(self):
        image = synthetic_image(noise_sigma=0.01)
        yy, xx = np.mgrid[0:64, 0:64]
        image += 5.0 * np.exp(-(((yy - 50) ** 2 + (xx - 12) ** 2) / 8.0))
        image += 0.5 * np.exp(-(((yy - 15) ** 2 + (xx - 15) ** 2) / 8.0))
        sources = compare_sources.detect_sources(image, compare_sources.mad_rms(image))
        positions = [(round(y), round(x)) for y, x, _ in sources]
        self.assertIn((50, 12), positions)
        self.assertNotIn((15, 15), positions)

    def test_jsonable_strips_internal_arrays(self):
        report = {'product': {'_sources': np.zeros((2, 3)), 'total_flux': np.float32(3.0)}}
        stripped = compare_sources.jsonable(report)
        self.assertNotIn('_sources', stripped['product'])
        self.assertEqual(stripped['product']['total_flux'], 3.0)
        json.dumps(stripped)  # must remain serialisable

    # --- criterion ----------------------------------------------------------

    def test_subnormal_only_images_are_not_flushed_or_crashed(self):
        # Subnormal-only data: the gate must neither flush it to zero (which
        # would make every threshold trivially pass) nor crash. The significance
        # floor is evaluated in double precision, so even a near-denormal peak
        # stays detectable. Stack-level peak semantics are inherited from
        # upstream; this pins the harness side of that contract.
        tiny = float(np.finfo(np.float32).tiny)
        for value in (np.float32(1e-40), np.float32(1e-44)):
            with self.subTest(value=value):
                image = np.zeros((8, 8), dtype=np.float32)
                image[3, 4] = value
                self.assertTrue(0.0 < float(image[3, 4]) < tiny)
                sources = compare_sources.detect_sources(image, compare_sources.mad_rms(image))
                self.assertEqual(len(sources), 1)
                self.assertEqual(float(sources[0][2]), float(value))

    def test_percentile_and_rank_helpers(self):
        self.assertEqual(compare_sources.percentile([1, 2, 3, 4, 5], 0.5), 3.0)
        self.assertEqual(compare_sources.percentile([], 0.95), 0.0)
        rank = compare_sources.candidate_percentile([1, 2, 3], 2.5)
        self.assertTrue(rank is not None and abs(rank - 2 / 3) < 1e-9)
        self.assertIsNone(compare_sources.candidate_percentile([], 1.0))

    def test_p95_criterion_is_stricter_than_the_max_envelope(self):
        # Four identical references and one wild member: the family's own 95th
        # percentile sits below the worst pairwise deviation, so a candidate
        # between the two must pass under `max` and fail under `p95`.
        image = synthetic_image()
        for index, scale in enumerate((1.0, 1.0, 1.0, 1.0, 1.1)):
            self.write(self.root / f'r{index}', image * np.float32(scale))
        candidate = self.write(self.root / 'cand', image * np.float32(1.08))
        references = [str(self.root / f'r{index}') for index in range(5)]
        under_max = subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate), *references],
            text=True, capture_output=True, check=False)
        under_p95 = subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate), *references, '--criterion', 'p95'],
            text=True, capture_output=True, check=False)
        self.assertEqual(under_max.returncode, 0, under_max.stdout)
        self.assertEqual(under_p95.returncode, 1)
        self.assertIn('total_flux', under_p95.stdout)
        self.assertIn('p95 family', under_p95.stdout)

    def test_p95_criterion_accepts_a_typical_member(self):
        image = synthetic_image()
        for index, scale in enumerate((1.0, 1.001, 1.002, 1.003, 1.004)):
            self.write(self.root / f'r{index}', image * np.float32(scale))
        candidate = self.write(self.root / 'cand', image * np.float32(1.0015))
        result = subprocess.run(
            [sys.executable, str(Path(compare_sources.__file__).resolve()),
             '--candidate', str(candidate),
             *[str(self.root / f'r{index}') for index in range(5)], '--criterion', 'p95'],
            text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
