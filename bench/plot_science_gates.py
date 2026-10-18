#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Figures for the source-level science gates (docs/science-gates.md).

Produces, under docs/bench/science-gates/:

  lofar-difference.png     restored 3C196 image, mx-minus-reference difference,
                           and the difference distribution (real-source field)
  quiet-sun-difference.png same for the quiet-Sun multiscale case
  envelope-scatter.png     reference-pair deviations against the mx-p11 and
                           perturbed-reference candidates, for both datasets

Run with the project venv: .venv/bin/python bench/plot_science_gates.py
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # runnable as a script, not only as a module

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
import numpy as np

from bench import compare_sources as cs

QUIET_SUN_REFS = [ROOT / f'bench/out/envelope18-ref-r{n}/upstream-fix'
                  for n in range(4, 54)]
QUIET_SUN_MX = [ROOT / f'bench/out/envelope18-mx-r{n}/mx-p11' for n in (4, 5, 6, 7)]
QUIET_SUN_ULP = [ROOT / f'bench/out/envelope18-ulp-r{n}/upstream-fix-ulp'
                 for n in (1, 3, 4, 5, 6)]
LOFAR_REFS = [ROOT / f'bench/out/lofar18-ref-r{n}/upstream-fix' for n in (1, 2, 3, 4)]
LOFAR_MX = [ROOT / f'bench/out/lofar18-mx-r{n}/mx-p11' for n in (1, 2, 3)]
LOFAR_ULP = [ROOT / f'bench/out/lofar18-ulp-r{n}/upstream-fix-ulp' for n in (1, 2)]

METRICS = [('restored total flux', 'img-image.fits', 'total_flux'),
           ('model MAD rms', 'img-model.fits', 'mad_rms'),
           ('restored 2nd moment', 'img-image.fits', 'second_moment'),
           ('residual total flux', 'img-residual.fits', 'total_flux')]
SOURCE_METRICS = [('restored source flux spread', 'img-image.fits'),
                  ('model source flux spread', 'img-model.fits')]


def deviation(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-30)


def difference_figure(reference_dir, candidate_dir, product, title, out_path, note):
    reference = cs.read_image(reference_dir / product)
    candidate = cs.read_image(candidate_dir / product)
    difference = candidate - reference
    peak = float(np.max(np.abs(reference)))
    relative_rms = float(np.sqrt(np.mean(difference ** 2)) / peak)
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    figure.suptitle(title, fontsize=13)

    norm = SymLogNorm(linthresh=max(peak * 1e-4, 1e-12), vmin=-peak, vmax=peak, base=10)
    image = axes[0].imshow(reference, origin='lower', cmap='inferno', norm=norm)
    axes[0].set_title('reference (fixed upstream)')
    figure.colorbar(image, ax=axes[0], fraction=0.046)

    scale = float(np.max(np.abs(difference)))
    diff_norm = SymLogNorm(linthresh=max(scale * 1e-3, 1e-12), vmin=-max(scale, 1e-12),
                           vmax=max(scale, 1e-12), base=10)
    image = axes[1].imshow(difference, origin='lower', cmap='RdBu_r', norm=diff_norm)
    axes[1].set_title(f'candidate − reference   (max |Δ| = {scale:.3g})')
    figure.colorbar(image, ax=axes[1], fraction=0.046)

    axes[2].hist((difference / peak).ravel(), bins=200, log=True, color='#444444')
    axes[2].set_xlabel('(candidate − reference) / peak')
    axes[2].set_ylabel('pixels')
    axes[2].set_title(f'relative rms = {relative_rms:.2e}')
    axes[2].grid(alpha=0.3)

    figure.tight_layout(rect=(0, 0.06, 1, 0.95))
    figure.text(0.5, 0.015, note, ha='center', fontsize=9)
    figure.savefig(out_path, dpi=130)
    plt.close(figure)
    print(f'wrote {out_path.relative_to(ROOT)}  (max |Δ| {scale:.3g}, rel rms {relative_rms:.2e})')


def source_list(directory, product):
    data = cs.read_image(directory / product)
    return cs.detect_sources(data, cs.mad_rms(data))


def spread(reference_sources, candidate_sources):
    return cs.compare_sources(reference_sources, candidate_sources).get('flux_ratio_spread',
                                                                        np.nan)


