import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

fig, ax = plt.subplots(1, 3, figsize=(16, 4.2))

# Left: optimization path
versions = ["12 fixed\nchunks", "adaptive\nchunks", "+ parallel\nprep+extract", "+ blit grid\nreuse"]
times = [19.3, 8.4, 7.4, 6.8]
bars = ax[0].bar(versions, times, color=["#c0392b", "#e67e22", "#2980b9", "#27ae60"])
ax[0].axhline(1.11, color="k", linestyle="--", label="CPU ducc0 (1.11 s)")
ax[0].set_ylabel("inversion time (s)")
ax[0].set_title("LWA 4-slot dirty: -mgpu optimization path")
ax[0].legend(fontsize=8)
for b, t in zip(bars, times):
    ax[0].text(b.get_x() + b.get_width() / 2, t + 0.3, "%.1f s" % t, ha="center", fontsize=9)

# Middle: thread scaling (50k subset, total GPU ms)
thr = [64, 128, 256, 512, 1024]
ms = [1566, 884, 598, 565, 595]
ax[1].plot(thr, ms, "o-", color="#2980b9")
ax[1].set_xscale("log", base=2)
ax[1].set_xticks(thr)
ax[1].set_xticklabels([str(t) for t in thr])
ax[1].set_xlabel("threads per group")
ax[1].set_ylabel("GPU ms (50k subset)")
ax[1].set_title("Thread scaling: plateaus at 256")
ax[1].grid(True, alpha=0.3)

# Right: CPU vs GPU by stage
labels = ["total", "grid", "FFT/extract", "prep/other"]
cpu = [1.11, 0.5, 0.4, 0.2]
gpu = [6.8, 3.1, 1.5, 2.2]
x = np.arange(len(labels))
w = 0.35
ax[2].bar(x - w / 2, cpu, w, label="CPU ducc0")
ax[2].bar(x + w / 2, gpu, w, label="GPU -mgpu")
ax[2].set_xticks(x)
ax[2].set_xticklabels(labels, fontsize=9)
ax[2].set_ylabel("seconds")
ax[2].set_title("CPU vs GPU by stage (4-slot)")
ax[2].legend(fontsize=8)

fig.suptitle("Metal -mgpu benchmark: bottleneck is GPU grid kernel (46%) + host prep")
fig.tight_layout()
fig.savefig("/Users/peijinz/dev/wsclean-mx/bench/out/mgpu-profile.png", dpi=90)
print("wrote mgpu-profile.png")
