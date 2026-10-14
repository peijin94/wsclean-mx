#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# check_headers.sh <build>
# Fail if any object in the build was compiled against casacore headers other
# than the ones in deps/install (e.g. /usr/local or Homebrew copies).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

bad=$(cd "$1" && ninja -t deps | grep "/include/casacore/" \
  | grep -v "^ *$DEPS_PREFIX/" | sort -u | head -5 || true)
if [ -n "$bad" ]; then
  echo "ERROR: build used foreign casacore headers:" >&2
  echo "$bad" >&2
  exit 1
fi
echo "headers OK: all casacore headers from $DEPS_PREFIX"
