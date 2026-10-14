#!/usr/bin/env bash
# Sample-profile one native WSClean run with macOS `sample`.
#
#   bench/profile.sh <upstream|mx|snapshot> <tag> [wsclean args...]
#
# Writes bench/out/<tag>/<variant>-profile/{sample.txt,wsclean.log,top.txt}.
# top.txt lists the functions with the most samples at the top of the stack
# (self time), summed over all threads.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
variant="$1"; tag="$2"; shift 2
case "$variant" in
  upstream) bin="$ROOT/build-upstream/wsclean" ;;
  mx)       bin="$ROOT/build-mx/wsclean" ;;
  *)
    bin="$ROOT/bench/bin/$variant/wsclean"
    [ -x "$bin" ] || { echo "unknown variant: $variant" >&2; exit 2; } ;;
esac
out="$ROOT/bench/out/$tag/$variant-profile"
rm -rf "$out"; mkdir -p "$out/tmp"

cd "$ROOT"
"$bin" -no-update-model-required -temp-dir "$out/tmp" -name "$out/img" "$@" \
  > "$out/wsclean.log" 2>&1 &
pid=$!
sample "$pid" "${SAMPLE_SECONDS:-600}" 1 -mayDie -file "$out/sample.txt" >/dev/null 2>&1 || true
wait "$pid"
rm -rf "$out/tmp"

# "Sort by top of stack" section of the sample report = self time per function.
awk '/^Sort by top of stack/{f=1;next} f&&NF' "$out/sample.txt" | head -40 > "$out/top.txt"
tail -1 "$out/wsclean.log"
cat "$out/top.txt"
