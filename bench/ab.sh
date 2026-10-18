#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# A/B timing: alternate variants for N repeats (with a cool-down between runs,
# this is a fanless laptop) and report min / median per stage.
#
#   REPS=3 COOL=10 bench/ab.sh <tag> <variantA,variantB,...> [wsclean args...]
#
# Runs land in bench/out/<tag>-r<i>/<variant>/; compare products with
# bench/compare_fits.py. Each row also records retired instructions and cycles
# when the platform's time command provides them, and the comparison's mode
# assessment is written to bench/out/<tag>-ab.mode.txt and printed BEFORE the
# ratio table: wall-clock alone does not distinguish a code cost from a host
# timing mode, and container variants report their launcher's counters rather
# than the guest's.
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
mode_file="$ROOT/bench/out/$tag-ab.mode.txt"
bench_output "$mode_file"
for ((r = 1; r <= REPS; r++)); do
  for v in "${variants[@]}"; do
    bench_output "$ROOT/bench/out/$tag-r$r/$v"
  done
done
mkdir -p "$(dirname "$results")"
(set -o noclobber
 printf "variant\trep\twall\tinversion\tprediction\tdeconvolution\tinstructions_G\tcycles_G\n" > "$results"
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
    counters=$(bench_counters "$out/time.txt") || bench_die "invalid hardware counters: $out/time.txt"
    read -r instructions cycles <<< "$counters"
    printf "%s\t%d\t%s\t%s\t%s\t%s\t%s\t%s\n" "$v" "$r" "$wall" "$inv" "$pred" "$dec" "$instructions" "$cycles" | tee -a "$results"
  done
done

python3 - "$results" "$mode_file" <<'EOF'
import csv, math, statistics, sys

rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
cols = ["wall", "inversion", "prediction", "deconvolution"]
variants = list(dict.fromkeys(r["variant"] for r in rows))


def positive(value):
    """A usable measurement: finite and strictly positive. Anything else (absent,
    zero, negative, nonfinite, unparseable) disqualifies the comparison rather
    than being read as a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


samples, wall_values, complete = {}, {}, True
for row in rows:
    pair = (positive(row.get("instructions_G")), positive(row.get("cycles_G")))
    if None in pair:
        complete = False
    samples.setdefault(row["variant"], []).append(pair)
    wall_values.setdefault(row["variant"], []).append(positive(row.get("wall")))
if any(value is None for values in wall_values.values() for value in values):
    complete = False

counter_lines, spread = [], {}
for variant in variants:
    values = [p for p in samples[variant] if None not in p]
    walls = [value for value in wall_values[variant] if value is not None]
    if not walls:
        counter_lines.append(f"{variant}: no valid wall timings | counters not assessed")
        spread[variant] = None
        continue
    wall_span = (max(walls) - min(walls)) / max(walls)
    wall_text = f"wall {min(walls):.2f}-{max(walls):.2f}s (span {wall_span * 100:.1f}%)"
    if not values or len(values) != len(samples[variant]):
        counter_lines.append(f"{variant}: {wall_text} | counters unavailable or incomplete")
        spread[variant] = None
        continue
    instructions = [p[0] for p in values]
    cycles = [p[1] for p in values]
    span = (max(cycles) - min(cycles)) / max(cycles)
    spread[variant] = span
    counter_lines.append(
        f"{variant}: {wall_text} | {len(values)} sample(s), "
        f"instructions {min(instructions):.2f}-{max(instructions):.2f}G, "
        f"cycles {min(cycles):.2f}-{max(cycles):.2f}G (span {span * 100:.1f}%)")

# Classify before the wall times are read as a variant cost: different work
# (very different instruction counts), a container launcher's counters, a
# variant whose own repeats span several cycle levels, or equal work with
# different cycle counts are all reasons why the ratio is not a patch effect.
containers = [v for v in variants if v == "linc"]
if not complete or any(spread[v] is None for v in variants):
    status = "hardware counters unavailable, incomplete or invalid: wall comparison is unclassified"
elif containers:
    status = ("container variant(s) " + ", ".join(containers) +
              ": host counters measure the container CLI, not guest execution, so the "
              "wall comparison is unclassified")
elif len(variants) < 2:
    status = "single variant: nothing to compare"
else:
    mixed = [v for v in variants if spread[v] > 0.15]
    if mixed:
        status = ("host mode present within " + ", ".join(mixed) +
                  ": repeats span several cycle levels, so the wall comparison is unclassified")
    else:
        status = "comparable"
        for index, first in enumerate(variants):
            for other in variants[index + 1:]:
                instructions = [statistics.median(p[0] for p in samples[v]) for v in (first, other)]
                cycles = [statistics.median(p[1] for p in samples[v]) for v in (first, other)]
                if abs(instructions[0] - instructions[1]) > 0.20 * max(instructions):
                    status = (f"counter scope differs between {first} and {other}: instruction "
                              "counts differ by more than 20%, so the wall comparison is "
                              "unclassified")
                elif (abs(instructions[0] - instructions[1]) <= 0.02 * max(instructions)
                        and abs(cycles[0] - cycles[1]) > 0.15 * max(cycles)):
                    status = (f"stall mode mismatch between {first} and {other}: "
                              "similar instructions, cycles differ")
                if status != "comparable":
                    break
            if status != "comparable":
                break

resolution = ("a wall difference smaller than the widest within-variant span above is not "
              "resolvable by this run (descriptive heuristic: an observed range is not a "
              "computed bound, and a single repeat gives no repeatability estimate)")

print()
print("hardware counters and mode assessment (read this before the ratios):")
for line in counter_lines:
    print(f"  {line}")
print(f"  mode: {status}")
print(f"  resolution: {resolution}")
if status == "comparable":
    print("  -> the wall comparison below is not explained by a host timing mode")
else:
    print(f"  -> NOT an established variant cost: {status}")

print()
print(f"{'variant':<10}" + "".join(f"{c + ' min/med':>26}" for c in cols))
base = None
for v in variants:
    vals = {c: sorted(float(r[c]) for r in rows if r["variant"] == v) for c in cols}
    stats = {c: (vals[c][0], statistics.median(vals[c])) for c in cols}
    base = base or stats
    cells = "".join(
        f"{stats[c][0]:>9.2f} /{stats[c][1]:>6.2f} ({base[c][0] / stats[c][0] if stats[c][0] else 0:4.2f}x)"
        for c in cols)
    print(f"{v:<10}{cells}")
print("(ratio vs first variant, on min: interpret with the mode assessment above)")

with open(sys.argv[2], "x") as mode_file_handle:
    mode_file_handle.write(status + "\n" + "\n".join(counter_lines) + "\nresolution: " + resolution + "\n")
EOF
