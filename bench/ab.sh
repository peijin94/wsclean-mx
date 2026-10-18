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

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/bench/common.sh"
[ "$#" -ge 2 ] || bench_die "usage: bench/ab.sh <tag> <variantA,variantB,...> [wsclean args...]"
REPS="${REPS-3}"
COOL="${COOL-10}"
validated=$(python3 - "$REPS" "$COOL" <<'PYCODE'
import math, re, sys
reps, cool = sys.argv[1:]
if not re.fullmatch(r"[0-9]+", reps) or not 0 < int(reps) < sys.maxsize:
    sys.exit("bench: invalid REPS: expected a positive integer fitting the shell counter")
try:
    value = float(cool)
except ValueError:
    sys.exit("bench: invalid COOL: expected finite nonnegative seconds")
if not math.isfinite(value) or value < 0:
    sys.exit("bench: invalid COOL: expected finite nonnegative seconds")
print(int(reps), value if value else 0)
PYCODE
)
read -r REPS COOL <<< "$validated"
tag="$1"; variant_list="$2"; shift 2
[[ "$variant_list" =~ ^[a-zA-Z0-9_,.-]+$ &&
   "$variant_list" != *, && "$variant_list" != ,* && "$variant_list" != *,,* ]] || bench_die "invalid variant list"
IFS=, read -r -a variants <<< "$variant_list"
seen=,
for v in "${variants[@]}"; do
  [[ "$seen" != *,"$v",* ]] || bench_die "invalid duplicate variant: $v"
  seen+="$v,"
done

bench_slug "$tag" tag
bench_args "$@"
for v in "${variants[@]}"; do bench_variant "$v"; done
results="$ROOT/bench/out/$tag-ab.tsv"
bench_output "$results"
for ((r = 1; r <= REPS; r++)); do
  for v in "${variants[@]}"; do
    bench_output "$ROOT/bench/out/$tag-r$r/$v"
  done
done
mkdir -p "$(dirname "$results")"
(set -o noclobber
 printf "variant\trep\twall\tinversion\tprediction\tdeconvolution\n" > "$results"
) || bench_die "results already exist or cannot be created: $results"

stage_times() {
  python3 - "$1" <<'PYCODE'
import math, re, sys
from pathlib import Path
try:
    lines = [line for line in Path(sys.argv[1]).read_text().splitlines() if line.startswith("Inversion:")]
except OSError:
    sys.exit(f"bench: missing stage timing log: {sys.argv[1]}")
pattern = r"Inversion: (\S+), prediction: (\S+), deconvolution: (\S+)\s*"
match = re.fullmatch(pattern, lines[-1]) if lines else None
if not match:
    sys.exit(f"bench: missing or malformed stage timing: {sys.argv[1]}")
values = []
for text in match.groups():
    if not re.fullmatch(r"[0-9]+:[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?", text):
        sys.exit(f"bench: malformed stage timing: {text}")
    h, m, s = map(float, text.split(":"))
    value = h * 3600 + m * 60 + s
    if not math.isfinite(value):
        sys.exit(f"bench: nonfinite stage timing: {text}")
    values.append(f"{value:.3f}")
print(" ".join(values))
PYCODE
}

for ((r = 1; r <= REPS; r++)); do
  for ((i = 0; i < ${#variants[@]}; i++)); do
    index=$i
    if ((r % 2 == 0)); then index=$((${#variants[@]} - 1 - i)); fi
    v="${variants[index]}"
    sleep "$COOL"
    "$ROOT/bench/run.sh" "$v" "$tag-r$r" "$@" > /dev/null
    out="$ROOT/bench/out/$tag-r$r/$v"
    wall=$(bench_wall_time "$out/time.txt")
    stages=$(stage_times "$out/wsclean.log")
    read -r inv pred dec <<< "$stages"
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
