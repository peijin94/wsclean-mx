#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build (into build-mx-metal/) the active Apple Metal prediction/deconvolution
# backend. The default builds are untouched: only this script configures with
# -DWSCLEAN_MX_METAL=ON.
#
#   scripts/metal_build.sh                 configure (if needed), build active targets
#   scripts/metal_build.sh --reconfigure   force a fresh configure first
#   scripts/metal_build.sh --quiet         accepted for compatibility; no runtime probes
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

BUILD="$ROOT/build-mx-metal"
RECONFIGURE=0

for argument in "$@"; do
  case "$argument" in
    --reconfigure) RECONFIGURE=1 ;;
    --quiet) ;;
    *) printf 'Unknown argument: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

if [ "$RECONFIGURE" = 1 ] || [ ! -f "$BUILD/CMakeCache.txt" ]; then
  DEP_FLAGS=()
  for dep in aocommon schaapcommon radler; do
    upper="$(echo "$dep" | tr '[:lower:]' '[:upper:]')"
    DEP_FLAGS+=("-DFETCHCONTENT_SOURCE_DIR_${upper}=$ROOT/work/$dep")
  done
  "$ROOT/scripts/configure_wsclean.sh" "$ROOT/work/wsclean" "$BUILD" \
    "${DEP_FLAGS[@]}" -DWSCLEAN_MX_METAL=ON -DWSCLEAN_MX_METAL_ARCHIVE=OFF
fi

"$CMAKE" --build "$BUILD" --target wsclean mx-peak-probe mx-vkfft-real-probe \
  mx-multiscale-batch-probe mx-prediction-gpu-probe mx-prediction-mock-probe \
  mx-prediction-cpu-probe -j "${JOBS:-$(sysctl -n hw.ncpu)}"
printf 'Active Metal targets built. Run scripts/test.sh %s for active gates.\n' "$BUILD"
printf 'Archived GPU gridding probe not run; use scripts/test_archived_metal.sh separately.\n'
