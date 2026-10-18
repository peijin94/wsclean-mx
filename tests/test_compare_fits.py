# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Correctness regressions using synthetic arrays and real tiny FITS files."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from astropy.io import fits

from bench import compare_fits


class CompareFitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ref = self.root / "ref"
        self.test = self.root / "test"
        self.ref.mkdir()
        self.test.mkdir()

    def pair(self, a, b):
        ref_path = self.ref / "image.fits"
        test_path = self.test / "image.fits"
        fits.writeto(ref_path, np.asarray(a), overwrite=True)
        fits.writeto(test_path, np.asarray(b), overwrite=True)
        return compare_fits.compare(ref_path, test_path)

    def passes(self, result, tier, **thresholds):
        args = dict(tier=tier, max_ulp=4, max_rel_rms=1e-4,
                    max_rel_peak=1e-3)
        args.update(thresholds)
        return compare_fits.passes(result, SimpleNamespace(**args))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(compare_fits.__file__).resolve()),
             str(self.ref), str(self.test), *args],
            text=True, capture_output=True, check=False)

    def test_zero_reference_nonzero_candidate_fails_t2(self):
        result = self.pair(np.zeros(2), np.array([0.0, 1.0]))
        self.assertFalse(self.passes(result, "T2"))
        self.assertEqual(result["rel_rms"], float("inf"))
        self.assertEqual(result["rel_peak"], float("inf"))

    def test_integer_unit_differences_survive_t2_and_cli(self):
        cases = (
            (np.int64, 2**53, np.int64, 2**53 + 1),
            (np.int64, -2**53, np.int64, -2**53 - 1),
            (np.uint64, 2**63, np.uint64, 2**63 + 1),
            (np.int64, 2**63 - 1, np.uint64, 2**63),
            (np.uint64, 2**63, np.int64, 2**63 - 1),
        )
        for ref_dtype, ref_value, test_dtype, test_value in cases:
            with self.subTest(ref_dtype=ref_dtype, ref_value=ref_value,
                              test_dtype=test_dtype, test_value=test_value):
                result = self.pair(
                    np.array([ref_value, 0], dtype=ref_dtype),
                    np.array([test_value, 0], dtype=test_dtype))
                self.assertNotIn("error", result)
                self.assertEqual(result["n_diff"], 1)
                self.assertEqual(result["max_abs"], 1.0)
                self.assertAlmostEqual(result["rel_rms"] * abs(ref_value), 1.0)
                self.assertAlmostEqual(result["rel_peak"] * abs(ref_value), 1.0)
                self.assertFalse(self.passes(result, "T2", max_rel_rms=0,
                                             max_rel_peak=0))
                cli = self.cli("--tier", "T2", "--max-rel-rms", "0",
                               "--max-rel-peak", "0")
                self.assertEqual(cli.returncode, 1, cli.stdout)
                self.assertIn("1.000e+00", cli.stdout)
                self.assertIn("FAIL", cli.stdout)
                self.assertEqual(cli.stderr, "")

    def test_high_range_mixed_integer_float_fails_closed(self):
        for dtype, value in (
            (np.int64, 2**53 + 1), (np.int64, -2**53 - 1),
            (np.uint64, 2**63 + 1), (np.uint64, 2**64 - 1),
            # Conservatively reject even exactly representable high integers.
            (np.int64, 2**53 + 2), (np.int64, -2**63),
        ):
            integer = np.array([value, 0], dtype=dtype)
            floating = np.array([float(value), 0], dtype=np.float64)
            for a, b in ((integer, floating), (floating, integer)):
                with self.subTest(dtype=dtype, value=value, ref_dtype=a.dtype):
                    result = self.pair(a, b)
                    self.assertIn("error", result)
                    self.assertIn("mixed integer/float", result["error"])
                    for tier in ("T0", "T1", "T2"):
                        self.assertFalse(self.passes(result, tier,
                                                     max_rel_rms=0,
                                                     max_rel_peak=0))
                    cli = self.cli("--tier", "T2", "--max-rel-rms", "0",
                                   "--max-rel-peak", "0")
                    self.assertEqual(cli.returncode, 1, cli.stdout)
                    self.assertIn("mixed integer/float", cli.stdout)
                    self.assertIn("FAIL", cli.stdout)
                    self.assertEqual(cli.stderr, "")

    def test_integer_extremes_do_not_overflow_and_equal_values_pass(self):
        for ref_dtype, ref_value, test_dtype, test_value in (
            (np.int64, -2**63, np.int64, 2**63 - 1),
            (np.uint64, 0, np.uint64, 2**64 - 1),
            (np.uint64, 2**64 - 1, np.uint64, 0),
            (np.int64, -2**63, np.uint64, 2**64 - 1),
            (np.uint64, 2**64 - 1, np.int64, -2**63),
        ):
            with self.subTest(ref_value=ref_value, test_value=test_value):
                result = self.pair(np.array([ref_value], dtype=ref_dtype),
                                   np.array([test_value], dtype=test_dtype))
                delta = float(abs(test_value - ref_value))
                relative = delta / abs(ref_value) if ref_value else float("inf")
                self.assertEqual(result["n_diff"], 1)
                self.assertEqual(result["max_abs"], delta)
                self.assertEqual(result["rel_rms"], relative)
                self.assertEqual(result["rel_peak"], relative)
                self.assertFalse(self.passes(result, "T2", max_rel_rms=0,
                                             max_rel_peak=0))
        for dtype, values in ((np.int64, [-2**63, 0, 2**63 - 1]),
                              (np.uint64, [0, 2**63, 2**64 - 1])):
            a = np.array(values, dtype=dtype)
            result = self.pair(a, a)
            self.assertTrue(self.passes(result, "T0"))
            self.assertTrue(self.passes(result, "T2", max_rel_rms=0, max_rel_peak=0))
            self.assertEqual(result["n_diff"], 0)
            self.assertEqual(result["max_abs"], 0.0)
        result = self.pair(np.array([2**53 + 1], dtype=np.int64),
                           np.array([2**53 + 1], dtype=np.uint64))
        self.assertTrue(self.passes(result, "T2", max_rel_rms=0, max_rel_peak=0))
        self.assertEqual(result["n_diff"], 0)

    def test_integer_image_metrics_include_all_chunks(self):
        # Still a tiny FITS fixture (40 KiB of pixels per image).
        a = np.full((50, 100), 2**53, dtype=np.int64)
        b = a.copy()
        b.flat[[0, 4095, 4096, 4999]] += 1
        result = self.pair(a, b)
        self.assertEqual(result["n_diff"], 4)
        self.assertEqual(result["max_abs"], 1.0)
        self.assertAlmostEqual(result["rel_rms"] * 2**53, np.sqrt(4 / a.size))
        self.assertEqual(result["rel_peak"], 1 / 2**53)
        self.assertFalse(self.passes(result, "T2", max_rel_rms=0, max_rel_peak=0))

    def test_safe_mixed_integer_float_preserves_fractional_metrics(self):
        for dtype, values in ((np.int64, [-2**53, 0, 2**53]),
                              (np.uint64, [0, 1, 2**53])):
            integer = np.array(values, dtype=dtype)
            floating = integer.astype(np.float64)
            for a, b in ((integer, floating), (floating, integer)):
                result = self.pair(a, b)
                self.assertNotIn("error", result)
                self.assertTrue(self.passes(result, "T2", max_rel_rms=0,
                                            max_rel_peak=0))
                self.assertEqual(result["n_diff"], 0)
        for a, b, expected_rms, expected_peak, expected_ratio in (
            ([3, 4], [3.0, 4.5], 0.1, 0.125, 1.125),
            ([3.0, 4.5], [3, 4], 0.5 / np.hypot(3, 4.5), 0.5 / 4.5, 4 / 4.5),
        ):
            result = self.pair(a, b)
            self.assertEqual(result["n_diff"], 1)
            self.assertEqual(result["max_abs"], 0.5)
            self.assertAlmostEqual(result["rel_rms"], expected_rms)
            self.assertAlmostEqual(result["rel_peak"], expected_peak)
            self.assertAlmostEqual(result["peak_ratio"], expected_ratio)
            self.assertTrue(self.passes(result, "T2", max_rel_rms=0.2, max_rel_peak=0.2))

    def test_float64_ulp_across_sign_does_not_overflow(self):
        a = np.array([-np.finfo(np.float64).max])
        b = -a
        expected = 2 * 0x7FEFFFFFFFFFFFFF
        self.assertEqual(compare_fits.ulp_diff(a, b), expected)
        result = self.pair(a, b)
        self.assertEqual(result["max_ulp"], expected)
        self.assertFalse(self.passes(result, "T1", max_ulp=expected - 1))

    def test_big_endian_direct_ulp_is_one(self):
        a = np.array([1.0], dtype=">f8")
        b = np.array([np.nextafter(1.0, 2.0)], dtype=">f8")
        # Test the raw helper first: np.where in compare may normalize FITS data.
        self.assertEqual(compare_fits.ulp_diff(a, b), 1)
        self.assertEqual(self.pair(a, b)["max_ulp"], 1)

    def test_identical_bytes_with_incompatible_dtypes_fail_t0(self):
        # Both FITS arrays contain four zero bytes, with different meanings.
        result = self.pair(np.zeros(1, dtype=np.int32),
                           np.zeros(1, dtype=np.float32))
        self.assertFalse(self.passes(result, "T0"))
        self.assertFalse(result["bitwise"])

    def test_matching_infinities_fail_every_tier(self):
        result = self.pair([1.0, np.inf], [1.0, np.inf])
        for tier in ("T0", "T1", "T2"):
            self.assertFalse(self.passes(result, tier), tier)

    def test_all_nan_fails_every_tier(self):
        result = self.pair([np.nan, np.nan], [np.nan, np.nan])
        for tier in ("T0", "T1", "T2"):
            self.assertFalse(self.passes(result, tier), tier)

    def test_empty_arrays_fail_every_tier_cleanly(self):
        result = self.pair(np.array([], dtype=np.float32),
                           np.array([], dtype=np.float32))
        for tier in ("T0", "T1", "T2"):
            self.assertFalse(self.passes(result, tier), tier)
        cli = self.cli()
        self.assertEqual(cli.returncode, 1)
        self.assertNotIn("Traceback", cli.stderr)

    def test_malformed_input_fails_cli_cleanly(self):
        self.pair([1.0], [1.0])
        (self.test / "image.fits").write_bytes(b"not a FITS file")
        cli = self.cli()
        self.assertEqual(cli.returncode, 1)
        self.assertNotIn("Traceback", cli.stderr)
        self.assertIn("FAIL", cli.stdout)

    def test_cli_rejects_nonfinite_or_negative_thresholds(self):
        self.pair([1.0], [1.0])
        for option, value in (
            ("--max-rel-rms", "nan"), ("--max-rel-rms", "inf"),
            ("--max-rel-rms", "-inf"), ("--max-rel-rms", "-1"),
            ("--max-rel-peak", "nan"), ("--max-rel-peak", "inf"),
            ("--max-rel-peak", "-inf"), ("--max-rel-peak", "-1"),
            ("--max-ulp", "nan"), ("--max-ulp", "inf"),
            ("--max-ulp", "-inf"), ("--max-ulp", "-1"),
        ):
            cli = self.cli(f"{option}={value}")
            self.assertEqual(cli.returncode, 2, (option, value, cli.stdout))
            self.assertIn("error:", cli.stderr)
            self.assertNotIn("Traceback", cli.stderr)

    def test_primary_hdu_without_data_fails_cleanly(self):
        self.pair([1.0], [1.0])
        fits.PrimaryHDU().writeto(self.test / "image.fits", overwrite=True)
        cli = self.cli()
        self.assertEqual(cli.returncode, 1)
        self.assertNotIn("Traceback", cli.stderr)
        self.assertIn("FAIL", cli.stdout)

    def test_large_finite_identical_arrays_pass_t2(self):
        result = self.pair([1e200, -1e200], [1e200, -1e200])
        self.assertTrue(self.passes(result, "T2"))
        self.assertEqual(result["rel_rms"], 0.0)

    def test_large_finite_nearby_arrays_pass_t2(self):
        result = self.pair([1e200], [1e200 * (1 + 1e-6)])
        self.assertTrue(self.passes(result, "T2"))
        self.assertAlmostEqual(result["rel_rms"], 1e-6, places=12)

    def test_signed_zero_bits_differ_but_ulp_distance_is_zero(self):
        result = self.pair([0.0, -0.0], [-0.0, 0.0])
        self.assertFalse(self.passes(result, "T0"))
        self.assertTrue(self.passes(result, "T1", max_ulp=0))
        self.assertTrue(self.passes(result, "T2", max_rel_rms=0, max_rel_peak=0))
        for dtype in ("<f4", ">f4", "<f8", ">f8"):
            self.assertEqual(compare_fits.ulp_diff(
                np.array([-0.0], dtype=dtype), np.array([0.0], dtype=dtype)), 0)

    def test_matching_nan_masks_with_finite_coverage_pass(self):
        result = self.pair([np.nan, 1.0, -2.0], [np.nan, 1.0, -2.0])
        for tier in ("T0", "T1", "T2"):
            self.assertTrue(self.passes(result, tier), tier)
        changed = self.pair([np.nan, 1.0], [np.nan, np.nextafter(1.0, 2.0)])
        self.assertFalse(self.passes(changed, "T0"))
        self.assertTrue(self.passes(changed, "T1", max_ulp=1))
        self.assertTrue(self.passes(changed, "T2"))

    def test_nan_payloads_are_bitwise_data_for_t0(self):
        a = np.array([0x7FF8000000000001, 0x3FF0000000000000], dtype=np.uint64).view(np.float64)
        b = np.array([0x7FF8000000000002, 0x3FF0000000000000], dtype=np.uint64).view(np.float64)
        result = self.pair(a, b)
        self.assertFalse(self.passes(result, "T0"))
        self.assertTrue(self.passes(result, "T1", max_ulp=0))

    def test_nan_mask_mismatch_fails_every_tier(self):
        result = self.pair([1.0, np.nan, 2.0], [1.0, 2.0, np.nan])
        self.assertEqual(result["nan_mismatch"], 2)
        for tier in ("T0", "T1", "T2"):
            self.assertFalse(self.passes(result, tier), tier)

    def test_infinity_patterns_fail_every_tier_and_cli(self):
        for left, right in ((np.inf, -np.inf), (np.inf, 1.0),
                            (1.0, -np.inf), (-np.inf, -np.inf)):
            with self.subTest(left=left, right=right):
                result = self.pair([1.0, left], [1.0, right])
                for tier in ("T0", "T1", "T2"):
                    self.assertFalse(self.passes(result, tier), tier)
        cli = self.cli("--tier", "T2")
        self.assertEqual(cli.returncode, 1)
        self.assertIn("infinite pixels", cli.stdout)
        self.assertEqual(cli.stderr, "")

    def test_ulp_adjacent_values_and_sign_crossing_for_float32_and_float64(self):
        for dtype in (np.float32, np.float64):
            for byteorder in ("<", ">"):
                with self.subTest(dtype=dtype, byteorder=byteorder):
                    a = np.array([-1.0, 1.0], dtype=dtype)
                    b = np.nextafter(a, dtype(0))
                    storage = np.dtype(dtype).newbyteorder(byteorder)
                    self.assertEqual(compare_fits.ulp_diff(a.astype(storage), b.astype(storage)), 1)
                    tiny = np.nextafter(dtype(0), dtype(1))
                    self.assertEqual(compare_fits.ulp_diff(
                        np.array([-tiny], dtype=storage), np.array([tiny], dtype=storage)), 2)

    def test_zero_arrays_pass_all_tiers_and_cli_with_zero_thresholds(self):
        result = self.pair(np.zeros(2), np.zeros(2))
        for tier in ("T0", "T1", "T2"):
            self.assertTrue(self.passes(result, tier), tier)
            cli = self.cli("--tier", tier, "--max-ulp", "0",
                           "--max-rel-rms", "0", "--max-rel-peak", "0")
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertIn("PASS", cli.stdout)
            self.assertEqual(cli.stderr, "")

    def test_cli_ulp_threshold_is_inclusive(self):
        self.pair([1.0], [np.nextafter(1.0, 2.0)])
        self.assertEqual(self.cli().returncode, 1)
        self.assertEqual(self.cli("--tier", "T1", "--max-ulp", "0").returncode, 1)
        self.assertEqual(self.cli("--tier", "T1", "--max-ulp", "1").returncode, 0)

    def test_t2_metrics_and_thresholds(self):
        result = self.pair([3.0, 4.0], [3.0, 4.5])
        self.assertAlmostEqual(result["rel_rms"], 0.1)
        self.assertEqual(result["rel_peak"], 0.125)
        self.assertEqual(result["peak_ratio"], 1.125)
        self.assertFalse(self.passes(result, "T2", max_rel_rms=0.09, max_rel_peak=0.2))
        self.assertFalse(self.passes(result, "T2", max_rel_rms=0.2, max_rel_peak=0.12))
        self.assertTrue(self.passes(result, "T2", max_rel_rms=0.1, max_rel_peak=0.125))
        self.assertEqual(self.cli("--tier", "T2", "--max-rel-rms", "0.1",
                                 "--max-rel-peak", "0.125").returncode, 0)

    def test_shape_mismatch_fails_cleanly(self):
        result = self.pair(np.ones((1, 2)), np.ones((2, 1)))
        for tier in ("T0", "T1", "T2"):
            self.assertFalse(self.passes(result, tier), tier)
        cli = self.cli()
        self.assertEqual(cli.returncode, 1)
        self.assertIn("shape", cli.stdout)
        self.assertEqual(cli.stderr, "")

    def test_product_mismatch_and_no_common_products_fail_cli(self):
        empty = self.cli()
        self.assertEqual(empty.returncode, 1)
        self.assertIn("no common FITS products", empty.stdout)
        self.pair([1.0], [1.0])
        fits.writeto(self.test / "extra.fits", np.ones(1))
        mismatch = self.cli()
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("product mismatch", mismatch.stdout)
        self.assertIn("extra.fits", mismatch.stdout)
        self.assertIn("PASS", mismatch.stdout)

    def test_missing_file_comparison_returns_error(self):
        result = compare_fits.compare(self.ref / "missing.fits", self.test / "missing.fits")
        self.assertIn("input error", result["error"])
        self.assertFalse(self.passes(result, "T0"))


if __name__ == "__main__":
    unittest.main()
