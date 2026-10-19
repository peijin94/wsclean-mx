#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build (into build-mx-metal/) and run the experimental Apple Metal backend
# probe. The default builds are untouched: only this script configures with
# -DWSCLEAN_MX_METAL=ON.
#
#   scripts/metal_build.sh                 configure (if needed), build, run
#   scripts/metal_build.sh --reconfigure   force a fresh configure first
#   scripts/metal_build.sh --quiet         one summary line per size
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

BUILD="$ROOT/build-mx-metal"
RECONFIGURE=0
PROBE_ARGS=()
for argument in "$@"; do
  case "$argument" in
    --reconfigure) RECONFIGURE=1 ;;
    *) PROBE_ARGS+=("$argument") ;;
  esac
done

if [ "$RECONFIGURE" = 1 ] || [ ! -f "$BUILD/CMakeCache.txt" ]; then
  DEP_FLAGS=()
  for dep in aocommon schaapcommon radler; do
    upper="$(echo "$dep" | tr '[:lower:]' '[:upper:]')"
    DEP_FLAGS+=("-DFETCHCONTENT_SOURCE_DIR_${upper}=$ROOT/work/$dep")
  done
  "$ROOT/scripts/configure_wsclean.sh" "$ROOT/work/wsclean" "$BUILD" \
    "${DEP_FLAGS[@]}" -DWSCLEAN_MX_METAL=ON
fi

"$CMAKE" --build "$BUILD" --target mx-metal-probe -j "${JOBS:-$(sysctl -n hw.ncpu)}"
exec "$BUILD/metal/mx-metal-probe" "${PROBE_ARGS[@]}"
