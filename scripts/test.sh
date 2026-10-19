#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Run Python harness tests and assertions against the real numerical libraries.
# Usage: scripts/test.sh [configured-build-directory]
# This does not download upstream integration-test measurement sets.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"
cd "$ROOT"
BUILD="${1:-$ROOT/build-mx}"
[ -f "$BUILD/CMakeCache.txt" ] || {
  printf 'Configure/build WSClean first; build directory not found: %s\n' "$BUILD" >&2
  exit 2
}
BUILD="$(cd "$BUILD" && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
CXX="${CXX:-/usr/bin/c++}"
# These tests compile work-tree headers/sources and link the selected build's
# libraries. Reject a reference or unrelated build before mixing those inputs.
python3 - "$ROOT" "$BUILD/CMakeCache.txt" <<'PY'
from pathlib import Path
import sys

root, cache_path = map(Path, sys.argv[1:])
cache = {}
for line in cache_path.read_text().splitlines():
    if line and not line.startswith(("#", "//")) and "=" in line:
        key, value = line.split("=", 1)
        cache[key.split(":", 1)[0]] = value
expected = {"CMAKE_HOME_DIRECTORY": root / "work/wsclean"}
for component in ("aocommon", "schaapcommon", "radler"):
    expected["FETCHCONTENT_SOURCE_DIR_" + component.upper()] = root / "work" / component
for key, path in expected.items():
    value = cache.get(key)
    if not value or Path(value).resolve() != path.resolve():
        print(f"Invalid source mapping: {key}={value!r}; expected {path}", file=sys.stderr)
        sys.exit(2)
PY
"$PYTHON" -m unittest discover -s tests -p 'test_*.py' -v
# A fresh build is required: an old binary/version string is not provenance.
"$CMAKE" --build "$BUILD" --target wsclean -j "${JOBS:-2}"
"$ROOT/scripts/check_headers.sh" "$BUILD"
OUT="$ROOT/bench/micro/bin"
mkdir -p "$OUT"
COMMON=(-std=c++20 -O2 -I"$DEPS_PREFIX/include" -I"$BREW/include"
        -I"$ROOT/work/aocommon/include" -I"$ROOT/work/schaapcommon/include"
        -I"$ROOT/work/radler/cpp")
"$CXX" "${COMMON[@]}" tests/numerical_regression.cpp \
  "$ROOT/work/radler/cpp/math/peak_finder.cc" \
  "$BUILD/_deps/schaapcommon-build/libschaapcommon.a" \
  -L"$BUILD" -lschaapthreading -L"$BREW/lib" -lfftw3f_threads -lfftw3f \
  -Wl,-rpath,"$BUILD" -o "$OUT/numerical_regression"
"$OUT/numerical_regression"
"$CXX" "${COMMON[@]}" -I"$ROOT/work/wsclean" tests/columnblock_regression.cpp \
  -L"$DEPS_PREFIX/lib" -lcasa_tables -lcasa_casa \
  -Wl,-rpath,"$DEPS_PREFIX/lib" -o "$OUT/columnblock_regression"
"$OUT/columnblock_regression"
"$CXX" "${COMMON[@]}" tests/peak_scratch_regression.cpp \
  "$BUILD/_deps/radler-build/cpp/libradler.a" \
  "$BUILD/_deps/schaapcommon-build/libschaapcommon.a" \
  -L"$BUILD" -lschaapthreading -L"$BREW/lib" -lfftw3f_threads -lfftw3f \
  -Wl,-rpath,"$BUILD" -o "$OUT/peak_scratch_regression"
"$OUT/peak_scratch_regression"
"$CXX" "${COMMON[@]}" tests/multiarray_regression.cpp -o "$OUT/multiarray_regression"
"$OUT/multiarray_regression"
"$CXX" "${COMMON[@]}" tests/median_edge_regression.cpp -o "$OUT/median_edge_regression"
"$OUT/median_edge_regression"
# The Metal probe exists only in a build configured with WSCLEAN_MX_METAL=ON;
# scripts/metal_build.sh produces one in build-mx-metal/. Its differential
# assertions (GPU gridding vs float64 CPU twin) run whenever it is present.
if [ -x "$BUILD/metal/mx-metal-probe" ]; then
  "$BUILD/metal/mx-metal-probe" --quiet
else
  printf 'Metal probe absent in %s (WSCLEAN_MX_METAL=OFF): use scripts/metal_build.sh.\n' \
    "$BUILD"
fi
"$CXX" "${COMMON[@]}" -I"$ROOT/work/wsclean" tests/inmemory_time_regression.cpp \
  "$BUILD/libwsclean.a" -L"$DEPS_PREFIX/lib" -lcasa_ms -lcasa_tables -lcasa_casa \
  -L"$BREW/lib" -lcfitsio -Wl,-rpath,"$DEPS_PREFIX/lib" \
  -o "$OUT/inmemory_time_regression"
"$OUT/inmemory_time_regression"
# The legacy programs below have differential assertions and nonzero failures.
"$CXX" "${COMMON[@]}" bench/micro/median_select.cpp -o "$OUT/median_select"
"$OUT/median_select"
"$CXX" "${COMMON[@]}" bench/micro/peak_simple.cpp \
  "$ROOT/work/radler/cpp/math/peak_finder.cc" -o "$OUT/peak_simple"
"$OUT/peak_simple"
printf 'Regression suite passed. Upstream fixture-dependent integration tests are separate.\n'
