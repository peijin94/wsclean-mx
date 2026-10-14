# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Shared helpers. Source, don't execute.

# checkout_patched <name> <git-url-or-path> <commit> <dest> [patch-dir...]
# Puts <dest> at exactly <commit> (discarding local edits) and applies every
# *.patch from each patch dir in order. Patch dirs that don't exist are skipped.
checkout_patched() {
  local name="$1" url="$2" commit="$3" dest="$4"; shift 4
  [ -d "$dest/.git" ] || git clone -q "$url" "$dest"
  git -C "$dest" cat-file -e "$commit^{commit}" 2>/dev/null \
    || git -C "$dest" fetch -q origin "$commit"
  git -C "$dest" -c advice.detachedHead=false checkout -q -f "$commit"
  git -C "$dest" clean -qfdx
  local d p
  for d in "$@"; do
    for p in "$d"/*.patch; do
      [ -e "$p" ] || continue
      git -C "$dest" apply --index "$p"
      echo "applied ${p#$ROOT/} to $name" >&2
    done
  done
}

# Commit pinned by upstream's CMakeLists.txt for a FetchContent dependency.
pinned_dep_commit() {
  sed -n "s/^set($1 \([0-9a-f]*\))/\1/p" "$ROOT/upstream/wsclean/CMakeLists.txt"
}

upstream_commit() { git -C "$ROOT/upstream/wsclean" rev-parse HEAD; }
