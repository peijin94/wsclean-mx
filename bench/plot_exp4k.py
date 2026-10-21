import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

cpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/exp4k-cpu/deep-image.fits").squeeze()
gpu = fits.getdata("/Users/peijinz/dev/wsclean-mx/bench/out/exp4k-gpu/deep-image.fits").squeeze()
diff = gpu - cpu

# Stretch to the 99.5th percentile: the true peak is a handful of pixels and
# flattens the whole field if used as vmax.
vmax = float(np.percentile(cpu, 99.5))
vmin = -0.02 * vmax
dmax = float(np.percentile(np.abs(diff), 99.5))

fig, ax = plt.subplots(1, 3, figsize=(16, 5.2))
for a, d, t in ((ax[0], cpu, "Mac CPU restored"), (ax[1], gpu, "Mac GPU (-mgpu) restored")):
    im = a.imshow(d, origin="lower", cmap="inferno", vmin=vmin, vmax=vmax,
                  interpolation="nearest")
    a.set_title(t)
    a.set_xticks([]); a.set_yticks([])
fig.colorbar(im, ax=ax[1], fraction=0.046, pad=0.02,
             label="Jy/beam  (vmax = p99.5 = %.1f)" % vmax)

im2 = ax[2].imshow(diff, origin="lower", cmap="RdBu_r", vmin=-dmax, vmax=dmax,
                   interpolation="nearest")
ax[2].set_title("GPU - CPU  (max %.3g, p99.5 %.3g Jy/beam)" %
                (np.abs(diff).max(), dmax))
ax[2].set_xticks([]); ax[2].set_yticks([])
fig.colorbar(im2, ax=ax[2], fraction=0.046, pad=0.02, label="Jy/beam")

fig.suptitle("LWA 64 MHz 4-slot, exo-pipe-style deep clean: 4096px, 2amin, multiscale, "
             "niter 20000, mgain 0.95, auto-mask 3, local-rms")
fig.tight_layout()
out = "/Users/peijinz/dev/wsclean-mx/bench/out/exp4k-cpu-gpu.png"
fig.savefig(out, dpi=90)
print("wrote %s | peak %.3f | vmax(99%%) %.3f | diff max %.3g | diff 99%% %.3g | rel_rms %.3g"
      % (out, cpu.max(), vmax, np.abs(diff).max(), dmax,
         np.sqrt((diff ** 2).mean()) / cpu.max()))
