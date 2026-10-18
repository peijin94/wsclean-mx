#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Build the FIXED reference WSClean into build-reffix/: the pinned upstream
# commit plus the build-only patches (patches/build/wsclean/<commit12>/) plus
# ONLY patches/mx/wsclean/0001 (the uninitialized-padding fix), nothing else.
#
# This is the scientific comparison baseline: plain upstream produces corrupt
# 2048² images on macOS under clang -ffast-math (see benchmark.md), and the
# optimization patches must be compared against the repaired upstream, not
# against a broken one or against the whole mx stack.
#
# The upstream/wsclean submodule is never modified; the reference is built from
# a disposable clone in deps/src/wsclean-ref-fix.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"
source "$ROOT/scripts/lib.sh"

COMMIT="$(upstream_commit)"
SRC="$ROOT/deps/src/wsclean-ref-fix"
BUILD="$ROOT/build-reffix"
PATCH_DIR="$ROOT/patches/build/wsclean/${COMMIT:0:12}"

# Exactly one padding-fix patch: a glob that matches zero or several files means
# the patch set changed and this builder must be revisited, not guessed at.
fix_patches=("$ROOT"/patches/mx/wsclean/0001-*.patch)
[ "${#fix_patches[@]}" -eq 1 ] && [ -f "${fix_patches[0]}" ] \
  || { echo "expected exactly one patches/mx/wsclean/0001-*.patch, found ${#fix_patches[@]}" >&2; exit 2; }

checkout_patched wsclean "$ROOT/upstream/wsclean" "$COMMIT" "$SRC" "$PATCH_DIR"
git -C "$SRC" apply --index "${fix_patches[0]}"
echo "applied ${fix_patches[0]#$ROOT/} to reffix" >&2

DEP_FLAGS=($("$ROOT/scripts/prepare_fetched_deps.sh"))
"$ROOT/scripts/configure_wsclean.sh" "$SRC" "$BUILD" "${DEP_FLAGS[@]}"
"$CMAKE" --build "$BUILD" -j "${JOBS:-4}" --target wsclean
"$ROOT/scripts/check_headers.sh" "$BUILD"
"$BUILD/wsclean" -version | head -3

# Provenance travels with the build so a comparison can name its reference.
python3 - "$ROOT" "$SRC" "$BUILD" "$PATCH_DIR" "${fix_patches[0]}" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path

root, src, build, patch_dir, fix_patch = map(Path, sys.argv[1:])
def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def output(*command):
    return subprocess.check_output(list(map(str, command)), text=True).strip()
def try_output(*command):
    try:
        return output(*command)
    except (OSError, subprocess.CalledProcessError):
        return 'unavailable'

patches = sorted(patch_dir.glob('*.patch')) + [fix_patch]
manifest = {
    'role': 'fixed reference: pinned upstream + build patches + wsclean/0001 only',
    'upstream_commit': output('git', '-C', root / 'upstream/wsclean', 'rev-parse', 'HEAD'),
    'underlying_commit': output('git', '-C', src, 'rev-parse', 'HEAD'),
    'submodule_clean': not output('git', '-C', root / 'upstream/wsclean', 'status', '--porcelain'),
    'patches': {str(p.relative_to(root)): sha256(p) for p in patches},
    'binary': str(build / 'wsclean'),
    'binary_sha256': sha256(build / 'wsclean'),
    'version_output': output(build / 'wsclean', '-version'),
    'linked_libraries': output('otool', '-L', build / 'wsclean'),
    'compiler': try_output('clang++', '--version').splitlines()[0],
    'work_tree_heads': {name: output('git', '-C', root / 'work' / name, 'rev-parse', 'HEAD')
                        for name in ('wsclean', 'aocommon', 'schaapcommon', 'radler')},
}
(build / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('wrote', build / 'provenance.json')
print('binary sha256', manifest['binary_sha256'])
PY
