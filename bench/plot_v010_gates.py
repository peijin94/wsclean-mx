#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""v0.1.0 release-candidate figures for the Linear PZ-19 update.

Produces under docs/bench/:
  v010-lofar-difference.png  3C196 restored (mx), mx-ref difference, histogram
  v010-timing.png            wall/stage bars mx vs reference (+ A/A note)
  v010-basin.png             pairwise cleaned-product RMS across the widened
                             3C196 family (basin structure)

Run: .venv/bin/python bench/plot_v010_gates.py
"""
import re
from pathlib import Path
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
REFS = [ROOT / f'bench/out/v010-lofar2-r{i}/reffix-verified' for i in (1, 2, 3, 4, 5)]
MXS = [ROOT / f'bench/out/v010-lofar2-mx{i}/v010-rc1' for i in (1, 2, 3, 4)]

STAGE_RE = re.compile(
    r'Inversion:\s*(\d+):(\d+):([\d.]+),\s*prediction:\s*(\d+):(\d+):([\d.]+),\s*'
    r'deconvolution:\s*(\d+):(\d+):([\d.]+)')


def stage_seconds(log_path):
    text = Path(log_path).read_text(errors='ignore')
    match = STAGE_RE.search(text)
    if not match:
        return None
    groups = [float(g) for g in match.groups()]
    return (groups[0] * 3600 + groups[1] * 60 + groups[2],
            groups[3] * 3600 + groups[4] * 60 + groups[5],
            groups[6] * 3600 + groups[7] * 60 + groups[8])


def wall_seconds(run_dir):
    for line in Path(run_dir, 'time.txt').read_text(errors='ignore').splitlines():
        if line.startswith('real'):
            return float(line.split()[1])
    return float('nan')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for directory in REFS + MXS:
        assert (directory / 'img-image.fits').exists(), directory

    # 1. Image + difference figure (mx1 sits in the reference basin).
    difference_figure(
        REFS[0], MXS[0], 'img-image.fits',
        'v0.1.0-rc1 vs fixed reference: 3C196 restored, 1024x1024 multiscale niter 3000',
        OUT / 'v010-lofar-difference.png',
        note='candidate v010-lofar2-mx1, reference v010-lofar2-r1')

    # 2. Timing bars.
    configs = [
        ('1024 dirty -j1\nOVRO snapshot', [(ROOT / 'bench/out/v010-t0-dirty/v010-rc1'),
                                           (ROOT / 'bench/out/v010-t0-dirty/reffix-verified')]),
        ('1024 ms n300 -j1\nOVRO snapshot', [(ROOT / 'bench/out/v010-t0-ms/v010-rc1'),
                                             (ROOT / 'bench/out/v010-t0-ms/reffix-verified')]),
        ('1024 3C196 ms n3000 -j8', MXS[:2] + REFS[:3]),
    ]
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    figure.suptitle('v0.1.0-rc1 wall time vs fixed reference (real seconds, one run each '
                    'except 3C196 medians)', fontsize=12)
    for axis, (title, dirs) in zip(axes, configs):
        mx_walls, ref_walls, mx_stages, ref_stages = [], [], [], []
        for run in dirs:
            stages = stage_seconds(run / 'wsclean.log')
            wall = wall_seconds(run)
            if 'v010-rc1' in run.parts:
                mx_walls.append(wall)
                if stages:
                    mx_stages.append(stages)
            else:
                ref_walls.append(wall)
                if stages:
                    ref_stages.append(stages)
        mx_med, ref_med = float(np.median(mx_walls)), float(np.median(ref_walls))
        axis.bar(['mx\nv010-rc1', 'reference'], [mx_med, ref_med], color=['#2a7f62', '#999999'])
        axis.set_title(f'{title}\n{mx_med:.2f}s vs {ref_med:.2f}s '
                       f'({ref_med / max(mx_med, 1e-9):.2f}x)')
        axis.set_ylabel('seconds')
        if mx_stages and ref_stages:
            labels = ['inversion', 'prediction', 'deconvolution']
            axis.text(0.98, 0.96,
                      'mx stages: ' + ' / '.join(f'{v:.2f}' for v in np.median(mx_stages, axis=0)) +
                      '\nref stages: ' + ' / '.join(f'{v:.2f}' for v in np.median(ref_stages, axis=0)),
                      transform=axis.transAxes, ha='right', va='top', fontsize=8,
                      family='monospace')
    figure.tight_layout()
    figure.savefig(OUT / 'v010-timing.png', dpi=100)
    plt.close(figure)

    # 3. Basin matrix: pairwise rel RMS of the restored image.
    labels = [f'ref{i + 1}' for i in range(len(REFS))] + \
             [f'mx{i + 1}' for i in range(len(MXS))]
    arrays = [cs.read_image(d / 'img-image.fits') for d in REFS + MXS]
    n = len(arrays)
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            diff = arrays[i] - arrays[j]
            matrix[i, j] = float(np.sqrt(np.mean(diff ** 2)) / np.sqrt(np.mean(arrays[j] ** 2)))
    figure, axis = plt.subplots(figsize=(7.2, 6.2))
    im = axis.imshow(np.log10(np.maximum(matrix, 1e-12)), vmin=-8, vmax=-1)
    axis.set_xticks(range(n), labels, rotation=45)
    axis.set_yticks(range(n), labels)
    for i in range(n):
        for j in range(n):
            axis.text(j, i, f'{matrix[i, j]:.1e}', ha='center', va='center', fontsize=8,
                      color='white' if matrix[i, j] > 3e-4 else 'black')
    axis.set_title('3C196 restored-image pairwise rel RMS (log10 scale)\n'
                   'mx1/mx3/mx4 inside the reference basin (~6e-7); single mx2 excursion', fontsize=11)
    figure.colorbar(im, label='log10 rel RMS')
    figure.tight_layout()
    figure.savefig(OUT / 'v010-basin.png', dpi=100)
    plt.close(figure)
    print('wrote v010-lofar-difference.png v010-timing.png v010-basin.png')


if __name__ == '__main__':
    main()
