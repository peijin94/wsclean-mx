#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# A/B timing: alternate variants for N repeats (with a cool-down between runs,
# this is a fanless laptop) and report min / median per stage.
#
#   REPS=3 COOL=10 bench/ab.sh <tag> <variantA,variantB,...> [wsclean args...]
#
# Runs land in bench/out/<tag>-r<i>/<variant>/; compare products with
# bench/compare_fits.py.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPS="${REPS:-3}"
COOL="${COOL:-10}"
tag="$1"; IFS=, read -r -a variants <<< "$2"; shift 2

results="$ROOT/bench/out/$tag-ab.tsv"
mkdir -p "$(dirname "$results")"
printf "variant\trep\twall\tinversion\tprediction\tdeconvolution\n" > "$results"

to_s() {  # hh:mm:ss.ffffff -> seconds
  awk -F: '{printf "%.3f", $1*3600 + $2*60 + $3}' <<< "$1"
}

for ((r = 1; r <= REPS; r++)); do
  for v in "${variants[@]}"; do
    sleep "$COOL"
    "$ROOT/bench/run.sh" "$v" "$tag-r$r" "$@" > /dev/null
    out="$ROOT/bench/out/$tag-r$r/$v"
    wall=$(awk '/^real/{print $2}' "$out/time.txt")
    line=$(grep -E "^Inversion:" "$out/wsclean.log" | tail -1)
    inv=$(to_s "$(sed -E 's/.*Inversion: ([0-9:.]+).*/\1/' <<< "$line")")
    pred=$(to_s "$(sed -E 's/.*prediction: ([0-9:.]+).*/\1/' <<< "$line")")
    dec=$(to_s "$(sed -E 's/.*deconvolution: ([0-9:.]+).*/\1/' <<< "$line")")
    printf "%s\t%d\t%s\t%s\t%s\t%s\n" "$v" "$r" "$wall" "$inv" "$pred" "$dec" | tee -a "$results"
  done
done

python3 - "$results" <<'EOF'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
cols = ["wall", "inversion", "prediction", "deconvolution"]
variants = list(dict.fromkeys(r["variant"] for r in rows))
print(f"\n{'variant':<10}" + "".join(f"{c + ' min/med':>26}" for c in cols))
base = None
for v in variants:
    vals = {c: sorted(float(r[c]) for r in rows if r["variant"] == v) for c in cols}
    stats = {c: (vals[c][0], statistics.median(vals[c])) for c in cols}
    base = base or stats
    cells = "".join(f"{stats[c][0]:>9.2f} /{stats[c][1]:>6.2f} ({base[c][0] / stats[c][0] if stats[c][0] else 0:4.2f}x)" for c in cols)
    print(f"{v:<10}{cells}")
print("(speedup vs first variant, on min)")
EOF