def rows_for(references, candidates):
    """Per metric: reference-pair values, their max, and each candidate's worst value."""
    rows = []
    for label, product, key in METRICS:
        values = [cs.metrics(cs.read_image(d / product))[key] for d in references]
        pairs = [deviation(a, b) for i, a in enumerate(values) for b in values[i + 1:]]
        centre = float(np.median(values))
        candidate_values = [[deviation(centre, cs.metrics(cs.read_image(d / product))[key])
                             for d in family] for family in candidates]
        rows.append((label, pairs, candidate_values))
    for label, product in SOURCE_METRICS:
        sources = [source_list(d, product) for d in references]
        pairs = [spread(sources[i], sources[j])
                 for i in range(len(sources)) for j in range(i + 1, len(sources))]
        candidate_values = []
        for family in candidates:
            per_run = []
            for directory in family:
                candidate = source_list(directory, product)
                per_run.append(max((spread(reference, candidate) for reference in sources),
                                   default=np.nan))
            candidate_values.append(per_run)
        rows.append((label, pairs, candidate_values))
    return rows


def scatter_panel(axes, references, candidates, title):
    """Reference-pair values vs candidate values, per metric."""
    rows = rows_for(references, candidates)
    for row, (label, pairs, candidate_values) in enumerate(rows):
        pairs = [value for value in pairs if np.isfinite(value)]
        axes.scatter(pairs, np.full(len(pairs), row), s=16, color='#9a9a9a',
                     zorder=2, label='reference pairs' if row == 0 else None)
        axes.scatter([max(pairs)], [row], marker='|', s=220, color='black',
                     zorder=3, label='envelope (max)' if row == 0 else None)
        for colour, values, marker, offset in (('#1f77b4', candidate_values[0], '^', 0.22),
                                               ('#d95f02', candidate_values[1], 's', -0.22)):
            finite = [value for value in values if np.isfinite(value)]
            if not finite:
                continue
            name = {'#1f77b4': 'mx-p11', '#d95f02': 'perturbed ref'}[colour]
            axes.scatter(finite, np.full(len(finite), row + offset), marker=marker, s=42,
                         color=colour, zorder=4, edgecolor='white', linewidth=0.5,
                         label=name if row == 0 else None)
    axes.set_yticks(range(len(rows)))
    axes.set_yticklabels([label for label, _, _ in rows], fontsize=9)
    axes.set_xscale('log')
    axes.set_xlabel('relative deviation')
    axes.set_title(title, fontsize=11)
    axes.grid(axis='x', alpha=0.3)
    axes.set_ylim(-0.45, len(rows) - 0.45)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/bench/science-gates')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    difference_figure(
        LOFAR_REFS[0], LOFAR_MX[0], 'img-image.fits',
        'LOFAR 3C196 (real calibrator): mx-p11 vs fixed reference, restored image',
        args.out / 'lofar-difference.png',
        'Single -j 8 multiscale run each; disagreement at float32 rounding level means the '
        'stack reproduces the reference. Source fluxes and positions also match to ~1e-7.')
    difference_figure(
        QUIET_SUN_REFS[0], QUIET_SUN_MX[0], 'img-image.fits',
        'OVRO-LWA quiet-Sun 2048² multiscale: mx-p11 vs fixed reference, restored image',
        args.out / 'quiet-sun-difference.png',
        'Cleaning is chaotic here: the reference differs from its own reruns by the same '
        'order (50-rerun scatter: 3.0% median / 8.1% max on total flux).')

    figure, axes = plt.subplots(2, 1, figsize=(9.5, 8.6))
    print(f'quiet-sun family: {len(QUIET_SUN_REFS)} reruns, '
          f'{len(QUIET_SUN_MX)} mx and {len(QUIET_SUN_ULP)} perturbed-reference candidates')
    print(f'3C196 family: {len(LOFAR_REFS)} reruns, '
          f'{len(LOFAR_MX)} mx and {len(LOFAR_ULP)} perturbed-reference candidates')
    scatter_panel(axes[0], QUIET_SUN_REFS, (QUIET_SUN_MX, QUIET_SUN_ULP),
                  f'Quiet-Sun 2048² multiscale — {len(QUIET_SUN_REFS)} reference reruns')
    scatter_panel(axes[1], LOFAR_REFS, (LOFAR_MX, LOFAR_ULP),
                  f'LOFAR 3C196 real-source field — {len(LOFAR_REFS)} reference reruns')
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc='lower center', ncol=4, fontsize=9, frameon=False)
    figure.suptitle('Reference family scatter vs candidates (bench/compare_sources.py metrics)',
                    fontsize=12)
    figure.tight_layout(rect=(0, 0.05, 1, 0.96))
    figure.savefig(args.out / 'envelope-scatter.png', dpi=130)
    plt.close(figure)
    print(f'wrote {(args.out / "envelope-scatter.png").relative_to(ROOT)}')


if __name__ == '__main__':
    main()
