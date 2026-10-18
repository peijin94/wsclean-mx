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

# SHA-256 of a file, for identity checks on frozen executables.
bench_sha256() {
  python3 - "$1" <<'PYCODE'
import hashlib, sys
from pathlib import Path
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PYCODE
}

# Optional hardware counters from /usr/bin/time -lp, printed as
# "<instructions_G> <cycles_G>" so a wall-clock difference can be classified:
# equal instruction counts with a large cycle increase is a host stall mode, not
# a code cost. Prints "na na" where the platform's time command lacks them; values
# are never invented.
bench_counters() {
  python3 - "$1" <<'PYCODE'
import re, sys
from pathlib import Path
try:
    text = Path(sys.argv[1]).read_text()
except OSError:
    sys.exit(f"bench: missing timing file: {sys.argv[1]}")
def value(label):
    # Horizontal whitespace only, so a split record cannot be reassembled across
    # lines, and a labelled suffix ("... retired per second") does not match.
    matches = re.findall(rf"^[ \t]*(\d+)[ \t]+{label}[ \t]*$", text, re.M)
    if not matches:
        return "na"
    if len(matches) > 1:
        sys.exit(f"bench: ambiguous counter records for {label}: {sys.argv[1]}")
    return f"{int(matches[0]) / 1e9:.4f}"
print(value("instructions retired"), value("cycles elapsed"))
PYCODE
}

bench_wall_time() {
  python3 - "$1" <<'PYCODE'
import math, re, sys
from pathlib import Path
try:
    text = Path(sys.argv[1]).read_text()
except OSError:
    sys.exit(f"bench: missing wall timing: {sys.argv[1]}")
# A truncated or partially malformed timing file (a failed or killed run) must
# not pass as a record: all three of real/user/sys are required, each exactly
# once, each with a fractional part and a finite value.
records = {}
for line in text.splitlines():
    match = re.fullmatch(r"(real|user|sys)[ \t]+([0-9]+\.[0-9]+)[ \t]*", line)
    if match:
        records.setdefault(match.group(1), []).append(match.group(2))
if (sorted(records) != ["real", "sys", "user"]
        or any(len(values) != 1 for values in records.values())):
    sys.exit(f"bench: missing or malformed wall timing: {sys.argv[1]}")
if not all(math.isfinite(float(values[0])) for values in records.values()):
    sys.exit(f"bench: nonfinite wall timing: {sys.argv[1]}")
print(records["real"][0])
PYCODE
}
