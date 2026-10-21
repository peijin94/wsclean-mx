#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build and run the replay check: replays one exact wsclean inversion from a
# dump written by the MX_METAL_DEBUG_DUMP_INPUTS hook (header, geometry, uvws,
# frequencies, visibilities), running the Metal inversion and the ducc0
# reference with identical call-site parameters.
#
#   scripts/metal_replay_check.sh <dump>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCC0="$ROOT/deps/src/schaapcommon/external/ducc0"
mkdir -p "$ROOT/deps/build-metal"
TOOL="$ROOT/deps/build-metal/replay_check"

CXX="${CXX:-/usr/bin/c++}"
LIBS=(); OMP_FLAGS=()
if [ -d /opt/homebrew/opt/libomp ]; then
  OMP_FLAGS=(-Xpreprocessor -fopenmp "-I/opt/homebrew/opt/libomp/include")
  LIBS=(-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib)
fi

"$CXX" -std=c++20 -O3 -DNDEBUG -march=native -fobjc-arc "${OMP_FLAGS[@]+"${OMP_FLAGS[@]}"}" \
  "-I$ROOT/work/wsclean" "-I$ROOT/work/wsclean/metal" "-I$ROOT/deps/src/schaapcommon/external" "-I$DUCC0" \
  "$ROOT/bench/metal/replay_check.cpp" \
  "$ROOT/work/wsclean/metal/metaldevice.mm" "$ROOT/work/wsclean/metal/metalinversion.mm" \
  "$DUCC0/wgridder/wgridder.cc" \
  "$ROOT/build-mx-metal/_deps/schaapcommon-build/libschaapcommon.a" \
  "$DUCC0/math/gridding_kernel.cc" "$DUCC0/math/gl_integrator.cc" \
  "$DUCC0/infra/threading.cc" "$DUCC0/infra/string_utils.cc" "$DUCC0/infra/mav.cc" \
  -framework Metal -framework Foundation -framework Accelerate \
  "${LIBS[@]+"${LIBS[@]}"}" -o "$TOOL"

"$TOOL" "$@"
