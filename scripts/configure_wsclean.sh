#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# configure_wsclean.sh <src> <build> [extra cmake args...]
# Identical CMake configuration for the reference and the mx build, so that
# compiler flags never explain a difference between them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

SRC="$1"; BUILD="$2"; shift 2

# Apple clang searches /usr/local/include before any -isystem dir, and both
# /usr/local and Homebrew carry older casacore headers. -I beats both.
"$CMAKE" -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-I$DEPS_PREFIX/include" \
  -DCASACORE_ROOT_DIR="$DEPS_PREFIX" \
  -DCMAKE_PREFIX_PATH="$DEPS_PREFIX;$BREW" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DBUILD_TESTING=OFF \
  "$@"
