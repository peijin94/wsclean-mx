#!/usr/bin/env python3
"""Figures for the external-validity gates (real LOFAR/MWA fixtures).

Two figures, both derived from the run products themselves (no cached JSON):

  external-differences.png  per dataset: reference restored image, the
                            candidate-minus-reference map and its histogram
  external-envelope.png     per dataset: each candidate's worst deviation per
                            metric, normalised by the widest reference-pair
                            deviation (the family envelope); >1 fails

Usage: .venv/bin/python bench/plot_external_gates.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
import numpy as np

from bench import compare_sources as cs
from bench import plot_science_gates as psg

OUT = ROOT / 'docs/bench/science-gates'

DATASETS = [
    dict(name='LOFAR LBA (lba.MS, 4 ch @57.8 MHz)',
         refs=[ROOT / f'bench/out/extlba-ref-r{n}/upstream-fix' for n in (1, 2, 3)],
         candidates=[('mx', [ROOT / f'bench/out/extlba-mx-r{n}/mx-p11' for n in (1, 2)]),
                     ('1-ulp control', [ROOT / 'bench/out/extlba-ulp-r1/upstream-fix-ulp'])],
         image='img-image.fits', model='img-model.fits'),
    dict(name='LOFAR HBA (L258627-one-timestep, 1 ch @138.5 MHz)',
         refs=[ROOT / f'bench/out/extlofar-ref-r{n}/upstream-fix' for n in (1, 2, 3, 4, 5, 6)],
         candidates=[('mx', [ROOT / f'bench/out/extlofar-mx-r{n}/mx-p11' for n in (1, 2, 3, 4)]),
                     ('1-ulp control', [ROOT / f'bench/out/extlofar-ulp-r{n}/upstream-fix-ulp'
                                        for n in (1, 2)])],
         image='img-image.fits', model='img-model.fits'),
    dict(name='MWA (PupA, 24 ch @133.8 MHz, 4 out)',
         refs=[ROOT / f'bench/out/extmwa-ref-r{n}/upstream-fix' for n in range(1, 9)],
         candidates=[('mx', [ROOT / f'bench/out/extmwa-mx-r{n}/mx-p11' for n in (1, 2, 3, 4)]),
                     ('1-ulp control', [ROOT / f'bench/out/extmwa-ulp-r{n}/upstream-fix-ulp'
                                        for n in (1, 2, 3)])],
         image='img-MFS-image.fits', model='img-MFS-model.fits'),
]

COLOURS = {'mx': '#1f77b4', '1-ulp control': '#d95f02'}
MARKERS = {'mx': '^', '1-ulp control': 's'}


def relative_rms(difference, reference):
    return float(np.sqrt(np.mean(difference ** 2)) / np.max(np.abs(reference)))


def differences_figure(out_path):
    rows = len(DATASETS)
    figure, axes = plt.subplots(rows, 3, figsize=(15, 4.4 * rows))
    for row, dataset in enumerate(DATASETS):
        reference_dir = dataset['refs'][0]
        candidate_dir = dataset['candidates'][0][1][0]
        reference = cs.read_image(reference_dir / dataset['image'])
        candidate = cs.read_image(candidate_dir / dataset['image'])
        difference = candidate - reference
        peak = float(np.max(np.abs(reference)))

        norm = SymLogNorm(linthresh=max(peak * 1e-4, 1e-12), vmin=-peak, vmax=peak, base=10)
        image = axes[row][0].imshow(reference, origin='lower', cmap='inferno', norm=norm)
        axes[row][0].set_title(f"{dataset['name']}\nreference (fixed upstream restored)", fontsize=10)
        figure.colorbar(image, ax=axes[row][0], fraction=0.046)

        scale = float(np.max(np.abs(difference)))
        diff_norm = SymLogNorm(linthresh=max(scale * 1e-2, 1e-12), vmin=-max(scale, 1e-12),
                               vmax=max(scale, 1e-12), base=10)
        image = axes[row][1].imshow(difference, origin='lower', cmap='RdBu_r', norm=diff_norm)
        axes[row][1].set_title(f"mx − reference   max |Δ| = {scale:.3g}", fontsize=10)
        figure.colorbar(image, ax=axes[row][1], fraction=0.046)

        axes[row][2].hist((difference / peak).ravel(), bins=200, log=True, color='#444444')
        axes[row][2].set_xlabel('(mx − reference) / peak')
        axes[row][2].set_ylabel('pixels')
        axes[row][2].set_title(f'relative rms = {relative_rms(difference, reference):.2e}',
                               fontsize=10)
        axes[row][2].grid(alpha=0.3)
    figure.tight_layout(rect=(0, 0.03, 1, 0.98))
    figure.text(0.5, 0.008,
                'Reference pair deviations on the same fields set the width of the envelope; '
                'rows 1–2 sit at the float32 floor, row 3 is cleaning-chaotic (see envelope figure).',
                ha='center', fontsize=9)
    figure.savefig(out_path, dpi=130)
    plt.close(figure)
    print(f'wrote {out_path.relative_to(ROOT)}')


def metric_rows(dataset):
    """(label, reference-pair deviations, envelope, {family: [worst deviations]})."""
    rows = []
    # The metric product names in psg.METRICS are img-image.fits / img-model.fits;
    # MWA needs the MFS variants, so map by suffix.
    def mapped(product):
        if dataset['image'].startswith('img-MFS'):
            return product.replace('img-', 'img-MFS-')
        return product

    for label, product, key in psg.METRICS:
        product = mapped(product)
        values = [cs.metrics(cs.read_image(d / product))[key] for d in dataset['refs']]
        pairs = [psg.deviation(a, b) for i, a in enumerate(values) for b in values[i + 1:]]
        pairs = [value for value in pairs if np.isfinite(value)]
        centre = float(np.median(values))
        family_values = {}
        for name, directories in dataset['candidates']:
            family_values[name] = [psg.deviation(centre, cs.metrics(cs.read_image(d / product))[key])
                                   for d in directories]
        rows.append((label, pairs, float(max(pairs)), family_values))

    for label, product in psg.SOURCE_METRICS:
        product = mapped(product)
        sources = [psg.source_list(d, product) for d in dataset['refs']]
        pairs = [psg.spread(sources[i], sources[j])
                 for i in range(len(sources)) for j in range(i + 1, len(sources))]
        pairs = [value for value in pairs if np.isfinite(value)]
        family_values = {}
        for name, directories in dataset['candidates']:
            per_run = []
            for directory in directories:
                candidate = psg.source_list(directory, product)
                per_run.append(max((psg.spread(reference, candidate) for reference in sources),
                                   default=np.nan))
            family_values[name] = per_run
        rows.append((label, pairs, float(max(pairs)), family_values))
    return rows


def envelope_figure(out_path):
    """Deviation vs the gate's own threshold, so 1.0 is exactly the gate boundary.

    The gate passes a metric when its deviation is within max(reference-pair
    envelope, float32 floor). Plotting deviation/threshold therefore puts the
    envelope marker left of 1.0 wherever the float32 floor, not the family, is
    the binding constraint.
    """
    figure, axes = plt.subplots(len(DATASETS), 1, figsize=(11, 11.5), sharex=True)
    for panel, dataset in enumerate(DATASETS):
        rows = metric_rows(dataset)
        worst_per_family = {name: 0.0 for name, _ in dataset['candidates']}
        for row, (label, _, envelope, family_values) in enumerate(rows):
            threshold = max(envelope, cs.NUMERICAL_FLOOR)
            marker = min(envelope / threshold, 1.0)
            axes[panel].plot([marker], [row], marker='|', markersize=16, color='#555555',
                             zorder=3)
            for name, values in family_values.items():
                finite = [value / threshold for value in values if np.isfinite(value)]
                if not finite:
                    continue
                worst_per_family[name] = max(worst_per_family[name], max(finite))
                axes[panel].scatter(finite, np.full(len(finite), row) +
                                    (0.14 if name == 'mx' else -0.14),
                                    s=46, color=COLOURS[name], marker=MARKERS[name],
                                    zorder=4, edgecolor='white', linewidth=0.5,
                                    label=name if row == 0 else None)
            if row == 0:
                axes[panel].legend(loc='lower left', fontsize=8, framealpha=0.9)
        axes[panel].set_yticks(list(range(len(rows))))
        axes[panel].set_yticklabels([label for label, _, _, _ in rows], fontsize=9)
        axes[panel].set_title(
            f"{dataset['name']}  —  worst "
            + ', '.join(f'{name} {value:.2f}' for name, value in worst_per_family.items())
            + ' × threshold', fontsize=10)
        axes[panel].grid(alpha=0.3, axis='x')
        axes[panel].set_xlim(1e-4, 4)
        axes[panel].axvline(1.0, color='black', lw=1.1, ls=':')
    axes[-1].set_xscale('log')
    axes[-1].set_xlabel('candidate deviation / max(reference-pair envelope, float32 floor)'
                        '    —    dotted line = the gate boundary')
    figure.suptitle('External validity: each candidate measured with the gate\'s own statistic\n'
                    '(grey marks = the run-to-run envelope of that field\'s reference reruns; '
                    'left of the dotted line means the float32 floor is binding)',
                    fontsize=11)
    figure.tight_layout(rect=(0, 0.055, 1, 0.93))
    figure.text(0.5, 0.012,
                'mx = wsclean-mx p11 stack; control = fixed reference perturbed by one ulp —\n'
                'the same code path, so a chaotic configuration pushes both across the boundary:\n'
                'the failure is then not mx-specific.', ha='center', fontsize=9)
    figure.savefig(out_path, dpi=130)
    plt.close(figure)
    print(f'wrote {out_path.relative_to(ROOT)}')


def main():
    differences_figure(OUT / 'external-differences.png')
    envelope_figure(OUT / 'external-envelope.png')


if __name__ == '__main__':
    main()
