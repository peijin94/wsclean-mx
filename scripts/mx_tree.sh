#!/usr/bin/env bash
# Manage the wsclean-mx development trees, one per patched repo:
#
#   work/<repo>   git clone of <repo> at the commit pinned by upstream
#     mx-base (tag)  = pinned commit + patches/build/<repo>/<commit12>/
#     mx (branch)    = mx-base + patches/mx/<repo>/*.patch
#
# repos: wsclean aocommon schaapcommon radler
#
#   scripts/mx_tree.sh init [--force] [repo...]   create trees from the patch set
#   scripts/mx_tree.sh export [repo...]           write mx-base..mx to patches/mx/<repo>/
#
# Develop by committing on branch mx in work/<repo>, then export. The patches
# in patches/mx/ are the source of truth that gets committed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/lib.sh"

ALL_REPOS=(wsclean aocommon schaapcommon radler)

repo_url() {
  case "$1" in
    wsclean) echo "$ROOT/upstream/wsclean" ;;
    aocommon) echo https://gitlab.com/aroffringa/aocommon.git ;;
    schaapcommon) echo https://git.astron.nl/RD/schaapcommon.git ;;
    radler) echo https://git.astron.nl/RD/radler.git ;;
    *) echo "unknown repo: $1" >&2; exit 2 ;;
  esac
}

repo_commit() {
  case "$1" in
    wsclean) upstream_commit ;;
    *) pinned_dep_commit "$(echo "$1" | tr '[:lower:]' '[:upper:]')_COMMIT" ;;
  esac
}

g() { git -C "$ROOT/work/$1" -c user.name=wsclean-mx -c user.email=wsclean-mx@localhost "${@:2}"; }

init_repo() {
  local repo="$1" force="$2" tree="$ROOT/work/$1"
  if [ -e "$tree" ]; then
    if [ "$force" != "--force" ]; then
      echo "work/$repo exists; use --force to recreate it (discards unexported work)" >&2
      return 1
    fi
    rm -rf "$tree"
  fi
  local commit; commit="$(repo_commit "$repo")"
  mkdir -p "$ROOT/work"
  git -c advice.detachedHead=false clone -q "$(repo_url "$repo")" "$tree"
  g "$repo" -c advice.detachedHead=false checkout -q -b mx "$commit"
  local p
  for p in "$ROOT"/patches/build/"$repo"/"${commit:0:12}"/*.patch; do
    [ -e "$p" ] && g "$repo" am -q "$p"
  done
  g "$repo" tag -f mx-base >/dev/null
  for p in "$ROOT"/patches/mx/"$repo"/*.patch; do
    [ -e "$p" ] && g "$repo" am -q "$p"
  done
  echo "work/$repo: $(g "$repo" rev-list --count mx-base..mx) mx patch(es) on mx-base (${commit:0:12})"
}

export_repo() {
  local repo="$1"
  [ -d "$ROOT/work/$repo" ] || return 0
  if [ -n "$(g "$repo" status --porcelain --untracked-files=no)" ]; then
    echo "work/$repo has uncommitted changes; commit them first" >&2
    return 1
  fi
  mkdir -p "$ROOT/patches/mx/$repo"
  rm -f "$ROOT"/patches/mx/"$repo"/*.patch
  g "$repo" format-patch -q --zero-commit --no-signature --no-stat \
    -o "$ROOT/patches/mx/$repo" mx-base..mx
  echo "patches/mx/$repo: $(ls "$ROOT/patches/mx/$repo" | grep -c '\.patch$' || true) patch(es)"
}

cmd="${1:-}"; shift || true
force=""
if [ "${1:-}" = "--force" ]; then force="--force"; shift; fi
repos=("$@"); [ ${#repos[@]} -gt 0 ] || repos=("${ALL_REPOS[@]}")

case "$cmd" in
  init)
    for r in "${repos[@]}"; do
      if [ -e "$ROOT/work/$r" ] && [ -z "$force" ]; then
        echo "work/$r: exists, kept"
      else
        init_repo "$r" "$force"
      fi
    done ;;
  export) for r in "${repos[@]}"; do export_repo "$r"; done ;;
  *) echo "usage: $0 init [--force] [repo...] | export [repo...]" >&2; exit 2 ;;
esac
