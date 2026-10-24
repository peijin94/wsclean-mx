#!/usr/bin/env python3
"""Render release evidence; numerical verdicts come from recorded T0 gates."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits


def validate_phase(result, phase, artifacts):
    """Validate a receipt and return the bound product directories by size.

    The gate producer records relative paths from the repository root.
    """
    if result.get('phase') != phase:
        raise ValueError(f'Unexpected receipt phase: {phase}')
    if result['passed'] is not True or result['input_unchanged'] is not True:
        raise ValueError(f'Incomplete phase: {phase}')
    sizes = [run['run']['size'] for run in result['runs']]
    if any(type(size) is not int for size in sizes) or sorted(sizes) != [3072, 4096]:
        raise ValueError(f'Unexpected cases: {phase}')
    artifacts = artifacts.resolve()
    repository = Path(__file__).resolve().parents[3]
    validated = {}
    for run in result['runs']:
        size = run['run']['size']
        gate = run['gate']
        if run['run'].get('phase') != phase or gate.get('label') != f'{phase}-{size}':
            raise ValueError(f'Unexpected run/gate identity: {phase}/{size}')
        paths = {}
        for side, role in (('left', 'baseline'), ('right', phase)):
            recorded = gate.get(side)
            if not isinstance(recorded, str) or not recorded:
                raise ValueError(f'Missing gate {side} path: {phase}/{size}')
            path = (repository / recorded).resolve()
            if path != (artifacts / f'imaging-{role}' / str(size)).resolve():
                raise ValueError(f'Unexpected gate {side} path: {phase}/{size}')
            paths[side] = path
        products = gate['products']
        if gate.get('expected') != 'T0' or gate['passed'] is not True or len(products) != 6:
            raise ValueError(f'Incomplete T0 gate: {phase}')
        expected = {'img-dirty.fits', 'img-image.fits', 'img-model.fits', 'img-psf.fits', 'img-residual.fits', 'img-horizon-mask.fits'}
        if {p['name'] for p in products} != expected:
            raise ValueError(f'Unexpected product inventory: {phase}')
        if any(p['T0'] is not True or p['bitwise'] is not True for p in products):
            raise ValueError(f'Non-bitwise product in {phase}')
        validated[size] = dict(paths, products=len(products))
    return validated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', required=True, type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    phases = [('native', 'Native'), ('installed-v2', 'Homebrew source'), ('poured', 'Bottle pour')]
    inventory = []
    validated = {}
    for phase, label in phases:
        result = json.loads((args.artifacts / f'imaging-{phase}' / 'result.json').read_text())
        validated[phase] = validate_phase(result, phase, args.artifacts)
        for size, case in validated[phase].items():
            inventory.append({'phase': label, 'size': size, 'products': case['products']})

    fig, axes = plt.subplots(2, 3, figsize=(12.6, 8), constrained_layout=True)
    details = []
    for row, size in enumerate((3072, 4096)):
        case = validated['poured'][size]
        left = np.asarray(fits.getdata(case['left'] / 'img-image.fits')).squeeze()
        right = np.asarray(fits.getdata(case['right'] / 'img-image.fits')).squeeze()
        if left.shape != (size, size) or right.shape != left.shape:
            raise ValueError('Unexpected restored-image geometry')
        if not np.array_equal(left, right, equal_nan=True):
            raise ValueError('Restored-image pixels contradict saved T0 verdict')
        valid = np.isfinite(left) & np.isfinite(right)
        vmax = float(np.percentile(left[valid], 99))
        difference = right.astype(np.float64) - left.astype(np.float64)
        max_difference = float(np.max(np.abs(difference[valid])))
        limit = max(float(np.percentile(np.abs(difference[valid]), 99)), 1e-7)
        for col, (image, title) in enumerate(((left, 'Frozen CPU reference'), (right, 'Poured wsclean-mx 0.1.1'))):
            shown = axes[row, col].imshow(image, origin='lower', cmap='magma', vmin=-0.05*vmax, vmax=vmax)
            axes[row, col].set_title(f'{title}\n{size} x {size}; upper stretch = p99')
            fig.colorbar(shown, ax=axes[row, col], shrink=0.72, label=f'Jy/beam; vmax={vmax:.3g} (p99)')
        shown = axes[row, 2].imshow(difference, origin='lower', cmap='RdBu_r', vmin=-limit, vmax=limit)
        axes[row, 2].set_title(f'Bottle minus reference\nmax |difference| = {max_difference:g} Jy/beam')
        fig.colorbar(shown, ax=axes[row, 2], shrink=0.72, label='Jy/beam; +/-1e-7 display floor when identically zero')
        for ax in axes[row]:
            ax.set_xlabel('Pixel x')
            ax.set_ylabel('Pixel y')
        details.append({'size': size, 'restored_max_abs_difference': max_difference, 'image_p99': vmax, 'difference_display_limit': limit})
    fig.suptitle('Release reproducibility: native, source-installed and bottle-poured binaries\nCORRECTED_DATA; 150,000-iteration cap; all six products pass T0 in each case', fontsize=12)
    fig.savefig(output/'image-consistency.png', dpi=140)
    plt.close(fig)
    (output/'figure-data.json').write_text(json.dumps({'comparisons': inventory, 'panels': details}, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
