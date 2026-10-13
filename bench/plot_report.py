#!/usr/bin/env python3
"""Render the benchmark figures in docs/bench/ from runs in bench/out/.

    bench/plot_report.py

Each figure is skipped (with a note) if its input runs are missing.
"""

import csv
import re
import statistics
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "out"
DOCS = ROOT / "docs" / "bench"
sys.path.insert(0, str(ROOT / "bench"))
from compare_fits import compare  # noqa: E402
from sample_tree import inclusive  # noqa: E402

STAGES = ["inversion", "prediction", "deconvolution", "other"]
COLORS = {"inversion": "#4C72B0", "prediction": "#55A868",
          "deconvolution": "#C44E52", "other": "#8C8C8C"}


def hms(s):
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def run_stats(run_dir):
    """Wall and stage times of a single bench/run.sh output directory."""
    log = (run_dir / "wsclean.log").read_text()
    m = re.findall(r"Inversion: ([\d:.]+), prediction: ([\d:.]+), deconvolution: ([\d:.]+)", log)
    wall = float(re.search(r"^real ([\d.]+)", (run_dir / "time.txt").read_text(), re.M)[1])
    inv, pred, dec = (hms(x) for x in m[-1])
    return {"wall": wall, "inversion": inv, "prediction": pred, "deconvolution": dec}


def ab_min(tsv, variant):
    """Per-column minimum over repeats from a bench/ab.sh table."""
    rows = [r for r in csv.DictReader(open(tsv), delimiter="\t") if r["variant"] == variant]
    if not rows:
        return None
    return {k: min(float(r[k]) for r in rows) for k in ["wall", "inversion", "prediction", "deconvolution"]}


def with_other(s):
    s = dict(s)
    s["other"] = max(s["wall"] - s["inversion"] - s["prediction"] - s["deconvolution"], 0)
    return s


def fig_stages():
    entries = []
    if (OUT / "b4k" / "linc").exists():
        entries.append(("LINC 5.2.1\n(x86, Rosetta)", run_stats(OUT / "b4k" / "linc")))
    if (OUT / "p1-ab.tsv").exists():
        entries.append(("upstream\n(native arm64)", ab_min(OUT / "p1-ab.tsv", "upstream")))
        entries.append(("mx: patch 1", ab_min(OUT / "p1-ab.tsv", "mx")))
    if (OUT / "p2-ab.tsv").exists() and ab_min(OUT / "p2-ab.tsv", "mx"):
        entries.append(("mx: patch 1\n+ candidate vForce", ab_min(OUT / "p2-ab.tsv", "mx")))
    if not entries:
        return None
    entries = [(n, with_other(s)) for n, s in entries]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    names = [n for n, _ in entries]
    left = [0] * len(entries)
    for st in STAGES:
        vals = [s[st] for _, s in entries]
        ax.barh(names, vals, left=left, color=COLORS[st], label=st)
        left = [a + b for a, b in zip(left, vals)]
    base = next((s["wall"] for n, s in entries if n.startswith("upstream")), None)
    for i, (_, s) in enumerate(entries):
        txt = f"{s['wall']:.1f} s"
        if base:
            txt += f"  ({base / s['wall']:.2f}x vs upstream)"
        ax.text(s["wall"] + 0.3, i, txt, va="center", fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("wall time [s] (native: min of 3 alternating runs)")
    ax.set_title("4096² Stokes I, 1000 iterations, OVRO-LWA 50 MHz snapshot, M2 8 threads")
    ax.set_xlim(0, max(s["wall"] for _, s in entries) * 1.35)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return save(fig, "stages.png")


def fig_scaling():
    pts = []
    for j in [1, 2, 4, 6, 8]:
        d = OUT / f"scale-j{j}" / "upstream"
        if d.exists():
            pts.append((j, with_other(run_stats(d))))
    if not pts:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 4))
    js = [j for j, _ in pts]
    for st in ["wall"] + STAGES[:3]:
        ax.plot(js, [s[st] for _, s in pts], "o-", label=st, color=COLORS.get(st, "black"))
    t1 = pts[0][1]["wall"]
    ax.plot(js, [t1 / j for j in js], ":", color="gray", label="ideal (wall)")
    ax.axvspan(4.5, 8.5, color="orange", alpha=0.08)
    ax.text(6.5, t1 * 0.9, "E-cores", ha="center", color="darkorange")
    ax.set_xlabel("-j (threads)")
    ax.set_ylabel("time [s]")
    ax.set_title("Upstream thread scaling on M2 (4P + 4E), 4096²")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return save(fig, "scaling_upstream.png")


PROFILE_CATS = [
    ("ducc0 gridding", r"x2grid"),
    ("ducc0 degridding", r"grid2x"),
    ("ducc0 FFT", r"ducc0::detail_fft"),
    ("FFTW", r"fftwf|FftR2CComposite|FftC2RComposite"),
    ("sin/cos (libm)", r"sincosf"),
    ("mutex wait", r"psynch_mutexwait"),
    ("MS reordering", r"MsHelper::PerformReordering"),
]


