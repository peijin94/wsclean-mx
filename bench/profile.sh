#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Sample-profile one native WSClean run with macOS `sample`.
#
#   bench/profile.sh <upstream|mx|snapshot> <tag> [wsclean args...]
#
# Writes bench/out/<tag>/<variant>-profile/{sample.txt,wsclean.log,top.txt}.
# top.txt lists the functions with the most samples at the top of the stack
# (self time), summed over all threads.
#
# The output directory must not exist: this harness never removes pre-existing
# results, so re-invoking it cannot destroy an earlier profile or another run's
# evidence. Use a new tag instead.
# SAMPLE_TOOL overrides the sampler command (used by the harness tests).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/bench/common.sh"
[ "$#" -ge 2 ] || bench_die "usage: bench/profile.sh <variant> <tag> [wsclean args...]"
variant="$1"; tag="$2"; shift 2
bench_slug "$variant" variant
bench_slug "$tag" tag
bench_variant "$variant"
bench_args "$@"

sampler="${SAMPLE_TOOL:-sample}"
command -v "$sampler" >/dev/null \
  || bench_die "unavailable sampler: $sampler (macOS 'sample' is required)"

case "$variant" in
  upstream) bin="$ROOT/build-upstream/wsclean" ;;
  mx)       bin="$ROOT/build-mx/wsclean" ;;
  *)        bin="$ROOT/bench/bin/$variant/wsclean" ;;
esac

out="$ROOT/bench/out/$tag/$variant-profile"
bench_output "$out"
mkdir -p "$out/tmp"

cd "$ROOT"
"$bin" -no-update-model-required -temp-dir "$out/tmp" -name "$out/img" "$@" \
  > "$out/wsclean.log" 2>&1 &
pid=$!
"$sampler" "$pid" "${SAMPLE_SECONDS:-600}" 1 -mayDie -file "$out/sample.txt" >/dev/null 2>&1 || true
wait "$pid"
rm -rf -- "$out/tmp"

# "Sort by top of stack" section of the sample report = self time per function.
awk '/^Sort by top of stack/{f=1;next} f&&NF' "$out/sample.txt" | head -40 > "$out/top.txt"
tail -1 "$out/wsclean.log"
cat "$out/top.txt"
