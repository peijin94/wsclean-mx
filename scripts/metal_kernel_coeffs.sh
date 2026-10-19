#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Extract ducc0's fitted gridding kernel (the one its w-gridder uses) so the
# Metal probe can evaluate exactly that kernel:
#
#   scripts/metal_kernel_coeffs.sh [--epsilon E] [--ofactor F] [--ndim N]
#
# Writes <build-mx-metal>/ducc0-kernel-w<support>.txt and prints the row it
# selected plus two checks: the shader's evaluation convention against ducc0's
# own polynomial evaluation (must be exact) and the float32 coefficient storage
# level. wsclean's default -wgridder-accuracy is 1e-4, which selects the W=6
# row; pass --epsilon 1e-7 to see the wider-support rows.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCC0="$ROOT/deps/src/schaapcommon/external/ducc0"
[ -d "$DUCC0" ] || { printf 'ducc0 source not found at %s\n' "$DUCC0" >&2; exit 2; }

BUILD="$ROOT/build-mx-metal"
mkdir -p "$BUILD" "$ROOT/deps/build-metal"
TOOL="$ROOT/deps/build-metal/ducc0_kernel_tool"

CXX="${CXX:-/usr/bin/c++}"
"$CXX" -std=c++20 -O2 "-I$ROOT/deps/src/schaapcommon/external" \
  "$ROOT/bench/metal/ducc0_kernel_tool.cpp" \
  "$DUCC0/math/gridding_kernel.cc" "$DUCC0/math/gl_integrator.cc" \
  "$DUCC0/infra/threading.cc" "$DUCC0/infra/string_utils.cc" "$DUCC0/infra/mav.cc" \
  -o "$TOOL"

EPSILON=1e-4
OUT="$BUILD/ducc0-kernel-w6.txt"
"$TOOL" --epsilon "$EPSILON" --out "$OUT" "$@"
