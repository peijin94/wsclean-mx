#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Freeze a build into bench/bin/<name>/ so it can be benchmarked as a variant
# after the build directory has moved on.
#
#   bench/snapshot.sh <build-dir> <name>
#
# The wsclean binary loads libschaapthreading.dylib through an rpath that
# points at its build directory; the snapshot carries its own copy instead.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/bench/common.sh"
[ "$#" -ge 2 ] || bench_die "usage: bench/snapshot.sh <build-dir> <name>"
name="$2"
bench_slug "$name" name
build="$(cd "$1" && pwd)"
out="$ROOT/bench/bin/$name"
bench_output "$out"
mkdir -p "$(dirname "$out")"
mkdir "$out" || bench_die "output already exists or cannot be created: $out"
cp "$build/wsclean" "$build/libschaapthreading.dylib" "$out/"
install_name_tool -rpath "$build" @executable_path "$out/wsclean" 2>/dev/null
codesign -f -s - "$out/wsclean" "$out/libschaapthreading.dylib" 2>/dev/null
"$out/wsclean" -version | grep -m1 "WSClean version"
echo "snapshot $name <- $build"
