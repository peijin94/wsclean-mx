#!/usr/bin/env bash
# Freeze a build into bench/bin/<name>/ so it can be benchmarked as a variant
# after the build directory has moved on.
#
#   bench/snapshot.sh <build-dir> <name>
#
# The wsclean binary loads libschaapthreading.dylib through an rpath that
# points at its build directory; the snapshot carries its own copy instead.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
build="$(cd "$1" && pwd)"; name="$2"
out="$ROOT/bench/bin/$name"
rm -rf "$out"; mkdir -p "$out"
cp "$build/wsclean" "$build/libschaapthreading.dylib" "$out/"
install_name_tool -rpath "$build" @executable_path "$out/wsclean" 2>/dev/null
codesign -f -s - "$out/wsclean" "$out/libschaapthreading.dylib" 2>/dev/null
"$out/wsclean" -version | grep -m1 "WSClean version"
echo "snapshot $name <- $build"
