#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Resolve active MX binaries strictly; retain explicitly named legacy snapshots."""
from pathlib import Path
import argparse
import os
import sys


def require_binary(path):
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'unknown or unavailable variant executable: {path}')
    return path


def mx_binary(build):
    return require_binary(Path(build) / 'wsclean-mx')


def snapshot_binary(directory):
    directory = Path(directory)
    preferred = directory / 'wsclean-mx'
    if preferred.exists() or preferred.is_symlink():
        return require_binary(preferred)
    return require_binary(directory / 'wsclean')


def build_binary(build):
    build = Path(build)
    cache_path = build / 'CMakeCache.txt'
    cache = {}
    if cache_path.is_file():
        for line in cache_path.read_text().splitlines():
            if line and not line.startswith(('#', '//')) and '=' in line:
                key, value = line.split('=', 1)
                cache[key.split(':', 1)[0]] = value
    mx_source = Path(__file__).resolve().parents[1] / 'work/wsclean'
    source = cache.get('CMAKE_HOME_DIRECTORY')
    if (build.name.startswith('build-mx') or 'WSCLEAN_MX_VERSION' in cache
            or (source and Path(source).resolve() == mx_source)):
        return mx_binary(build)
    return snapshot_binary(build)


def resolve_variant(root, variant):
    root = Path(root)
    if variant == 'mx':
        return mx_binary(root / 'build-mx')
    if variant == 'upstream':
        return require_binary(root / 'build-upstream/wsclean')
    return snapshot_binary(root / 'bench/bin' / variant)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', nargs='?')
    parser.add_argument('--build', type=Path)
    args = parser.parse_args()
    if (args.build is None) == (args.variant is None):
        parser.error('provide a variant or --build DIRECTORY')
    try:
        print(build_binary(args.build) if args.build is not None else
              resolve_variant(Path(__file__).resolve().parents[1], args.variant))
    except (ValueError, OSError) as error:
        sys.exit(str(error))
