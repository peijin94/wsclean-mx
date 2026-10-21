import numpy as np
from astropy.io import fits
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

cpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/lwa4-cpu/img-dirty.fits").squeeze()
gpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/lwa4-gpu/img-dirty.fits").squeeze()
diff = gpu - cpu

peak = np.abs(cpu).max()
print("cpu peak %.4g min %.4g | gpu peak %.4g min %.4g" % (cpu.max(), cpu.min(), gpu.max(), gpu.min()))
print("diff max_abs %.4g rms %.4g rel_rms %.4g rel_peak %.4g peak_ratio %.8f" % (
    np.abs(diff).max(), np.sqrt(np.mean(diff**2)),
    np.sqrt(np.mean(diff**2)) / np.sqrt(np.mean(cpu**2)),
    np.abs(diff).max() / peak, np.abs(gpu).max() / peak))

fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
vmax = np.percentile(np.abs(cpu), 99.9)
im0 = ax[0].imshow(cpu, origin="lower", cmap="inferno", vmin=-vmax, vmax=vmax)
ax[0].set_title("CPU dirty (Jy/beam)")
plt.colorbar(im0, ax=ax[0], fraction=0.046)
im1 = ax[1].imshow(gpu, origin="lower", cmap="inferno", vmin=-vmax, vmax=vmax)
ax[1].set_title("GPU (-mgpu) dirty (Jy/beam)")
plt.colorbar(im1, ax=ax[1], fraction=0.046)
dmax = np.abs(diff).max()
im2 = ax[2].imshow(diff, origin="lower", cmap="seismic", vmin=-dmax, vmax=dmax)
ax[2].set_title("GPU-CPU diff (max %.2g)" % dmax)
plt.colorbar(im2, ax=ax[2], fraction=0.046)
for a in ax:
    a.set_xticks([]); a.set_yticks([])
fig.suptitle("LWA 64MHz full-sky 4-slot dirty: CPU vs -mgpu (T2 rel_rms 2.9e-06)")
fig.tight_layout()
fig.savefig("/Users/peijinz/dev/wsclean-mx/bench/out/lwa4-cpu-gpu.png", dpi=90)
print("wrote bench/out/lwa4-cpu-gpu.png")
