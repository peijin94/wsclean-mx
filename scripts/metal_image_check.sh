#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build and run the image-level check of the Metal gridding: the grid is computed
# on the GPU, pushed through ducc0's own forward chain (complex2hartley ->
# hartley2_2D -> extraction with ducc0's kernel correction), and the resulting
# dirty image is compared with ducc0::ms2dirty_bda on identical data.
#
#   scripts/metal_image_check.sh [--nvis N] [--size N] [--uvw-file F --freq HZ]
#
# Output goes to <build-mx-metal>/metal-image-check.txt.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCC0="$ROOT/deps/src/schaapcommon/external/ducc0"
[ -d "$DUCC0" ] || { printf 'ducc0 source not found at %s\n' "$DUCC0" >&2; exit 2; }

BUILD="$ROOT/build-mx-metal"
mkdir -p "$BUILD" "$ROOT/deps/build-metal"
TOOL="$ROOT/deps/build-metal/ducc0_image_check"
OUT="$BUILD/metal-image-check.txt"

CXX="${CXX:-/usr/bin/c++}"
LIBS=()
OMP_FLAGS=()
if [ -d /opt/homebrew/opt/libomp ]; then
  OMP_FLAGS=(-Xpreprocessor -fopenmp "-I/opt/homebrew/opt/libomp/include")
  LIBS=(-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib)
else
  printf 'note: Homebrew libomp not found, building single-threaded\n' >&2
fi

# metaldevice.mm is Objective-C++ and needs ARC plus the Metal framework; the
# shader source is a string compiled at runtime, so no metallib step exists.
"$CXX" -std=c++20 -O3 -DNDEBUG -march=native -fobjc-arc "${OMP_FLAGS[@]+"${OMP_FLAGS[@]}"}" \
  "-I$ROOT/work/wsclean" "-I$ROOT/work/wsclean/metal" "-I$ROOT/deps/src/schaapcommon/external" "-I$DUCC0" \
  "$ROOT/bench/metal/ducc0_image_check.cpp" "$ROOT/work/wsclean/metal/metaldevice.mm" \
  
  "$DUCC0/wgridder/wgridder.cc" \
  "$DUCC0/math/gridding_kernel.cc" "$DUCC0/math/gl_integrator.cc" \
  "$DUCC0/infra/threading.cc" "$DUCC0/infra/string_utils.cc" "$DUCC0/infra/mav.cc" \
  -framework Metal -framework Foundation \
  "${LIBS[@]+"${LIBS[@]}"}" -o "$TOOL"

"$TOOL" "$@" | tee "$OUT"
printf 'wrote %s\n' "$OUT"
