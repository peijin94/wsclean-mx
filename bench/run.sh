#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Run one WSClean invocation on a given variant, with identical arguments and
# paths across variants.
#
#   bench/run.sh <variant> <tag> [wsclean args...]
#
# variant: linc     - astronrd/linc container (x86_64, Rosetta, Apple container)
#          upstream - native arm64 build of the pinned upstream (build-upstream/)
#          mx       - native arm64 build of wsclean-mx (build-mx/)
#          <name>   - snapshot binary bench/bin/<name>/wsclean (gitignored)
#
# Output goes to bench/out/<tag>/<variant>/ (images, wsclean.log, time.txt).
# Every variant runs with the repo root as working directory, and the repo is
# mounted at the same absolute path inside the container, so every path in
# the arguments (relative or absolute) is valid for every variant.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/bench/common.sh"
[ "$#" -ge 2 ] || bench_die "usage: bench/run.sh <variant> <tag> [wsclean args...]"
variant="$1"; tag="$2"; shift 2
bench_variant "$variant"
bench_slug "$tag" tag
bench_args "$@"
out="$ROOT/bench/out/$tag/$variant"
bench_output "$out"

# Suppress normal imaging MODEL_DATA updates; bench_args rejects known writers.
args=(-no-update-model-required -temp-dir "$out/tmp" -name "$out/img" "$@")

case "$variant" in
  linc)
    LINC_IMAGE="${LINC_IMAGE:-docker.io/astronrd/linc:5.2.1}"
    CONTAINER_CPUS="${CONTAINER_CPUS:-$(sysctl -n hw.ncpu)}"
    CONTAINER_MEM="${CONTAINER_MEM:-12g}"
    cmd=(container run --rm --platform linux/amd64 --rosetta
         -c "$CONTAINER_CPUS" -m "$CONTAINER_MEM"
         -v "$ROOT:$ROOT" -w "$ROOT" "$LINC_IMAGE" wsclean "${args[@]}") ;;
  upstream) cmd=("$ROOT/build-upstream/wsclean" "${args[@]}") ;;
  mx)       cmd=("$ROOT/build-mx/wsclean" "${args[@]}") ;;
  *)
    # Snapshot of an earlier mx build, e.g. bench/bin/mx-p1/wsclean.
    cmd=("$ROOT/bench/bin/$variant/wsclean" "${args[@]}") ;;
esac

mkdir -p "$(dirname "$out")"
mkdir "$out" || bench_die "output already exists or cannot be created: $out"
mkdir "$out/tmp"

printf '%q ' "${cmd[@]}" > "$out/cmd.txt"; echo >> "$out/cmd.txt"
(cd "$ROOT" && /usr/bin/time -lp "${cmd[@]}" > "$out/wsclean.log" 2> "$out/time.txt") || {
  echo "FAILED ($variant): see $out/wsclean.log" >&2
  tail -8 "$out/wsclean.log" >&2; exit 1; }
rmdir "$out/tmp" 2>/dev/null || true

wall=$(bench_wall_time "$out/time.txt")
rss=$(awk '/maximum resident set size/{printf "%.0f", $1/1048576}' "$out/time.txt")
echo "$variant $tag wall=${wall}s host_peak_rss=${rss}MiB"
grep -E "Inversion:|prediction:|deconvolution:" "$out/wsclean.log" | tail -1 || true
