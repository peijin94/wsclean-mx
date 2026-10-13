#!/usr/bin/env bash
# Build wsclean-mx from the work/<repo> dev trees into build-mx/, with the same
# CMake configuration as the reference build. Missing trees are created from
# the patch set first.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

BUILD="$ROOT/build-mx"

"$ROOT/scripts/mx_tree.sh" init
DEP_FLAGS=()
for dep in aocommon schaapcommon radler; do
  upper="$(echo "$dep" | tr '[:lower:]' '[:upper:]')"
  DEP_FLAGS+=("-DFETCHCONTENT_SOURCE_DIR_${upper}=$ROOT/work/$dep")
done

"$ROOT/scripts/configure_wsclean.sh" "$ROOT/work/wsclean" "$BUILD" "${DEP_FLAGS[@]}"
"$CMAKE" --build "$BUILD" -j "$(sysctl -n hw.ncpu)" --target wsclean
"$ROOT/scripts/check_headers.sh" "$BUILD"
"$BUILD/wsclean" -version | head -3
