import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

cpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/e4cc/image.fits").squeeze()
gpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/e4gg/image.fits").squeeze()
diff = gpu - cpu
peak = cpu.max()
vmin, vmax = -0.05 * peak, 0.25 * peak

fig, ax = plt.subplots(1, 3, figsize=(16, 5.2))
for a, d, t in ((ax[0], cpu, "Mac CPU restored"), (ax[1], gpu, "Mac GPU (-mgpu) restored")):
    im = a.imshow(d, origin="lower", cmap="inferno", vmin=vmin, vmax=vmax)
    a.set_title(t)
    a.set_xticks([]); a.set_yticks([])
fig.colorbar(im, ax=ax[1], fraction=0.046, pad=0.02, label="Jy/beam")

m = np.abs(diff).max()
im2 = ax[2].imshow(diff, origin="lower", cmap="RdBu_r", vmin=-m, vmax=m)
ax[2].set_title("GPU - CPU  (max %.2g Jy/beam)" % m)
ax[2].set_xticks([]); ax[2].set_yticks([])
fig.colorbar(im2, ax=ax[2], fraction=0.046, pad=0.02, label="Jy/beam")

fig.suptitle("LWA 64 MHz 4-slot, exo-pipe-style deep clean: 4096px, 2amin, multiscale, "
             "niter 20000, mgain 0.95, auto-mask 3, local-rms")
fig.tight_layout()
out = "/Users/peijinz/dev/wsclean-mx/bench/out/exp4k-cpu-gpu.png"
fig.savefig(out, dpi=90)
print("wrote", out, "| peak %.3f | diff max %.3g | rel_rms %.3g" %
      (peak, m, np.sqrt((diff ** 2).mean()) / peak))
