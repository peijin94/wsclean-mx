#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Pipeline-style LWA comparison: linear-scale image, horizon-masked stats.

Difference metrics count only pixels above the horizon mask (elevation >=
10 deg = angular distance from phase centre <= 80 deg). Reference panel is
linear scale per request (saturated at p99 to stay informative).

Run: .venv/bin/python bench/plot_pipe.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

REF = ROOT / 'bench/out/v010-pipe-ref/reffix-verified'
MX = ROOT / 'bench/out/v010-pipe-mx/v010-rc1'
PRODUCT = 'img-image.fits'
MASK_DEG = 80.0


def load(path):
    with fits.open(path) as hdul:
        return np.asarray(hdul[0].data).squeeze().astype(np.float64), hdul[0].header


def horizon_mask(header, shape):
    wcs = WCS(header).celestial
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    ra, dec = wcs.all_pix2world(xx, yy, 0)
    ra0, dec0 = header['CRVAL1'], header['CRVAL2']
    cosang = (np.sin(np.radians(dec0)) * np.sin(np.radians(dec))
              + np.cos(np.radians(dec0)) * np.cos(np.radians(dec))
              * np.cos(np.radians(ra - ra0)))
    return np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0))) <= MASK_DEG


def main():
    reference, header = load(REF / PRODUCT)
    candidate, _ = load(MX / PRODUCT)
    mask = horizon_mask(header, reference.shape)
    difference = candidate - reference
    masked = difference[mask]
    peak = float(np.max(np.abs(reference[mask])))
    relative_rms = float(np.sqrt(np.mean(masked ** 2)) / peak)
    scale = float(np.max(np.abs(masked)))
    print(f'above-horizon pixels: {mask.sum()} / {mask.size}')

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    figure.suptitle('OVRO-LWA 64 MHz pipeline-style multiscale (above-horizon stats only)',
                    fontsize=13)
    vmax = float(np.quantile(reference[mask], 0.99))
    image = axes[0].imshow(reference, origin='lower', cmap='inferno',
                           vmin=0.0, vmax=vmax)
    axes[0].set_title('reference (fixed upstream, linear)')
    figure.colorbar(image, ax=axes[0], fraction=0.046)

    from matplotlib.colors import SymLogNorm
    diff_norm = SymLogNorm(linthresh=max(scale * 1e-3, 1e-12),
                           vmin=-max(scale, 1e-12), vmax=max(scale, 1e-12),
                           base=10)
    image = axes[1].imshow(np.where(mask, difference, np.nan), origin='lower',
                           cmap='RdBu_r', norm=diff_norm)
    axes[1].set_title(f'candidate − reference   (max |Δ| = {scale:.3g})')
    figure.colorbar(image, ax=axes[1], fraction=0.046)

    axes[2].hist((masked / peak).ravel(), bins=200, log=True, color='#444444')
    axes[2].set_xlabel('(candidate − reference) / peak  [above horizon]')
    axes[2].set_ylabel('pixels')
    axes[2].set_title(f'relative rms = {relative_rms:.2e}')
    axes[2].grid(alpha=0.3)

    figure.tight_layout(rect=(0, 0.06, 1, 0.95))
    figure.text(0.5, 0.015, 'candidate v010-pipe-mx, reference v010-pipe-ref',
                ha='center', fontsize=9)
    out = ROOT / 'docs/bench/v010-pipe-difference.png'
    figure.savefig(out, dpi=130)
    plt.close(figure)
    print(f'wrote docs/bench/v010-pipe-difference.png  '
          f'(max |Δ| {scale:.3g}, rel rms {relative_rms:.2e})')


if __name__ == '__main__':
    main()
