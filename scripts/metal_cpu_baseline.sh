#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build and run the ducc0 CPU baseline for the Metal kernels: it grids and
# degrids the same synthetic visibilities as the Metal probe with ducc0's own
# w-gridder, so the two can be compared directly.
#
#   scripts/metal_cpu_baseline.sh [--nvis N] [--grid N] [--threads N] [--repeat N]
#
# Output goes to <build-mx-metal>/cpu-ducc0-baseline.txt. The tool mirrors
# wsclean's own ms2dirty_bda/dirty2ms_bda call (one band, flat visibilities,
# empty weight/mask, flip_v, sigma 1.1/2.0, pixsize 1/nxdirty) with
# do_wgridding=false so that it measures the same 2D gridding the Metal kernels
# implement. ducc0's FFT and kernel correction are inside the number.
#
# This needs an OpenMP runtime: the build uses Homebrew's libomp when present
# (Apple clang has no bundled one), and falls back to compiling without
# -fopenmp, which makes ducc0 single-threaded and inflates the CPU number.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCC0="$ROOT/deps/src/schaapcommon/external/ducc0"
[ -d "$DUCC0" ] || { printf 'ducc0 source not found at %s\n' "$DUCC0" >&2; exit 2; }

BUILD="$ROOT/build-mx-metal"
mkdir -p "$BUILD" "$ROOT/deps/build-metal"
TOOL="$ROOT/deps/build-metal/ducc0_wgridder_tool"
OUT="$BUILD/cpu-ducc0-baseline.txt"

CXX="${CXX:-/usr/bin/c++}"
LIBS=()
OMP_FLAGS=()
if [ -d /opt/homebrew/opt/libomp ]; then
  OMP_FLAGS=(-Xpreprocessor -fopenmp "-I/opt/homebrew/opt/libomp/include")
  LIBS=(-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib)
else
  printf 'note: Homebrew libomp not found, building single-threaded\n' >&2
fi

# -march=native matters: without a SIMD width ducc0 selects scalar paths and the
# baseline is much slower than what wsclean's own build does.
"$CXX" -std=c++20 -O3 -DNDEBUG -march=native "${OMP_FLAGS[@]+"${OMP_FLAGS[@]}"}" \
  "-I$ROOT/deps/src/schaapcommon/external" "-I$ROOT/work/wsclean/metal" \
  "$ROOT/bench/metal/ducc0_wgridder_tool.cpp" \
  "$DUCC0/math/gridding_kernel.cc" "$DUCC0/math/gl_integrator.cc" \
  "$DUCC0/infra/threading.cc" "$DUCC0/infra/string_utils.cc" "$DUCC0/infra/mav.cc" \
  "${LIBS[@]+"${LIBS[@]}"}" -o "$TOOL"

THREADS=8
previous=""
for arg in "$@"; do
  if [ "$previous" = "--threads" ]; then THREADS="$arg"; fi
  case "$arg" in --threads=*) THREADS="${arg#--threads=}" ;; esac
  previous="$arg"
done

OMP_NUM_THREADS="$THREADS" "$TOOL" --threads "$THREADS" "$@" | tee "$OUT"
printf 'wrote %s\n' "$OUT"