def profile_split(sample):
    pats = [p for _, p in PROFILE_CATS]
    totals, thread_total, thread_idle = inclusive(sample, pats)
    busy = sum(thread_total.values()) - sum(thread_idle.values())
    # Categories can nest (e.g. FFTW inside reordering is impossible, but sin/cos
    # sits inside gridding); report leaf-ish categories exclusively by subtracting
    # sin/cos and mutex from gridding.
    cat = {name: sum(totals[p].values()) / 1000 for name, p in PROFILE_CATS}
    for inner in ["sin/cos (libm)", "mutex wait"]:
        cat["ducc0 gridding"] -= min(cat[inner], cat["ducc0 gridding"])
    cat["other busy"] = busy / 1000 - sum(cat.values())
    return cat


def fig_profile():
    runs = [("upstream", OUT / "prof4k" / "upstream-profile" / "sample.txt"),
            ("mx: patch 1", OUT / "prof4k" / "mx-profile" / "sample.txt")]
    runs = [(n, p) for n, p in runs if p.exists()]
    if not runs:
        return None
    data = [(n, profile_split(p)) for n, p in runs]
    cats = list(data[0][1].keys())
    cmap = plt.get_cmap("tab10")
    fig, ax = plt.subplots(figsize=(8, 3.2))
    left = [0] * len(data)
    for i, c in enumerate(cats):
        vals = [d[c] for _, d in data]
        ax.barh([n for n, _ in data], vals, left=left, color=cmap(i), label=c)
        left = [a + b for a, b in zip(left, vals)]
    ax.invert_yaxis()
    ax.set_xlabel("busy CPU time summed over threads [s] (macOS sample, 1 ms)")
    ax.set_title("Where the CPU time goes, 4096² run")
    ax.legend(fontsize=7, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.28))
    fig.tight_layout()
    return save(fig, "profile.png")


def fig_accuracy():
    up = [OUT / f"p1-r{i}" / "upstream" for i in (1, 2, 3)]
    groups = [
        ("upstream vs upstream (reruns)",
         [(up[a], up[b]) for a, b in [(0, 1), (0, 2), (1, 2)]]),
        ("LINC vs upstream", [(OUT / "b4k" / "linc", OUT / "b4k" / "upstream")]),
        ("mx patch 1 vs upstream",
         [(u, OUT / f"p1-r{i + 1}" / "mx") for i, u in enumerate(up)]),
        ("mx patch 1 + candidate vForce vs upstream",
         [(u, OUT / f"p2-r{i + 1}" / "mx") for i, u in enumerate(up)]),
    ]
    groups = [(n, [(a, b) for a, b in pairs if a.exists() and b.exists()]) for n, pairs in groups]
    groups = [(n, pairs) for n, pairs in groups if pairs]
    if not groups:
        return None
    products = ["dirty", "psf", "model", "residual", "image"]
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    width = 0.8 / len(groups)
    for i, (label, pairs) in enumerate(groups):
        med, lo, hi = [], [], []
        for p in products:
            vals = [compare(a / f"img-{p}.fits", b / f"img-{p}.fits")["rel_rms"] for a, b in pairs]
            m = statistics.median(vals)
            med.append(m)
            lo.append(m - min(vals))
            hi.append(max(vals) - m)
        xs = [k + i * width for k in range(len(products))]
        ax.bar(xs, med, width, label=f"{label} (n={len(pairs)})")
        ax.errorbar(xs, med, yerr=[lo, hi], fmt="none", ecolor="black", capsize=2, lw=0.8)
    ax.set_yscale("log")
    ax.set_xticks([k + width * (len(groups) - 1) / 2 for k in range(len(products))], products)
    ax.set_ylabel("rms(diff) / rms(reference)")
    ax.set_title("Image agreement, 4096² with deconvolution: median, whiskers = min..max")
    ax.legend(fontsize=7.5, loc="upper left")
    fig.tight_layout()
    return save(fig, "accuracy.png")


DEEP_RUNS = [("d4k-n2k", "Högbom, niter 2000"), ("d4k-n5k", "Högbom, niter 5000"),
             ("d4k-ms5k", "multiscale, niter 5000")]


