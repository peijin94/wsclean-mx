#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Check out the FetchContent dependencies of upstream WSClean at the commits
# pinned in upstream/wsclean/CMakeLists.txt, and apply build-only patches from
# patches/build/<dep>/<commit12>/. Prints the -DFETCHCONTENT_SOURCE_DIR_* flags.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/lib.sh"

prepare() {
  local name="$1" url="$2" commit; commit="$(pinned_dep_commit "$3")"
  checkout_patched "$name" "$url" "$commit" "$ROOT/deps/src/$name" \
    "$ROOT/patches/build/$name/${commit:0:12}"
  local upper; upper="$(echo "$name" | tr '[:lower:]' '[:upper:]')"
  echo "-DFETCHCONTENT_SOURCE_DIR_${upper}=$ROOT/deps/src/$name"
}

prepare aocommon     https://gitlab.com/aroffringa/aocommon.git AOCOMMON_COMMIT
prepare schaapcommon https://git.astron.nl/RD/schaapcommon.git  SCHAAPCOMMON_COMMIT
prepare radler       https://git.astron.nl/RD/radler.git        RADLER_COMMIT
