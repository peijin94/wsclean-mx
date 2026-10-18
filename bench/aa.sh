#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# A/A null control: run the tracked A/B runner on two byte-identical executables.
#
#   bench/aa.sh <variantA> <variantB> <tag> [wsclean args...]
#
# Both variants must be snapshots under bench/bin/ holding the same executable
# (bench/snapshot.sh writes such a copy). An A/A pair measures the host's own
# run-to-run spread and timing modes, so an A/B difference can be judged against
# it before it is called a patch effect. The control runs the normal runner, so
# its results carry the same counters and mode assessment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/bench/common.sh"
[ "$#" -ge 3 ] || bench_die "usage: bench/aa.sh <variantA> <variantB> <tag> [wsclean args...]"
a="$1"; b="$2"; tag="$3"; shift 3
bench_slug "$a" variant
bench_slug "$b" variant
[ "$a" != "$b" ] || bench_die "aa: variants must differ; the A/A control needs two names for one executable"
for v in "$a" "$b"; do
  case "$v" in
    linc) bench_die "aa: linc is a container image, not a local executable" ;;
    mx|upstream) bench_die "aa: use snapshots under bench/bin/ for the A/A control, not the live '$v' build" ;;
  esac
  bench_variant "$v"
  snapshot_dir="$ROOT/bench/bin/$v"
  binary="$snapshot_dir/wsclean"
  [ ! -L "$snapshot_dir" ] || bench_die "aa: symlinked snapshot directory: $snapshot_dir"
  [ ! -L "$binary" ] || bench_die "aa: symlinked snapshot executable: $binary"
  resolved="$(cd "$snapshot_dir" && pwd -P)"
  case "$resolved" in
    "$ROOT/bench/bin/"*) ;;
    *) bench_die "aa: snapshot resolves outside bench/bin: $v -> $resolved" ;;
  esac
done
for file in wsclean wsclean.native libschaapthreading.dylib; do
  present_a=0
  present_b=0
  if [ -L "$ROOT/bench/bin/$a/$file" ] || [ -L "$ROOT/bench/bin/$b/$file" ]; then
    bench_die "aa: symlinked snapshot payload: $file"
  fi
  if [ -f "$ROOT/bench/bin/$a/$file" ]; then present_a=1; fi
  if [ -f "$ROOT/bench/bin/$b/$file" ]; then present_b=1; fi
  [ "$present_a" = "$present_b" ] || bench_die \
    "aa: $file present in only one snapshot ($a=$present_a $b=$present_b)"
  [ "$present_a" = 1 ] || continue
  hash_a=$(bench_sha256 "$ROOT/bench/bin/$a/$file")
  hash_b=$(bench_sha256 "$ROOT/bench/bin/$b/$file")
  [ "$hash_a" = "$hash_b" ] || bench_die \
    "aa: variants are not byte-identical ($a/$file=$hash_a $b/$file=$hash_b); snapshot one build under both names"
  echo "aa: $a and $b are byte-identical for $file ($hash_a)"
done
echo "aa: running the null-control A/B"
exec "$ROOT/bench/ab.sh" "$tag" "$a,$b" "$@"
