#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Dump the UVW/DATA/FLAG columns that the real-uv benchmark reads, and verify
# the dump before anyone uses it:
#
#   scripts/dump_ms_uvw.sh <ms> <output.txt>
#
# The verification exists because taql fails silently in two ways that both
# produce a plausible-looking small file:
#   * without -ps -m it prints only the first 50 rows (a 621 250-row dump once
#     became 54 lines);
#   * the Homebrew casacore in /opt/homebrew/bin is linked against a removed
#     libhdf5, so a background job can pick a broken taql off PATH. This script
#     defaults to the project's own build and checks -o actually got rows.
# It also refuses to overwrite an existing dump: two attempts writing the same
# path is a race, and the loser can be the good one.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$#" -ne 2 ]; then
  printf 'usage: %s <measurement-set> <output.txt>\n' "$0" >&2
  exit 2
fi

MS="$1"
OUT="$2"

[ -d "$MS" ] || { printf 'not a measurement set: %s\n' "$MS" >&2; exit 2; }
if [ -e "$OUT" ]; then
  printf 'refusing to overwrite %s - write to a new name and compare\n' "$OUT" >&2
  exit 2
fi

TAQL="${TAQL:-$ROOT/deps/install/bin/taql}"
[ -x "$TAQL" ] || { printf 'taql not executable: %s (set TAQL=...)\n' "$TAQL" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
printf 'dumping %s with %s\n' "$MS" "$TAQL"
"$TAQL" -ps -m 2000000 -o "$OUT" \
  "select UVW[0] as u, UVW[1] as v, UVW[2] as w, real(DATA[0,0]) as xr, imag(DATA[0,0]) as xi, FLAG[0,0] as f0 from $MS"

# Data rows start with a number AND contain a tab; taql's own headers can
# start with a digit too ("6 selected columns: ..."), so the tab is required.
rows="$(grep -cE '^[0-9-][^	]*	' "$OUT" || true)"
nan_rows="$(grep -c 'nan' "$OUT" || true)"
expected="$(head -1 "$OUT" | sed -n 's/.*select result of \([0-9]*\) rows.*/\1/p')"

if [ -z "$expected" ]; then
  printf 'no row count in the taql header - unexpected output format\n' >&2
  exit 1
fi
if [ "$rows" -ne "$expected" ]; then
  printf 'incomplete dump: %s of %s rows (is -ps -m missing?)\n' "$rows" "$expected" >&2
  exit 1
fi
if [ "$rows" -le 50 ]; then
  printf 'suspiciously small dump (%s rows): taql shows only 50 rows without -ps -m\n' "$rows" >&2
  exit 1
fi

printf 'wrote %s rows=%s nan_rows=%s\n' "$OUT" "$rows" "$nan_rows"
