#!/usr/bin/env python3
"""Evaluate source-gate families with cached metrics, preserving original verdicts.

Config: {"groups": [{"name": "group", "references": ["dir", ...],
                     "candidates": {"label": "dir", ...}}]}
All files must remain unchanged throughout. Output directory must be fresh.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import sys

if __package__:
    from . import compare_sources
else:
    import compare_sources


def run(config, output):
    groups = config['groups']
    names = set()
    output_stems = set()
    expected = 0
    for group in groups:
        name = group['name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or name in names:
            raise ValueError('invalid or duplicate group name')
        names.add(name)
        if len(group['references']) < 2 or not group['candidates']:
            raise ValueError('need at least two references and one candidate')
        inventory = None
        for directory in [*group['references'], *group['candidates'].values()]:
            current = set(compare_sources.product_files(Path(directory)))
            if not current or (inventory is not None and inventory != current):
                raise ValueError('incomplete product inventory')
            inventory = current
        for label in group['candidates']:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', label):
                raise ValueError('invalid candidate label')
            stem = name + '-' + label
            if stem in output_stems:
                raise ValueError(f'duplicate generated output stem: {stem}')
            output_stems.add(stem)
        expected += len(group['candidates'])
    output.mkdir(parents=True, exist_ok=False)
    cache, stamps = {}, {}
    original_loader, original_argv = compare_sources.load_metrics, sys.argv
    def stamp(path):
        st = path.stat()
        return st.st_size, st.st_mtime_ns, st.st_ino
    def cached(path):
        path = Path(path).resolve()
        now = stamp(path)
        if path in stamps and stamps[path] != now:
            raise ValueError(f'input changed during evaluation: {path}')
        if path not in cache:
            cache[path] = original_loader(path)
            if stamp(path) != now:
                raise ValueError(f'input changed during read: {path}')
            stamps[path] = now
        return cache[path]
    records = []
    try:
        compare_sources.load_metrics = cached
        for group in groups:
            for label, directory in group['candidates'].items():
                stem = group['name'] + '-' + label
                report = output / (stem + '.json')
                sys.argv = ['compare_sources.py', '--candidate', directory,
                            '--criterion', 'max', '--json', str(report), *group['references']]
                log = io.StringIO()
                with contextlib.redirect_stdout(log):
                    rc = compare_sources.main()
                (output / (stem + '.log')).write_text(log.getvalue())
                records.append({'group': group['name'], 'candidate': label,
                                'directory': directory, 'exit': rc, 'report': str(report)})
                print(stem, 'PASS' if rc == 0 else 'FAIL', flush=True)
        for path, before in stamps.items():
            if stamp(path) != before:
                raise ValueError(f'input changed during evaluation: {path}')
    finally:
        compare_sources.load_metrics, sys.argv = original_loader, original_argv
    assert len(records) == expected
    summary = {'evaluations': expected, 'unique_products_read': len(cache),
               'comparator_sha256': hashlib.sha256(Path(compare_sources.__file__).read_bytes()).hexdigest(),
               'records': records}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return 1 if any(r['exit'] for r in records) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    sys.exit(run(json.loads(args.config.read_text()), args.output))
