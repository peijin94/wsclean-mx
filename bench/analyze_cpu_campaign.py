#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Validate and summarize the frozen CPU weighted-peak campaign.

Run from the repository: .venv/bin/python bench/analyze_cpu_campaign.py
Raw logs remain in bench/out; this writes compact, reproducible evidence/figures.
"""
import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.analyze_gpu_profile import parse_times
from bench.compare_fits import compare


def load(path):
    return json.loads(path.read_text())


def validated_runs(art, prefix):
    plan = load(art / (prefix + '-plan.json'))
    runs = load(art / (prefix + '-runs.json'))
    required = {'tag', 'variant', 'mode', 'repeat', 'size', 'threads',
                'profile', 'monitor', 'sample', 'warmup', 'common'}
    if not isinstance(plan, list) or not isinstance(runs, list) or not plan or len(plan) != len(runs):
        raise ValueError(f'{prefix}: invalid plan/receipt counts')
    for planned in plan:
        if (not isinstance(planned, dict) or not required <= planned.keys()
                or any(not isinstance(planned[k], str) or not planned[k] for k in ('tag', 'variant'))):
            raise ValueError(f'{prefix}: malformed run plan')
    if len({p['tag'] for p in plan}) != len(plan):
        raise ValueError(f'{prefix}: duplicate run tags')
    for planned, actual in zip(plan, runs):
        if not isinstance(actual, dict) or any(
                k not in actual or type(actual[k]) is not type(v) or actual[k] != v
                for k, v in planned.items()):
            raise ValueError(f'{prefix}: run identity mismatch: {planned!r}, {actual!r}')
        if type(actual.get('exit')) is not int or actual['exit'] != 0:
            raise ValueError(f'{prefix}: missing/failed run exit: {actual!r}')
        d = ROOT / 'bench/out' / actual['tag'] / actual['variant']
        time = (d / 'time.txt').read_text()
        try:
            actual['timing'] = parse_times(time, (d / 'wsclean.log').read_text())
        except (TypeError, ZeroDivisionError, OverflowError) as exc:
            raise ValueError(f'{actual["tag"]}: invalid run timings') from exc
        for name in ('wall_s', 'deconvolution_s', 'inversion_s', 'prediction_s', 'rss_bytes'):
            value = actual['timing'][name]
            if value is None or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{actual["tag"]}: invalid {name}: {value!r}')
        for name in ('user_s', 'system_s'):
            value = actual['timing'][name]
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'{actual["tag"]}: invalid {name}: {value!r}')
        for key, suffix in [('instructions', 'instructions retired'), ('cycles', 'cycles elapsed')]:
            m = re.search(r'(\d+)\s+' + suffix, time)
            if not m or int(m[1]) <= 0:
                raise ValueError(f'{actual["tag"]}: missing/invalid {key}')
            actual['timing'][key] = int(m[1])
    return runs


def gate(left, right, label, expected):
    a = {p.name: p for p in left.glob('*.fits')}
    b = {p.name: p for p in right.glob('*.fits')}
    required = {f'img-{name}.fits' for name in
                ('dirty', 'horizon-mask', 'image', 'model', 'psf', 'residual')}
    for directory, products in ((left, a), (right, b)):
        if products.keys() != required or any(not path.is_file() for path in products.values()):
            raise ValueError(f'{directory}: expected exactly {sorted(required)}, got {sorted(products)}')
    if expected not in ('T0', 'T2'):
        raise ValueError(f'unknown gate tier: {expected}')
    products = [compare(a[n], b[n]) for n in sorted(a)]
    for p in products:
        p['T0'] = not p.get('error') and not p.get('nan_mismatch', 1) and p['bitwise']
        p['T2'] = (not p.get('error') and not p.get('nan_mismatch', 1)
                   and p['rel_rms'] <= 1e-4 and p['rel_peak'] <= 1e-3)
    return dict(label=label, left=str(left.relative_to(ROOT)), right=str(right.relative_to(ROOT)),
                expected=expected, passed=all(p[expected] for p in products), products=products)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--art', type=Path, default=ROOT / 'bench/out/cpu-opt-20261022-2035')
    p.add_argument('--out', type=Path, default=ROOT / 'docs/bench/cpu-opt-20261022')
    args = p.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    candidate = validated_runs(args.art, 'candidate')
    baseline = validated_runs(args.art, 'baseline-profile')
    def directory(tag):
        r = next(r for r in candidate + baseline if r['tag'] == tag)
        return ROOT / 'bench/out' / tag / r['variant']
    gates = [gate(directory('cpuaudit-20261022-threads-r1-j1'),
                  directory('cpuopt-20261022-deterministic'), 'deterministic', 'T0')]
    for role in ('new', 'aa'):
        gates.append(gate(directory('cpuopt-20261022-common-base'),
                          directory('cpuopt-20261022-common-' + role), 'common-' + role, 'T0'))
    for size, repetitions, roles in [('3k', 3, ('new', 'aa')), ('4k', 2, ('new',))]:
        for rep in range(1, repetitions + 1):
            for role in roles:
                tag = f'cpuopt-20261022-{size}-r{rep}-'
                gates.append(gate(directory(tag + 'base'), directory(tag + role),
                                  f'{size}-r{rep}-{role}', 'T2'))
    micro = []
    for size in (3072, 4096):
        lines = (args.art / f'weighted-micro-{3 if size == 3072 else 4}k.log').read_text().splitlines()
        rows = [line.split(',') for line in lines if line.startswith('timing,')]
        summaries = [line for line in lines if line.startswith('weighted differential')]
        summary = (re.fullmatch(r'weighted differential checks=(\d+) failures=(\d+)', summaries[0])
                   if len(summaries) == 1 else None)
        if not summary or int(summary[1]) <= 0 or int(summary[2]) != 0:
            raise ValueError(f'{size}: missing/invalid/failed differential-check summary')
        expected_rows = {(size, masked, rep, role) for masked in (0, 1)
                         for rep in range(9) for role in (0, 1)}
        seen = set()
        for row in rows:
            if len(row) != 6:
                raise ValueError(f'{size}: malformed micro timing row: {row!r}')
            identity = tuple(map(int, row[1:5]))
            duration = float(row[5])
            if identity not in expected_rows or identity in seen:
                raise ValueError(f'{size}: unexpected/duplicate micro identity: {identity!r}')
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(f'{size}: invalid micro duration: {duration!r}')
            seen.add(identity)
        if seen != expected_rows:
            raise ValueError(f'{size}: incomplete micro timings: {len(seen)}/36')
        for masked in (0, 1):
            values = {role: [float(a[5]) for a in rows
                            if int(a[2]) == masked and int(a[4]) == role and int(a[3]) != 0]
                      for role in (0, 1)}
            if any(len(v) != 8 for v in values.values()):
                raise ValueError(f'{size}/{masked}: expected eight measured timings per role')
            micro.append(dict(size=size, masked=bool(masked), samples_ms=values,
                              baseline_ms=statistics.median(values[0]),
                              candidate_ms=statistics.median(values[1]),
                              speedup=statistics.median(values[0]) / statistics.median(values[1])))
    stats = []
    for size in (3072, 4096):
        for role in ('base', 'new', 'aa'):
            rows = [r['timing'] for r in candidate if r['size'] == size and r['role'] == role
                    and '-r' in r['tag'] and not r['common'] and not r['warmup']]
            if rows:
                stats.append(dict(size=size, role=role, n=len(rows), metrics={
                    key: dict(median=statistics.median(r[key] for r in rows),
                              min=min(r[key] for r in rows), max=max(r[key] for r in rows))
                    for key in rows[0]}))
    summary = dict(baseline=baseline, candidate=candidate, statistics=stats, micro=micro,
                   gates=gates, profiles=load(args.art / 'sample-summary.json'),
                   provenance=load(args.art / 'provenance.json'))
    (args.out / 'results.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    print('Gates:', [(g['label'], g['passed']) for g in gates])
    print('Micro:', micro)
    print('Statistics:', stats)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    colors = {'base': '#4c78a8', 'new': '#f58518', 'aa': '#72b7b2'}
    for ax, metric, title in [(axes[0], 'wall_s', 'Whole imaging'),
                              (axes[1], 'deconvolution_s', 'Deconvolution')]:
        for i, size in enumerate((3072, 4096)):
            for j, role in enumerate(('base', 'new', 'aa')):
                vals = [r['timing'][metric] for r in candidate if r['size'] == size
                        and r['role'] == role and '-r' in r['tag'] and not r['common']]
                if vals:
                    x = i + (j - 1) * .23
                    ax.scatter([x] * len(vals), vals, color=colors[role], s=28,
                               label=role if i == 0 else None)
                    ax.plot([x - .07, x + .07], [statistics.median(vals)] * 2, color='black')
        ax.set(xticks=[0, 1], xticklabels=['3072²', '4096²'], ylabel='Seconds', title=title)
        ax.grid(axis='y', alpha=.2); ax.legend()
    for i, row in enumerate(micro):
        axes[2].bar(i - .18, row['baseline_ms'], .36, color=colors['base'], label='before' if i == 0 else None)
        axes[2].bar(i + .18, row['candidate_ms'], .36, color=colors['new'], label='after' if i == 0 else None)
    axes[2].set(xticks=range(4), xticklabels=['3K\nplain', '3K\nmask', '4K\nplain', '4K\nmask'],
                ylabel='Milliseconds', title='Weighted peak microbenchmark')
    axes[2].legend(); axes[2].grid(axis='y', alpha=.2)
    fig.suptitle('CPU weighted-peak optimization: all timed samples; horizontal marks = medians')
    fig.savefig(args.out / 'performance.png', dpi=160); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for threads in (1, 4, 8):
        vals = [r['timing']['wall_s'] for r in baseline if r['threads'] == threads
                and not r['warmup'] and not r['sample']]
        if len(vals) != 2:
            raise ValueError(f'{threads} threads: expected two baseline samples, got {len(vals)}')
        axes[0].scatter([threads] * len(vals), vals, color=colors['base'])
        axes[0].plot([threads-.2, threads+.2], [statistics.median(vals)]*2, color='black')
    axes[0].set(xticks=[1, 4, 8], xlabel='Requested CPU threads', ylabel='Seconds', title='3K reverse-order thread sweeps')
    reference = [r for r in candidate if '-3k-r' in r['tag'] and r['role'] == 'base']
    keys = ['inversion_s', 'prediction_s', 'deconvolution_s', 'other_s']
    axes[1].bar([k.removesuffix('_s') for k in keys],
                [statistics.median(r['timing'][k] for r in reference) for k in keys], color=colors['base'])
    axes[1].set(ylabel='Seconds', title='3K baseline median stage times (unprofiled)')
    fig.savefig(args.out / 'cpu-breakdown.png', dpi=160); plt.close(fig)
    return 0 if all(g['passed'] for g in gates) else 1


if __name__ == '__main__':
    raise SystemExit(main())
