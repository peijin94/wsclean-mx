#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Repeat one WSClean configuration and flag runs whose first noise estimate is
# far off, to find intermittent corruption.
#
#   N=6 bench/flake.sh <tag> <v1,v2,...> [wsclean args...]
#
# Prints one line per run: variant, run index, wall time, first noise estimate.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
tag="$1"; IFS=, read -r -a variants <<< "$2"; shift 2
N="${N:-6}"
summary="$ROOT/bench/out/$tag-flake.tsv"
: > "$summary"
for i in $(seq 1 "$N"); do
  for v in "${variants[@]}"; do
    run_tag="$tag/r$i"
    "$ROOT/bench/run.sh" "$v" "$run_tag" "$@" > /dev/null 2>&1 || true
    out="$ROOT/bench/out/$run_tag/$v"
    wall=$(awk '/^real/{print $2}' "$out/time.txt" 2>/dev/null || echo NA)
    noise=$(grep -m1 "standard deviation of background noise" "$out/wsclean.log" | sed 's/.*noise: //')
    printf '%s\t%s\t%s\t%s\n' "$v" "$i" "$wall" "$noise" | tee -a "$summary"
  done
done
