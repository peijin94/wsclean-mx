#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Compare the FITS products of two bench/run.sh variants, pixel by pixel.

    bench/compare_fits.py bench/out/<tag>/<variant-a> bench/out/<tag>/<variant-b>
        [--tier T0|T1|T2] [--max-ulp N] [--max-rel-rms X] [--max-rel-peak X]

Only data arrays are compared; headers always differ (dates, versions).

Tiers (see notes.md, "Comparison contract"):
  T0  bitwise identical data
  T1  max ULP difference <= --max-ulp
  T2  rms(diff)/rms(ref) <= --max-rel-rms and max|diff|/max|ref| <= --max-rel-peak

Exit status is non-zero if any common product violates the requested tier, or
if the two directories don't contain the same set of products.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits


def load(path):
    with fits.open(path, memmap=False) as hdul:
        data = hdul[0].data
    return np.ascontiguousarray(data)


def ulp_diff(a, b):
    """Max distance in units in the last place between two float arrays."""
    if a.dtype != b.dtype or a.dtype.kind != "f":
        return None
    itype = {4: np.int32, 8: np.int64}[a.dtype.itemsize]
    ia, ib = a.view(itype).astype(np.int64), b.view(itype).astype(np.int64)
    # Map sign-magnitude floats onto a monotonic integer line (-0.0 -> 0).
    int_min = -(np.int64(1) << (8 * a.dtype.itemsize - 1))
    ia = np.where(ia < 0, int_min - ia, ia)
    ib = np.where(ib < 0, int_min - ib, ib)
    return int(np.max(np.abs(ia - ib))) if ia.size else 0


def compare(ref_path, test_path):
    a, b = load(ref_path), load(test_path)
    r = {"name": ref_path.name, "shape": a.shape}
    if a.shape != b.shape:
        r["error"] = f"shape {a.shape} vs {b.shape}"
        return r
    r["bitwise"] = (hashlib.sha256(a.tobytes()).digest()
                    == hashlib.sha256(b.tobytes()).digest())
    both_nan = np.isnan(a) & np.isnan(b)
    r["nan_mismatch"] = int(np.count_nonzero(np.isnan(a) != np.isnan(b)))
    a64 = np.where(both_nan, 0, a).astype(np.float64)
    b64 = np.where(both_nan, 0, b).astype(np.float64)
    d = b64 - a64
    rms_ref = float(np.sqrt(np.nanmean(a64 ** 2)))
    peak_ref = float(np.nanmax(np.abs(a64)))
    r["max_abs"] = float(np.nanmax(np.abs(d)))
    r["rel_rms"] = float(np.sqrt(np.nanmean(d ** 2))) / rms_ref if rms_ref else 0.0
    r["rel_peak"] = r["max_abs"] / peak_ref if peak_ref else 0.0
    r["peak_ratio"] = float(np.nanmax(np.abs(b64))) / peak_ref if peak_ref else 1.0
    r["n_diff"] = int(np.count_nonzero(d))
    r["max_ulp"] = ulp_diff(np.where(both_nan, 0, a), np.where(both_nan, 0, b))
    return r


def passes(r, args):
    if "error" in r or r["nan_mismatch"]:
        return False
    if args.tier == "T0":
        return r["bitwise"]
    if args.tier == "T1":
        return r["max_ulp"] is not None and r["max_ulp"] <= args.max_ulp
    return r["rel_rms"] <= args.max_rel_rms and r["rel_peak"] <= args.max_rel_peak


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ref", type=Path)
    p.add_argument("test", type=Path)
    p.add_argument("--tier", choices=["T0", "T1", "T2"], default="T0")
    p.add_argument("--max-ulp", type=int, default=4)
    p.add_argument("--max-rel-rms", type=float, default=1e-4)
    p.add_argument("--max-rel-peak", type=float, default=1e-3)
    args = p.parse_args()

    ref = {f.name: f for f in sorted(args.ref.glob("*.fits"))}
    test = {f.name: f for f in sorted(args.test.glob("*.fits"))}
    ok = True
    if ref.keys() != test.keys():
        print(f"product mismatch: only in ref {sorted(ref.keys() - test.keys())}, "
              f"only in test {sorted(test.keys() - ref.keys())}")
        ok = False
    if not ref.keys() & test.keys():
        print("no common FITS products")
        return 1

    print(f"ref:  {args.ref}\ntest: {args.test}\ntier: {args.tier}\n")
    hdr = (f"{'product':<28}{'bitwise':>8}{'n_diff':>10}{'max_ulp':>12}"
           f"{'max_abs':>12}{'rel_rms':>11}{'rel_peak':>11}{'peak_ratio':>12}  result")
    print(hdr)
    print("-" * len(hdr))
    for name in sorted(ref.keys() & test.keys()):
        r = compare(ref[name], test[name])
        good = passes(r, args)
        ok &= good
        if "error" in r:
            print(f"{name:<28}{r['error']}  FAIL")
            continue
        ulp = "n/a" if r["max_ulp"] is None else str(r["max_ulp"])
        print(f"{name:<28}{str(r['bitwise']):>8}{r['n_diff']:>10}{ulp:>12}"
              f"{r['max_abs']:>12.3e}{r['rel_rms']:>11.2e}{r['rel_peak']:>11.2e}"
              f"{r['peak_ratio']:>12.8f}  {'PASS' if good else 'FAIL'}")
        if r["nan_mismatch"]:
            print(f"{'':<28}NaN pattern differs in {r['nan_mismatch']} pixels")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
