#!/usr/bin/env python3
"""Plan the bench/out cleanup: keep every run referenced by tracked files.

A run directory is kept when
  * it belongs to the current gate evidence (the science-gate families, the
    audit products, the throttle/continuation evidence), or
  * its name appears in any tracked file (bench/, scripts/, tests/, docs/,
    *.md) -- so figures and documents that cite a run stay reproducible.

Everything else is a superseded intermediate run: planned for removal, with a
manifest written first. Usage:
  .venv/bin/python bench/trim_plan.py            # dry run, prints the plan
  .venv/bin/python bench/trim_plan.py --execute  # remove planned entries
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path('/Users/peijinz/dev/wsclean-mx')
OUT = ROOT / 'bench/out'
KEEP_PREFIXES = ('envelope18-', 'lofar18-', 'lofarS-', 'bisect-deep-', 'audit-20261017-',
                 'throttle-20261018', 'smoke-sweep-check', 'reffix-verify-', 'continue-20261017')
TRACKED_SUFFIXES = ('.py', '.sh', '.md', '.cpp', '.txt', '.tsv')


def tracked_text():
    files = []
    for directory in ('bench', 'scripts', 'tests', 'docs'):
        for path in (ROOT / directory).rglob('*'):
            # Run outputs and snapshots must not cite themselves: only code and
            # documents count as references.
            if any(part in ('out', 'bin', 'micro') for part in
                   path.relative_to(ROOT / directory).parts[:1]):
                continue
            if path.is_file() and path.suffix in TRACKED_SUFFIXES:
                files.append(path)
    files.extend(p for p in ROOT.glob('*.md'))
    files.extend((ROOT / 'NOTICE.md', ROOT / 'README.md'))
    text = {}
    for path in sorted(set(files)):
        try:
            text[path] = path.read_text(errors='ignore')
        except OSError:
            continue
    return text


def human(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024


def recursive_size(path):
    if not path.is_dir():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def citation(name, text, minimum=3):
    """The literal string that cites this entry in tracked code or documents, if any.

    Names are cited in several shapes: the directory itself ("d4k-n2k-r1"), the
    tag a figure spells out ("d4k-n2k"), a formatted repeat ("p1-r{i}" cites
    "p1-r1" through "p1-r"), or a short base tag ("b4k"). Every candidate of at
    least `minimum` characters is checked; the longest match wins.
    """
    candidates = [name, name.rstrip('-0123456789').rstrip('-')]
    parts = name.split('-')
    candidates.extend('-'.join(parts[:length]) for length in range(len(parts) - 1, 0, -1))
    for candidate in sorted(set(candidates), key=len, reverse=True):
        if len(candidate) >= minimum and candidate in text:
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()

    references = tracked_text()
    entries = sorted(p for p in OUT.iterdir())
    keep, remove = [], []
    for path in entries:
        name = path.name
        if name.startswith(KEEP_PREFIXES):
            keep.append((path, 'current gate evidence'))
            continue
        if not path.is_dir():
            # Loose result tables, mode files and manifests are tiny and are the
            # primary evidence for figures: never removal candidates.
            keep.append((path, 'result table or mode file'))
            continue
        cited = [ref.relative_to(ROOT) for ref, text in references.items()
                 if citation(name, text)]
        if cited:
            keep.append((path, f'cited by {cited[0]}' + (f' (+{len(cited) - 1})' if len(cited) > 1 else '')))
        else:
            remove.append(path)

    total = sum(recursive_size(path) for path in entries)
    keep_size = sum(recursive_size(path) for path, _ in keep)
    remove_size = sum(recursive_size(path) for path in remove)
    print(f'{len(keep)} kept ({human(keep_size)} of {human(total)}), '
          f'{len(remove)} to remove ({human(remove_size)})')
    print()
    print('KEEP:')
    for path, why in keep:
        print(f'  {path.name:<38} {why}')
    print()
    print('REMOVE:')
    for path in remove:
        files = sum(1 for _ in path.rglob('*') if _.is_file()) if path.is_dir() else 1
        print(f'  {path.name:<38} {human(recursive_size(path)):>10}  {files} files')

    if not args.execute:
        print('\ndry run: nothing removed')
        return 0
    manifest = ROOT / 'docs/trim-2026-10-18.md'
    lines = ['# bench/out cleanup, 2026-10-18', '',
             f'Removed {len(remove)} superseded run directories ({human(remove_size)}), keeping every',
             'run that a tracked file cites plus the current gate evidence. Frozen snapshot',
             'binaries under `bench/bin/` and all patches/sources are untouched.', '',
             '| removed run | size | files |', '|---|---:|---:|']
    for path in remove:
        files = sum(1 for _ in path.rglob('*') if _.is_file()) if path.is_dir() else 1
        lines.append(f'| `{path.name}` | {human(recursive_size(path))} | {files} |')
    manifest.write_text('\n'.join(lines) + '\n')
    print(f'\nwrote {manifest.relative_to(ROOT)}')
    for path in remove:
        subprocess.run(['/opt/homebrew/bin/cmake', '-E', 'remove_directory', str(path)], check=True)
        assert not path.exists(), path
    print(f'removed {len(remove)} directories')
    return 0


if __name__ == '__main__':
    sys.exit(main())
