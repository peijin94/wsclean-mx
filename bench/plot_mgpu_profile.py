import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

versions = ["12 fixed\nchunks", "adaptive\nchunks", "+ GCD plane\ngather", "+ parallel\nitem+extract"]
times = [19.3, 8.4, 7.4, 6.8]
cpu = 1.2

fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))

bars = ax[0].bar(versions, times, color=["#c0392b", "#e67e22", "#2980b9", "#27ae60"])
ax[0].axhline(cpu, color="k", linestyle="--", label="CPU ducc0 (1.2 s)")
ax[0].set_ylabel("inversion time (s)")
ax[0].set_title("LWA 4-slot dirty: -mgpu optimization path")
ax[0].legend()
for b, t in zip(bars, times):
    ax[0].text(b.get_x() + b.get_width() / 2, t + 0.3, "%.1f s" % t, ha="center")

stages = ["item+bucket\n(GCD)", "gather\n(GCD)", "Metal grid\n(gpu 2.5)", "roll+FFT\n(CPU)", "other"]
stage_t = [0.7, 0.4, 2.7, 0.5, 2.5]
ax[1].bar(stages, stage_t, color="#2980b9")
ax[1].set_ylabel("seconds")
ax[1].set_title("Stage breakdown, latest (6.8 s total)")
for x, t in zip(stages, stage_t):
    ax[1].text(x, t + 0.05, "%.1f" % t, ha="center", fontsize=9)

fig.tight_layout()
fig.savefig("/Users/peijinz/dev/wsclean-mx/bench/out/mgpu-profile.png", dpi=90)
print("wrote mgpu-profile.png")
