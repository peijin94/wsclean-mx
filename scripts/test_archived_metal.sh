#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Explicit runner for retired, scientifically failing GPU gridding experiments.
# Usage: scripts/test_archived_metal.sh [configured-build-directory] [probe args...]
# Configure separately with WSCLEAN_MX_METAL=ON and WSCLEAN_MX_METAL_ARCHIVE=ON.
# A failed/missing archive configuration is an error, never a passing skip.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${1:-$ROOT/build-mx-metal}"
if [ "$#" -gt 0 ]; then shift; fi
for option in WSCLEAN_MX_METAL WSCLEAN_MX_METAL_ARCHIVE; do
  value="$(sed -n "s/^${option}:BOOL=//p" "$BUILD/CMakeCache.txt")"
  case "$value" in
    ON|TRUE|YES|1|Y) ;;
    *) printf 'Archive requires %s=ON in %s/CMakeCache.txt; refusing to run.\n' \
         "$option" "$BUILD" >&2; exit 2 ;;
  esac
done
BUILD="$(cd "$BUILD" && pwd)"
source "$ROOT/scripts/env.sh"
"$CMAKE" --build "$BUILD" --target mx-metal-probe -j "${JOBS:-2}"
printf 'Running retired GPU gridding probe; its failure status is preserved.\n'
exec "$BUILD/metal/mx-metal-probe" "$@"
