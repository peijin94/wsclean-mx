#!/usr/bin/env bash
# Build the reference WSClean into build-upstream/: the pinned upstream commit
# plus build-only patches (patches/build/wsclean/<commit12>/), nothing else.
# The upstream/wsclean submodule itself is never modified; the reference is
# built from a disposable clone in deps/src/wsclean-ref.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"
source "$ROOT/scripts/lib.sh"

COMMIT="$(upstream_commit)"
SRC="$ROOT/deps/src/wsclean-ref"
BUILD="$ROOT/build-upstream"

checkout_patched wsclean "$ROOT/upstream/wsclean" "$COMMIT" "$SRC" \
  "$ROOT/patches/build/wsclean/${COMMIT:0:12}"
DEP_FLAGS=($("$ROOT/scripts/prepare_fetched_deps.sh"))

"$ROOT/scripts/configure_wsclean.sh" "$SRC" "$BUILD" "${DEP_FLAGS[@]}"
"$CMAKE" --build "$BUILD" -j "$(sysctl -n hw.ncpu)" --target wsclean
"$ROOT/scripts/check_headers.sh" "$BUILD"
"$BUILD/wsclean" -version | head -3