def fig_deep():
    rows = []
    for tag, label in DEEP_RUNS:
        tsv = OUT / f"{tag}-ab.tsv"
        if not tsv.exists():
            continue
        for variant, name in [("upstream-fix", "upstream"), ("mx-p3", "mx")]:
            s = ab_min(tsv, variant)
            if s:
                rows.append((f"{label}\n{name}", with_other(s), tag))
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    names = [n for n, _, _ in rows]
    left = [0] * len(rows)
    for st in STAGES:
        vals = [s[st] for _, s, _ in rows]
        ax.barh(names, vals, left=left, color=COLORS[st], label=st)
        left = [a + b for a, b in zip(left, vals)]
    base = {tag: s["wall"] for n, s, tag in rows if n.endswith("upstream")}
    for i, (n, s, tag) in enumerate(rows):
        txt = f"{s['wall']:.1f} s"
        if n.endswith("mx") and tag in base:
            txt += f"  ({base[tag] / s['wall']:.2f}x)"
        ax.text(s["wall"] + 0.8, i, txt, va="center", fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("wall time [s] (min of 2 alternating runs)")
    ax.set_title("4096², briggs 0, mgain 0.8: upstream (+padding fix) vs mx patches 1+3+4")
    ax.set_xlim(0, max(s["wall"] for _, s, _ in rows) * 1.25)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return save(fig, "deep.png")


def fig_smallinv_bug():
    base = OUT / "smallinv-bug"
    panels = [("upstream-garbage", "upstream, unlucky run (own scale)\n(noise est. 6.52 mJy)"),
              ("upstream-lucky", "upstream, run that looked fine\n(25.35 µJy) minus LINC"),
              ("upstream-fix", "upstream + padding fix\n(24.54 µJy) minus LINC")]
    if not all((base / p / "img-dirty.fits").exists() for p, _ in panels + [("linc", "")]):
        return None
    from astropy.io import fits

    def load(p):
        img = fits.getdata(base / p / "img-dirty.fits").squeeze().astype("float64")
        c = img.shape[0] // 2
        return img[c - 256:c + 256, c - 256:c + 256]

    def sigma(x):
        return 1.4826 * float(np.median(np.abs(x - np.median(x))))

    linc = load("linc")
    lim = 5 * sigma(linc)
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6))
    axes[0].imshow(linc, origin="lower", cmap="gray", vmin=-lim, vmax=lim, interpolation="nearest")
    axes[0].set_title("LINC dirty image (reference)", fontsize=9)
    for ax, (p, title) in zip(axes[1:], panels):
        img = load(p)
        if p == "upstream-garbage":
            ax.imshow(img, origin="lower", cmap="gray", vmin=-5 * sigma(img), vmax=5 * sigma(img),
                      interpolation="nearest")
        else:
            ax.imshow(img - linc, origin="lower", cmap="gray", vmin=-lim / 5, vmax=lim / 5,
                      interpolation="nearest")
        rel = (img - linc).std() / linc.std()
        ax.set_title(f"{title}\nrms(diff)/rms(LINC) = {rel:.1e}", fontsize=9)
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("2048² dirty image (central 512²), small inversion, -j 2. LINC at ±5σ (MAD); "
                 "difference panels at ±1σ of LINC", fontsize=10)
    fig.tight_layout()
    return save(fig, "smallinv_bug.png")


def fig_multiscale():
    variants = [("LINC (reference)", OUT / "d4k-ms5k-iso" / "linc"),
                ("upstream", OUT / "d4k-ms5k-r1" / "upstream-fix"),
                ("upstream rerun", OUT / "d4k-ms5k-r2" / "upstream-fix"),
                ("upstream, Convolve\nscale +1 ulp", OUT / "d4k-ms5k-iso" / "upstream-fix-ulp"),
                ("mx patch 1", OUT / "d4k-ms5k-iso" / "mx-p1"),
                ("mx patches 1+3", OUT / "d4k-ms5k-iso" / "mx-p1c"),
                ("mx patches 1+3+4", OUT / "d4k-ms5k-r1" / "mx-p3"),
                ("mx patches 1+3+4 rerun", OUT / "d4k-ms5k-r2" / "mx-p3")]
    variants = [(n, p) for n, p in variants if (p / "img-model.fits").exists()]
    if len(variants) < 2:
        return None
    from astropy.io import fits

    def load(p, k):
        return fits.getdata(p / f"img-{k}.fits").squeeze().astype("float64")

    ref_res = load(variants[0][1], "residual")
    flux = [load(p, "model").sum() for _, p in variants]
    diff = [max((load(p, "residual") - ref_res).std() / ref_res.std(), 1e-7)
            for _, p in variants]
    names = [n for n, _ in variants]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    a1.barh(names, flux, color="#4C72B0")
    a1.set_xlim(min(flux) * 0.99, max(flux) * 1.005)
    a1.set_xlabel("total model flux [Jy]")
    a2.barh(names, diff, color="#C44E52")
    a2.set_xscale("log")
    a2.set_xlabel("rms(residual - LINC residual) / rms(LINC residual)")
    for a in (a1, a2):
        a.invert_yaxis()
    a2.set_yticks([])
    fig.suptitle("Multiscale clean (4096², niter 5000) is chaotic: a 1-ulp change in upstream's "
                 "Convolve already moves it 0.8% in flux, 3.5x the LINC-upstream gap",
                 fontsize=10)
    fig.tight_layout()
    return save(fig, "multiscale_sensitivity.png")


def save(fig, name):
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / name
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def main():
    for f in [fig_stages, fig_scaling, fig_profile, fig_accuracy, fig_deep, fig_smallinv_bug,
              fig_multiscale]:
        path = f()
        print(f"{f.__name__}: {path.relative_to(ROOT) if path else 'skipped (no data)'}")


if __name__ == "__main__":
    main()
