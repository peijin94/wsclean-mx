#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Compare the FITS products of two bench/run.sh variants, pixel by pixel.

    bench/compare_fits.py bench/out/<tag>/<variant-a> bench/out/<tag>/<variant-b>
        [--tier T0|T1|T2] [--max-ulp N] [--max-rel-rms X] [--max-rel-peak X]

Only data arrays are compared; headers always differ (dates, versions).

Tiers (see notes.md, "Comparison contract"):
  T0  bitwise identical data and dtype (byte order is canonicalized)
  T1  max ULP difference <= --max-ulp
  T2  rms(diff)/rms(ref) <= --max-rel-rms and max|diff|/max|ref| <= --max-rel-peak

Exit status is non-zero if any common product violates the requested tier, or
if the two directories don't contain the same set of products.
Infinite pixels, empty arrays and arrays without finite coverage fail every
tier. Matched NaN masks are allowed when finite pixels remain.
Mixed integer/float arrays fail closed if any integer is outside [-2**53, 2**53],
where conversion to float64 is no longer guaranteed to preserve the integer.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits


def load(path):
    with fits.open(path, memmap=False) as hdul:
        data = hdul[0].data
    if data is None:
        raise ValueError(f"{path}: primary HDU has no data")
    return np.ascontiguousarray(data)


def ulp_diff(a, b):
    """Max distance in units in the last place between two float arrays."""
    if a.dtype != b.dtype or a.dtype.kind != "f":
        return None
    itype = {4: np.uint32, 8: np.uint64}[a.dtype.itemsize]
    native = a.dtype.newbyteorder("=")
    ia = a.astype(native, copy=False).view(itype)
    ib = b.astype(native, copy=False).view(itype)
    # Unsigned ordering avoids overflow even across the full float64 range.
    # Both signed zeros map to the midpoint.
    sign = itype(1 << (8 * a.dtype.itemsize - 1))
    ia = np.where(ia & sign, sign - (ia & (sign - itype(1))), sign + ia)
    ib = np.where(ib & sign, sign - (ib & (sign - itype(1))), sign + ib)
    return int(np.max(np.maximum(ia, ib) - np.minimum(ia, ib))) if ia.size else 0


def rms(values):
    """Compute RMS without squaring unscaled float64 magnitudes."""
    peak = float(np.nanmax(np.abs(values)))
    if not peak or not np.isfinite(peak):
        return peak
    return peak * float(np.sqrt(np.nanmean((values / peak) ** 2)))


def integer_difference(a, b):
    """Subtract as Python integers before rounding differences for RMS metrics.

    This handles signed/unsigned mixtures and their full range without overflow.
    Object temporaries are bounded; no image-sized object arrays are created.
    Integer differences cannot underflow to zero when converted to float64.
    """
    d = np.empty(a.shape, dtype=np.float64)
    for start in range(0, a.size, 4096):
        stop = start + 4096
        exact = b.flat[start:stop].astype(object) - a.flat[start:stop].astype(object)
        d.flat[start:stop] = exact
    return d


def compare(ref_path, test_path):
    try:
        a, b = load(ref_path), load(test_path)
    except (OSError, ValueError, TypeError, IndexError) as exc:
        return {"name": ref_path.name, "error": f"input error: {exc}"}
    r = {"name": ref_path.name, "shape": a.shape}
    if a.shape != b.shape:
        r["error"] = f"shape {a.shape} vs {b.shape}"
        return r
    if not a.size:
        r["error"] = "empty data array"
        return r
    if np.any(np.isinf(a)) or np.any(np.isinf(b)):
        r["error"] = "infinite pixels"
        return r
    if np.all(np.isnan(a)) or np.all(np.isnan(b)):
        r["error"] = "no finite pixels"
        return r
    for integer, floating in ((a, b), (b, a)):
        if integer.dtype.kind in "iu" and floating.dtype.kind == "f":
            if int(integer.min()) < -(2**53) or int(integer.max()) > 2**53:
                r["error"] = "mixed integer/float comparison outside exact float64 integer range"
                return r
    native_a = a.astype(a.dtype.newbyteorder("="), copy=False)
    native_b = b.astype(b.dtype.newbyteorder("="), copy=False)
    r["bitwise"] = (native_a.dtype == native_b.dtype
                    and native_a.tobytes() == native_b.tobytes())
    both_nan = np.isnan(a) & np.isnan(b)
    r["nan_mismatch"] = int(np.count_nonzero(np.isnan(a) != np.isnan(b)))
    a64 = np.where(both_nan, 0, a).astype(np.float64)
    b64 = np.where(both_nan, 0, b).astype(np.float64)
    if a.dtype.kind in "iu" and b.dtype.kind in "iu":
        d = integer_difference(a, b)
    else:
        # A finite pair can still have an unrepresentably large difference.
        with np.errstate(over="ignore"):
            d = b64 - a64
    rms_ref = rms(a64)
    peak_ref = float(np.nanmax(np.abs(a64)))
    r["max_abs"] = float(np.nanmax(np.abs(d)))
    rms_diff = rms(d)
    peak_test = float(np.nanmax(np.abs(b64)))
    r["rel_rms"] = rms_diff / rms_ref if rms_ref else (np.inf if rms_diff else 0.0)
    r["rel_peak"] = r["max_abs"] / peak_ref if peak_ref else (np.inf if r["max_abs"] else 0.0)
    r["peak_ratio"] = peak_test / peak_ref if peak_ref else (np.inf if peak_test else 1.0)
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
    if args.max_ulp < 0:
        p.error("--max-ulp must be nonnegative")
    for option in ("max_rel_rms", "max_rel_peak"):
        value = getattr(args, option)
        if not np.isfinite(value) or value < 0:
            p.error(f"--{option.replace('_', '-')} must be finite and nonnegative")

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
