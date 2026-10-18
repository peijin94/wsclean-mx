#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Shared validation for the benchmark shell entry points.
bench_die() { echo "bench: $*" >&2; exit 2; }
bench_slug() {
  [[ "$1" =~ ^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$ ]] || bench_die "invalid $2: $1"
}

bench_variant() {
  local binary
  bench_slug "$1" variant
  case "$1" in
    linc)
      command -v container >/dev/null || bench_die "unavailable variant: linc (container not found)"
      return ;;
    mx|upstream) binary="$ROOT/build-$1/wsclean" ;;
    *) binary="$ROOT/bench/bin/$1/wsclean" ;;
  esac
  [ -f "$binary" ] && [ -x "$binary" ] || bench_die "unknown or unavailable variant: $1"
}

# Deny confirmed MS writers and overrides of runner-owned paths. This is not
# an allowlist or a guarantee that every other WSClean argument is read-only.
bench_args() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      -predict|--predict|-update-model-required|--update-model-required|\
      -no-reorder|--no-reorder|\
      -name|--name|-temp-dir|--temp-dir|-store-imaging-weights|--store-imaging-weights)
        bench_die "forbidden WSClean option: $arg" ;;
    esac
  done
}

# Check every component below the physical repository root, including dangling
# symlinks. Only generated paths are accepted; never resolve through a symlink.
bench_output() {
  local path="$1" relative cursor="$ROOT" part
  local -a parts
  [[ "$path" == "$ROOT/"* ]] || bench_die "unsafe output path: $path"
  relative="${path#"$ROOT/"}"
  IFS=/ read -r -a parts <<< "$relative"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. ]] || bench_die "unsafe output path: $path"
    cursor="$cursor/$part"
    [ ! -L "$cursor" ] || bench_die "symlink output path: $cursor"
    if [ "$cursor" != "$path" ] && [ -e "$cursor" ] && [ ! -d "$cursor" ]; then
      bench_die "unsafe output ancestor: $cursor"
    fi
  done
  [ ! -e "$path" ] || bench_die "output already exists: $path"
}

bench_wall_time() {
  python3 - "$1" <<'PYCODE'
import math, re, sys
from pathlib import Path
try:
    lines = [line for line in Path(sys.argv[1]).read_text().splitlines() if line.startswith("real")]
except OSError:
    sys.exit(f"bench: missing wall timing: {sys.argv[1]}")
match = re.fullmatch(r"real\s+([0-9]+(?:\.[0-9]+)?)\s*", lines[0]) if len(lines) == 1 else None
if not match or not math.isfinite(float(match[1])):
    sys.exit(f"bench: missing or malformed wall timing: {sys.argv[1]}")
print(match[1])
PYCODE
}
