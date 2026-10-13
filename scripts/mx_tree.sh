#!/usr/bin/env bash
# Manage the wsclean-mx development tree (work/wsclean-mx), a git clone of the
# pinned upstream commit with the patch set applied as commits:
#
#   mx-base (tag)  = pinned upstream + patches/build/wsclean/<commit12>/
#   mx (branch)    = mx-base + patches/mx/*.patch
#
#   scripts/mx_tree.sh init [--force]   create the tree from the patch set
#   scripts/mx_tree.sh export           write mx-base..mx to patches/mx/
#
# Develop by committing on branch mx in work/wsclean-mx, then export. The
# patches in patches/mx/ are the source of truth that gets committed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/lib.sh"

TREE="$ROOT/work/wsclean-mx"
GIT=(git -C "$TREE" -c user.name=wsclean-mx -c user.email=wsclean-mx@localhost)

init() {
  if [ -e "$TREE" ]; then
    if [ "${1:-}" != "--force" ]; then
      echo "$TREE exists; use --force to recreate it (discards unexported work)" >&2
      exit 1
    fi
    rm -rf "$TREE"
  fi
  local commit; commit="$(upstream_commit)"
  mkdir -p "$ROOT/work"
  git clone -q "$ROOT/upstream/wsclean" "$TREE"
  "${GIT[@]}" checkout -q -b mx "$commit"
  local p
  for p in "$ROOT"/patches/build/wsclean/"${commit:0:12}"/*.patch; do
    [ -e "$p" ] && "${GIT[@]}" am -q "$p"
  done
  "${GIT[@]}" tag -f mx-base >/dev/null
  for p in "$ROOT"/patches/mx/*.patch; do
    [ -e "$p" ] && "${GIT[@]}" am -q "$p"
  done
  echo "work/wsclean-mx: $("${GIT[@]}" rev-list --count mx-base..mx) mx patch(es) on mx-base"
}

export_patches() {
  if [ -n "$("${GIT[@]}" status --porcelain)" ]; then
    echo "work/wsclean-mx has uncommitted changes; commit them first" >&2
    exit 1
  fi
  mkdir -p "$ROOT/patches/mx"
  rm -f "$ROOT"/patches/mx/*.patch
  "${GIT[@]}" format-patch -q --zero-commit --no-signature --no-stat \
    -o "$ROOT/patches/mx" mx-base..mx
  ls "$ROOT/patches/mx"
}

case "${1:-}" in
  init) init "${2:-}" ;;
  export) export_patches ;;
  *) echo "usage: $0 init [--force] | export" >&2; exit 2 ;;
esac
