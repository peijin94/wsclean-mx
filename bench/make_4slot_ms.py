#!/usr/bin/env python3
"""Materialise the 4-slot LWA subset into a standalone MS (no reference table).

Step 1: taql SELECT into a reference table (fast, no data copy).
Step 2: casacore deep copy -> flat MS, so later reads never touch the 16 GB parent.
"""
import shutil
import sys
import time

import casacore.tables as T

PARENT = "/data/64mhz.ms"
REF = "/data/lwa-4slot-ref.ms"
FLAT = "/data/lwa-4slot-flat.ms"
CUT = 5268786660.0  # MJD 60312.327083 = 2025-11-02T07:51:00 UTC

SUBTABLES = [
    "ANTENNA", "DATA_DESCRIPTION", "FEED", "FIELD", "FLAG_CMD", "HISTORY",
    "OBSERVATION", "POINTING", "POLARIZATION", "PROCESSOR", "SOURCE",
    "SPECTRAL_WINDOW", "STATE",
]

t0 = time.time()
for path in (REF, FLAT):
    shutil.rmtree(path, ignore_errors=True)

print("selecting rows ...", flush=True)
with T.taql(f"SELECT * FROM {PARENT} WHERE TIME < {CUT} GIVING {REF}") as t:
    print("selected rows:", t.nrows(), flush=True)

print("copying subtables ...", flush=True)
for st in SUBTABLES:
    with T.table(f"{REF}::{st}") as src:
        dst = f"{FLAT}::{st}"
        shutil.rmtree(dst, ignore_errors=True)
        src.copy(dst, True)
        print(f"  {st}: {src.nrows()} rows", flush=True)

print("copying main table ...", flush=True)
with T.table(REF) as src:
    src.copy(FLAT, True)
    print("main rows:", src.nrows(), flush=True)

print("verifying flat table ...", flush=True)
with T.table(FLAT) as t:
    print("FLAT rows", t.nrows(), "cols", len(t.colnames()), flush=True)
    print("FLAT DATA shape", t.getcell("DATA", 0).shape, flush=True)

print(f"done in {time.time() - t0:.1f}s", flush=True)
