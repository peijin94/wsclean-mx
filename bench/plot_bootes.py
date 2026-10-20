#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Bootes-field comparison figures: restored MFS, mx-ref difference, timing.

Reads bench/out/v010-bootes2-{ref,mx}/ (mx build = v010-rc1 in ...-mx,
reference = reffix-verified in ...-ref). Writes docs/bench/v010-bootes-*.png.

Run: .venv/bin/python bench/plot_bootes.py
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from bench import compare_sources as cs
from bench.plot_science_gates import difference_figure

OUT = ROOT / 'docs/bench'
REF = ROOT / 'bench/out/v010-bootes2-ref/reffix-verified'
MX = ROOT / 'bench/out/v010-bootes2-mx/v010-rc1'

STAGE_RE = re.compile(
    r'Inversion:\s*(\d+):(\d+):([\d.]+),\s*prediction:\s*(\d+):(\d+):([\d.]+),\s*'
    r'deconvolution:\s*(\d+):(\d+):([\d.]+)')


def stage_seconds(log_path):
    match = STAGE_RE.search(Path(log_path).read_text(errors='ignore'))
    if not match:
        return None
    g = [float(v) for v in match.groups()]
    return (g[0] * 3600 + g[1] * 60 + g[2], g[3] * 3600 + g[4] * 60 + g[5],
            g[6] * 3600 + g[7] * 60 + g[8])


def wall_seconds(run_dir):
    for line in Path(run_dir, 'time.txt').read_text(errors='ignore').splitlines():
        if line.startswith('real'):
            return float(line.split()[1])
    return float('nan')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for product in ('img-MFS-image.fits', 'img-MFS-dirty.fits'):
        assert (REF / product).exists(), REF / product
        assert (MX / product).exists(), MX / product
    difference_figure(
        REF, MX, 'img-MFS-image.fits',
        'Bootes 2048x2048 multiscale n3000, 4 output channels (MFS shown)',
        OUT / 'v010-bootes-difference.png',
        note='candidate v010-bootes2-mx, reference v010-bootes2-ref')

    figure, axis = plt.subplots(figsize=(7.5, 4.6))
    names, walls, stages = [], [], []
    for label, run in (('mx\nv010-rc1', MX), ('reference', REF)):
        names.append(label)
        walls.append(wall_seconds(run))
        stages.append(stage_seconds(run / 'wsclean.log'))
    axis.bar(names, walls, color=['#2a7f62', '#999999'])
    axis.set_ylabel('seconds')
    axis.set_title(f'Bootes multiscale clean -j8\n{walls[0]:.1f}s vs {walls[1]:.1f}s '
                   f'({walls[1] / max(walls[0], 1e-9):.2f}x)')
    axis.text(0.98, 0.96,
              'mx stages: ' + ' / '.join(f'{v:.1f}' for v in stages[0]) +
              '\nref stages: ' + ' / '.join(f'{v:.1f}' for v in stages[1]),
              transform=axis.transAxes, ha='right', va='top', fontsize=9,
              family='monospace')
    figure.tight_layout()
    figure.savefig(OUT / 'v010-bootes-timing.png', dpi=100)
    plt.close(figure)
    print('wrote v010-bootes-difference.png v010-bootes-timing.png')


if __name__ == '__main__':
    main()
