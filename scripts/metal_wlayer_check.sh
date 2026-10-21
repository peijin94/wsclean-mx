#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build and run the w-layer check: the Metal inversion (w-gridding path) against
# ducc0's own w-gridded inversion on identical synthetic data. Fast enough to
# bisect with - a few seconds per run.
#
#   scripts/metal_wlayer_check.sh [--nvis N] [--size N] [--w-max LAMBDA] [--2d]
#
# Debug hooks (read inside the backend): MX_METAL_DEBUG_PLANES,
# MX_METAL_DEBUG_NOSCREEN, MX_METAL_DEBUG_SCALE.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCC0="$ROOT/deps/src/schaapcommon/external/ducc0"
BUILD="$ROOT/build-mx-metal"
mkdir -p "$BUILD" "$ROOT/deps/build-metal"
TOOL="$ROOT/deps/build-metal/wlayer_check"

CXX="${CXX:-/usr/bin/c++}"
LIBS=(); OMP_FLAGS=()
if [ -d /opt/homebrew/opt/libomp ]; then
  OMP_FLAGS=(-Xpreprocessor -fopenmp "-I/opt/homebrew/opt/libomp/include")
  LIBS=(-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib)
fi

"$CXX" -std=c++20 -O3 -DNDEBUG -march=native -fobjc-arc "${OMP_FLAGS[@]+"${OMP_FLAGS[@]}"}" \
  "-I$ROOT/work/wsclean" "-I$ROOT/work/wsclean/metal" "-I$ROOT/deps/src/schaapcommon/external" "-I$DUCC0" \
  "$ROOT/bench/metal/wlayer_check.cpp" \
  "$ROOT/work/wsclean/metal/metaldevice.mm" "$ROOT/work/wsclean/metal/metalinversion.mm" \
  "$DUCC0/wgridder/wgridder.cc" \
  "$ROOT/build-mx-metal/_deps/schaapcommon-build/libschaapcommon.a" \
  "$DUCC0/math/gridding_kernel.cc" "$DUCC0/math/gl_integrator.cc" \
  "$DUCC0/infra/threading.cc" "$DUCC0/infra/string_utils.cc" "$DUCC0/infra/mav.cc" \
  -framework Metal -framework Foundation -framework Accelerate \
  "${LIBS[@]+"${LIBS[@]}"}" -o "$TOOL"

"$TOOL" "$@"
