#!/usr/bin/env bash
# Build wsclean-mx from work/wsclean-mx into build-mx/, with exactly the same
# dependencies and CMake configuration as the reference build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

SRC="$ROOT/work/wsclean-mx"
BUILD="$ROOT/build-mx"

[ -d "$SRC" ] || "$ROOT/scripts/mx_tree.sh" init
DEP_FLAGS=($("$ROOT/scripts/prepare_fetched_deps.sh"))

"$ROOT/scripts/configure_wsclean.sh" "$SRC" "$BUILD" "${DEP_FLAGS[@]}"
"$CMAKE" --build "$BUILD" -j "$(sysctl -n hw.ncpu)" --target wsclean
"$ROOT/scripts/check_headers.sh" "$BUILD"
"$BUILD/wsclean" -version | head -3
