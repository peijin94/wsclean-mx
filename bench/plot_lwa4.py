#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""LWA 4arcmin benchmark plot: wall + stage splits, ref vs mx.

Run: .venv/bin/python bench/plot_lwa4.py
"""
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RUNS = [
    ('dirty\nref', 'v010-lwa4-ref/reffix-verified'),
    ('dirty\nmx', 'v010-lwa4-mx/v010-rc1'),
    ('clean\nref', 'v010-lwa4clean-ref/reffix-verified'),
    ('clean\nmx', 'v010-lwa4clean-mx/v010-rc1'),
]
STAGE_RE = re.compile(
    r'Inversion:\s*(\d+):(\d+):([\d.]+),\s*prediction:\s*(\d+):(\d+):([\d.]+),\s*'
    r'deconvolution:\s*(\d+):(\d+):([\d.]+)')


def seconds(match, base):
    return (float(match[base]) * 3600 + float(match[base + 1]) * 60
            + float(match[base + 2]))


def main():
    labels, inv, pred, dec = [], [], [], []
    for label, tag in RUNS:
        run = ROOT / 'bench/out' / tag
        match = STAGE_RE.search((run / 'wsclean.log').read_text(errors='ignore'))
        labels.append(label)
        inv.append(seconds(match.groups(), 0))
        pred.append(seconds(match.groups(), 3))
        dec.append(seconds(match.groups(), 6))
    figure, axis = plt.subplots(figsize=(7.5, 4.4))
    bottom = [0.0] * len(labels)
    for values, name in ((inv, 'inversion'), (pred, 'prediction'),
                         (dec, 'deconvolution')):
        axis.bar(labels, values, bottom=bottom, label=name)
        bottom = [b + v for b, v in zip(bottom, values)]
    for i, (a, b, c) in enumerate(zip(inv, pred, dec)):
        axis.text(i, a + b + c + 2, f'{a + b + c:.0f}s', ha='center', fontsize=9)
    axis.set_ylabel('seconds')
    axis.set_title('LWA 64 MHz full-sky 2048 4arcmin, -j8\n'
                   'dirty 46.5 vs 25.8 s (1.80x) — clean 170.5 vs 147.3 s '
                   '(deconv 18.8 vs 4.0 s)')
    axis.legend()
    figure.tight_layout()
    figure.savefig(ROOT / 'docs/bench/v010-lwa4-timing.png', dpi=100)
    print('wrote v010-lwa4-timing.png')


if __name__ == '__main__':
    main()
