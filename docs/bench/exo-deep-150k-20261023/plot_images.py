#!/usr/bin/env python3
"""Publish real 150k-budget FITS previews and same-build repeat differences.

Run from any directory with the project venv. No WSClean jobs are started and
no FITS inputs are written. These panels do not test legacy-build equivalence.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, SymLogNorm
import numpy as np

from bench.compare_sources import read_image

HERE = Path(__file__).resolve().parent


def render_case(reference_dir, candidate_dir, output, title):
    """Render restored/residual reference pixels and candidate-minus-reference."""
    reference = read_image(reference_dir / 'img-image.fits')
    residual = read_image(reference_dir / 'img-residual.fits')
    candidate = read_image(candidate_dir / 'img-image.fits')
    mask_pixels = read_image(reference_dir / 'img-horizon-mask.fits')
    if any(pixels.shape != reference.shape for pixels in (residual, candidate, mask_pixels)):
        raise ValueError('Image, residual, repeat and horizon mask shapes must match')
    if not np.isin(mask_pixels, (0, 1)).all() or not np.any(mask_pixels):
        raise ValueError('Expected a nonempty binary horizon mask')
    mask = mask_pixels > 0
    difference = candidate - reference
    p99 = float(np.percentile(reference[mask], 99))
    residual_p99 = float(np.percentile(np.abs(residual[mask]), 99))
    difference_p99 = float(np.percentile(np.abs(difference[mask]), 99))
    max_difference = float(np.max(np.abs(difference[mask])))
    peak = float(np.max(np.abs(reference[mask])))
    image_limit = max(p99, 1e-12)
    residual_limit = max(residual_p99, 1e-12)
    difference_limit = max(difference_p99, 1e-12)
    figure, axes = plt.subplots(1, 3, figsize=(16, 5.3))
    panels = [
        (reference, 'Restored reference: run 1', 'inferno',
         Normalize(vmin=-0.02 * image_limit, vmax=image_limit),
         f'Jy/beam; p99={p99:.4g}, peak={peak:.4g}'),
        (residual, 'Residual reference: run 1', 'RdBu_r',
         SymLogNorm(linthresh=max(residual_limit * 0.01, 1e-12),
                    vmin=-residual_limit, vmax=residual_limit),
         f'Jy/beam; |residual| p99={residual_p99:.4g}'),
        (difference, f'Run 2 - run 1: max |diff|={max_difference:.3g}', 'RdBu_r',
         SymLogNorm(linthresh=max(difference_limit * 0.01, 1e-12),
                    vmin=-difference_limit, vmax=difference_limit),
         f'Jy/beam; |diff| p99={difference_p99:.3g}; plot +/-{difference_limit:.3g}'),
    ]
    for axis, (pixels, label, cmap, norm, colorbar_label) in zip(axes, panels):
        image = axis.imshow(np.ma.array(pixels, mask=~mask), origin='lower',
                            cmap=cmap, norm=norm, interpolation='nearest')
        axis.set(title=label, xlabel='Image pixel x', ylabel='Image pixel y')
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label=colorbar_label)
    kept = int(np.count_nonzero(mask))
    fraction = kept / mask.size
    figure.suptitle(title, fontsize=14)
    figure.text(0.5, 0.035,
                f'Generated 10-degree horizon mask; {fraction:.1%} of pixels shown. '
                'Restored: linear p99; residual/difference: symlog p99 of magnitude.\n'
                'Reference and repeat use the same CPU build. Zero-difference plot limits '
                'use a display floor, not a numerical acceptance threshold.',
                ha='center', fontsize=10)
    figure.tight_layout(rect=(0, 0.12, 1, 0.94))
    figure.savefig(output, dpi=130)
    plt.close(figure)
    return {'restored_p99': p99, 'restored_peak': peak,
            'residual_abs_p99': residual_p99,
            'repeat_abs_difference_p99': difference_p99,
            'repeat_max_abs_difference': max_difference,
            'difference_display_limit': difference_limit,
            'kept_pixels': kept, 'total_pixels': int(mask.size),
            'kept_fraction': fraction}


if __name__ == '__main__':
    results = json.loads((HERE / 'results.json').read_text())
    statistics = []
    for size in (3072, 4096):
        rows = sorted((r for r in results['runs'] if r['size'] == size),
                      key=lambda r: r['repeat'])
        if ([r['repeat'] for r in rows] != [1, 2] or
                any(r['niter'] != 150000 or r['exit'] != 0 for r in rows)):
            raise ValueError('Expected two successful 150k-budget repeats per size')
        reference = ROOT / f'bench/out/exo150k-20261023-{size}-r1/mx'
        candidate = ROOT / f'bench/out/exo150k-20261023-{size}-r2/mx'
        output = HERE / f'images-{size}.png'
        measured = render_case(reference, candidate, output,
                               f'{size} square - 150,000 cap; final threshold at '
                               f"{rows[0]['last_iteration']:,} iterations - CPU, 8 threads")
        measured.update(size=size, reference=str(reference.relative_to(ROOT)),
                        candidate=str(candidate.relative_to(ROOT)))
        statistics.append(measured)
        print(output)
    (HERE / 'image-statistics.json').write_text(json.dumps(statistics, indent=2) + '\n')
