#!/usr/bin/env python3
"""Render retained CPU-correctness evidence; does not reclassify any gate."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
data = json.loads((HERE / 'results.json').read_text())
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
colors = {'old': '#6b7280', 'new': '#167a83'}
for group, size in enumerate((3072, 4096)):
    for offset, role in ((-.18, 'old'), (.18, 'new')):
        samples = data['summary'][str(size)][role]['wall_s']['samples']
        center = group + offset
        axes[0].bar(center, np.median(samples), width=.32, color=colors[role],
                    alpha=.65, label=role if group == 0 else None)
        axes[0].scatter(np.full(len(samples), center), samples, c='black', s=20, zorder=3)
axes[0].set(xticks=[0, 1], xticklabels=['3072 square', '4096 square'],
            ylabel='Measured wall time (s)', title='Sequential runs: median and every sample')
axes[0].legend()
products = ['img-dirty.fits', 'img-psf.fits', 'img-image.fits', 'img-model.fits', 'img-residual.fits']
styles = [('3072-old-repeat', '3K old/old', '#6b7280', 'x'),
          ('3072-old-new-1', '3K old/new', '#167a83', 'o'),
          ('4096-old-new-1', '4K old/new', '#c04c31', 's')]
for label, text, color, marker in styles:
    comparison = next(c for c in data['comparisons'] if c['label'] == label)
    rows = {r['product']: r for r in comparison['products']}
    axes[1].plot(range(len(products)), [rows[p]['rel_rms'] for p in products],
                 marker=marker, color=color, label=text, lw=1)
axes[1].axhline(1e-4, color='black', ls='--', label='Unchanged T2 RMS limit')
axes[1].set(yscale='log', xticks=range(len(products)),
            xticklabels=['dirty', 'PSF', 'restored', 'model', 'residual'],
            ylabel='Difference RMS / reference RMS', title='Retained strict-gate outcomes')
axes[1].legend(fontsize=8)
fig.suptitle('CPU repairs: new/new arrays are bitwise identical; old/new T2 is not all green', fontsize=12)
fig.savefig(HERE / 'verification.png', dpi=170)
plt.close(fig)

old = ROOT / 'bench/out/cpufix-20261022-4096-old-r1/cpu-weighted-v1-20261022/img-image.fits'
new1 = ROOT / 'bench/out/cpufix-20261022-4096-new-r1/mx/img-image.fits'
new2 = ROOT / 'bench/out/cpufix-20261022-4096-new-r2/mx/img-image.fits'
ref = fits.getdata(old).squeeze().astype(np.float64)
new = fits.getdata(new1).squeeze().astype(np.float64)
repeat = fits.getdata(new2).squeeze().astype(np.float64)
diff = new - ref
vmax = float(np.nanpercentile(ref, 99))
dmax = float(np.nanpercentile(np.abs(diff), 99))
if not np.isfinite(vmax) or vmax <= 0 or not np.isfinite(dmax) or dmax <= 0:
    raise ValueError('Cannot render invalid percentile scales')
fig, axes = plt.subplots(1, 3, figsize=(13, 4.3), constrained_layout=True)
a = axes[0].imshow(ref, origin='lower', cmap='inferno', vmin=-.1*vmax, vmax=vmax)
b = axes[1].imshow(diff, origin='lower', cmap='RdBu_r', vmin=-dmax, vmax=dmax)
c = axes[2].imshow(repeat-new, origin='lower', cmap='RdBu_r', vmin=-dmax, vmax=dmax)
axes[0].set_title('Old 4K restored image')
axes[1].set_title('New minus old: T2 FAIL')
axes[2].set_title('New repeat minus new: T0 PASS')
for ax in axes:
    ax.set_xticks([]);ax.set_yticks([])
fig.colorbar(a, ax=axes[0], fraction=.045, label=f'Jy/beam; vmax=p99={vmax:.3g}')
fig.colorbar(b, ax=axes[1], fraction=.045, label=f'Jy/beam; ±p99={dmax:.3g}')
fig.colorbar(c, ax=axes[2], fraction=.045, label='Same difference scale')
fig.savefig(HERE / 'image-differences.png', dpi=170)
plt.close(fig)
print(json.dumps({'reference_p99':vmax,'difference_abs_p99':dmax,
                  'repeat_max_abs':float(np.nanmax(np.abs(repeat-new)))}, indent=2))
