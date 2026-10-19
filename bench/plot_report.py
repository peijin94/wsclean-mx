#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Render the benchmark figures in docs/bench/ from runs in bench/out/.

    bench/plot_report.py

Each figure is skipped (with a note) if its input runs are missing. Wall-time
ratios are annotated with bench/ab.sh's mode assessment: a ratio is only read as
a variant cost where the mode file says `comparable`, and figures without mode
files are labelled wall-clock only.
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


def mode_status(tag, out=OUT):
    """bench/ab.sh's verdict for a tag, read from <tag>-ab.mode.txt.

    Returns 'comparable', 'stall mode mismatch', 'unclassified', 'absent'
    (no mode file: the comparison predates the counter harness) or
    'unrecognised' (a mode file whose first line this plotter does not know,
    treated as unclassified by callers).
    """
    path = out / f"{tag}-ab.mode.txt"
    if not path.exists():
        return "absent"
    first = next((line.strip() for line in path.read_text().splitlines() if line.strip()), "")
    if first == "comparable":
        return "comparable"
    if "stall mode mismatch" in first:
        return "stall mode mismatch"
    if "unclassified" in first or first == "single variant: nothing to compare":
        return "unclassified"
    return "unrecognised"


def ratio_note(tag, out=OUT):
    """Suffix for a wall-ratio annotation on a figure."""
    status = mode_status(tag, out)
    if status == "comparable":
        return ""
    if status == "absent":
        return " [no mode file: wall-clock only]"
    return f" [{status}]"


def figure_mode_note(tags, out=OUT):
    """One line naming every comparison that is not mode-verified."""
    statuses = {tag: mode_status(tag, out) for tag in tags}
    if all(status == "comparable" for status in statuses.values()):
        return "mode-verified: hardware counters comparable for every comparison"
    problems = ", ".join(f"{tag}={status}" for tag, status in statuses.items()
                         if status != "comparable")
    return f"wall-clock only where not mode-verified: {problems}"


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
        entries.append(("LINC 5.2.1\n(x86, Rosetta)", run_stats(OUT / "b4k" / "linc"), "b4k"))
    if (OUT / "p1-ab.tsv").exists():
        entries.append(("upstream\n(native arm64)", ab_min(OUT / "p1-ab.tsv", "upstream"), "p1"))
        entries.append(("mx: patch 1", ab_min(OUT / "p1-ab.tsv", "mx"), "p1"))
    if (OUT / "p2-ab.tsv").exists() and ab_min(OUT / "p2-ab.tsv", "mx"):
        entries.append(("mx: patch 1\n+ candidate vForce", ab_min(OUT / "p2-ab.tsv", "mx"), "p2"))
    if not entries:
        return None
    entries = [(n, with_other(s), t) for n, s, t in entries]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    names = [n for n, _, _ in entries]
    left = [0] * len(entries)
    for st in STAGES:
        vals = [s[st] for _, s, _ in entries]
        ax.barh(names, vals, left=left, color=COLORS[st], label=st)
        left = [a + b for a, b in zip(left, vals)]
    base = next((s["wall"] for n, s, _ in entries if n.startswith("upstream")), None)
    for i, (_, s, tag) in enumerate(entries):
        txt = f"{s['wall']:.1f} s"
        if base:
            txt += f"  ({base / s['wall']:.2f}x vs upstream)" + ratio_note(tag)
        ax.text(s["wall"] + 0.3, i, txt, va="center", fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("wall time [s] (native: min of 3 alternating runs)\n"
                  + figure_mode_note([tag for _, _, tag in entries]))
    ax.set_title("4096² Stokes I, 1000 iterations, OVRO-LWA 50 MHz snapshot, M2 8 threads")
    ax.set_xlim(0, max(s["wall"] for _, s, _ in entries) * 1.35)
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
            txt += f"  ({base[tag] / s['wall']:.2f}x)" + ratio_note(tag)
        ax.text(s["wall"] + 0.8, i, txt, va="center", fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("wall time [s] (min of 2 alternating runs)\n"
                  + figure_mode_note(sorted({tag for _, _, tag in rows})))
    ax.set_title("4096², briggs 0, mgain 0.8: upstream (+padding fix) vs mx patches 1+3+4")
    ax.set_xlim(0, max(s["wall"] for _, s, _ in rows) * 1.25)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return save(fig, "deep.png")


P6_RUNS = [("p6-n5k", "4096² Högbom\nniter 5000"), ("p6-ms2k", "2048² multiscale\nniter 5000")]
P6_VARIANTS = [("upstream-fix", "upstream"), ("mx-p3", "mx p1+3+4"), ("mx-p6", "mx p1+3+4+5+6")]


def fig_subminor():
    rows = []
    for tag, label in P6_RUNS:
        tsv = OUT / f"{tag}-ab.tsv"
        if not tsv.exists():
            continue
        for variant, name in P6_VARIANTS:
            s = ab_min(tsv, variant)
            if s:
                rows.append((f"{label}, {name}", with_other(s), tag, variant))
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(9, 4.6))
    names = [n for n, _, _, _ in rows]
    left = [0] * len(rows)
    for st in STAGES:
        vals = [s[st] for _, s, _, _ in rows]
        ax.barh(names, vals, left=left, color=COLORS[st], label=st)
        left = [a + b for a, b in zip(left, vals)]
    base = {tag: s for _, s, tag, v in rows if v == "upstream-fix"}
    for i, (_, s, tag, v) in enumerate(rows):
        txt = f"{s['wall']:.1f} s"
        if v != "upstream-fix" and tag in base:
            b = base[tag]
            txt += (f"  (wall {b['wall'] / s['wall']:.2f}x, "
                    f"deconv {b['deconvolution'] / s['deconvolution']:.1f}x)"
                    + ratio_note(tag))
        ax.text(s["wall"] + 0.5, i, txt, va="center", fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("wall time [s] (min of 2 alternating runs; multiscale runs were thermally noisy)\n"
                  + figure_mode_note(sorted({tag for _, _, tag, _ in rows})))
    ax.set_title("Patches 5+6: multithreaded subminor loop, multiscale FFT reuse")
    ax.set_xlim(0, max(s["wall"] for _, s, _, _ in rows) * 1.6)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return save(fig, "subminor.png")


PLATFORM_RUNS = ["ms2k-n3k-r1", "ms2k-n3k-r2"]
PLATFORM_VARIANTS = [
    ("mx-p6", "wsclean-mx, M2 (8 threads)"),
    ("upstream-fix", "upstream + fix, M2 (8 threads)"),
    ("linc", "LINC 5.2.1, M2 Rosetta (8 threads)"),
    ("linux-j8", "LINC 5.2.1, Xeon 4214 (-j 8)"),
    ("linux-j24", "LINC 5.2.1, Xeon 4214 (-j 24)"),
]


def fig_platforms():
    runs = {v: [OUT / t / v for t in PLATFORM_RUNS if (OUT / t / v / "img-residual.fits").exists()]
            for v, _ in PLATFORM_VARIANTS}
    if not all(runs.values()):
        return None
    from astropy.io import fits

    def best(dirs):
        stats = [run_stats(d) for d in dirs]
        return with_other({k: min(s[k] for s in stats) for k in stats[0]})

    rows = [(name, best(runs[v])) for v, name in PLATFORM_VARIANTS]
    ref = fits.getdata(runs["linc"][0] / "img-residual.fits").squeeze().astype("float64")
    spread = [(f"{name}, run {i + 1}" + (" (reference)" if (v, i) == ("linc", 0) else ""),
               max((fits.getdata(d / "img-residual.fits").squeeze() - ref).std() / ref.std(), 1e-7))
              for v, name in PLATFORM_VARIANTS for i, d in enumerate(runs[v])]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.2), width_ratios=[1.3, 1])
    names = [n for n, _ in rows]
    left = [0] * len(rows)
    for st in STAGES:
        vals = [s[st] for _, s in rows]
        a1.barh(names, vals, left=left, color=COLORS[st], label=st)
        left = [a + b for a, b in zip(left, vals)]
    mx = rows[0][1]["wall"]
    for i, (_, s) in enumerate(rows):
        a1.text(s["wall"] + 0.5, i, f"{s['wall']:.1f} s ({s['wall'] / mx:.1f}x)", va="center",
                fontsize=8)
    a1.invert_yaxis()
    a1.set_xlim(0, max(s["wall"] for _, s in rows) * 1.3)
    a1.set_xlabel("wall time [s], min of 2 runs (Xeon host shared, load avg 23-33)\n"
                  + figure_mode_note(sorted({t for t in PLATFORM_RUNS})))
    a1.legend(loc="upper right", fontsize=8)
    a1.set_title("Time", fontsize=10)
    a2.barh([n for n, _ in spread], [r for _, r in spread], color="#C44E52")
    a2.set_xscale("log")
    a2.invert_yaxis()
    a2.tick_params(axis="y", labelsize=7)
    a2.set_xlabel("rms(residual - LINC M2 run 1 residual) / rms(LINC residual)")
    a2.set_title("Residual vs LINC (multiscale is run-to-run chaotic)", fontsize=10)
    fig.suptitle("2048² at 0.0625° (full sky), multiscale, niter 3000, briggs 0, mgain 0.8",
                 fontsize=11)
    fig.tight_layout()
    return save(fig, "platforms_ms2k.png")


P11_PANELS = [
    ("p11-final-ms2k-ab.tsv", "2048² multiscale, niter 3000 (cleaning: reorders the MS)"),
    ("p11-final-inv4k-ab.tsv", "4096² dirty image, niter 0 (reads the MS directly)"),
]
P11_VARIANTS = [("upstream-fix", "upstream + fix"), ("mx-p6", "wsclean-mx-p6"),
                ("mx-p11", "wsclean-mx-p11")]


def fig_p11():
    if not all((OUT / t).exists() for t, _ in P11_PANELS):
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.6))
    for ax, (tsv, title) in zip(axes, P11_PANELS):
        rows = [(name, with_other(ab_min(OUT / tsv, v))) for v, name in P11_VARIANTS]
        names = [n for n, _ in rows]
        left = [0] * len(rows)
        for st in STAGES:
            vals = [s[st] for _, s in rows]
            ax.barh(names, vals, left=left, color=COLORS[st], label=st)
            left = [a + b for a, b in zip(left, vals)]
        base = rows[0][1]["wall"]
        for i, (_, s) in enumerate(rows):
            note = ratio_note(tsv.replace("-ab.tsv", ""))
            ax.text(s["wall"] + base * 0.01, i, f"{s['wall']:.2f} s ({base / s['wall']:.2f}x){note}",
                    va="center", fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, base * 1.3)
        ax.set_xlabel("wall time [s], min of 3 alternating runs, M2 8 threads\n"
                      + figure_mode_note([tsv.replace("-ab.tsv", "")]))
        ax.set_title(title, fontsize=10)
    axes[0].legend(loc="lower right", fontsize=8)
    fig.suptitle("Patches 7-11 (2026-10-17): wsclean-mx-p11 vs p6 vs upstream", fontsize=11)
    fig.tight_layout()
    return save(fig, "p11.png")


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


FULLSKY_MS_RUNS = ["fullsky-ms", "fullsky-ms-r2", "fullsky-ms-r3"]


def fig_fullsky():
    return fullsky("fullsky", "Högbom, niter 2000", "fullsky.png")


def fig_fullsky_multiscale():
    return fullsky("fullsky-ms", "multiscale, niter 5000", "fullsky_multiscale.png")


def fig_fullsky_ms_spread():
    variants = [("upstream", "upstream"), ("upstream-fix", "upstream + fix"),
                ("mx-p3", "wsclean-mx")]
    runs = [(t, v, n) for t in FULLSKY_MS_RUNS for v, n in variants
            if (OUT / t / v / "img-residual.fits").exists()]
    if not runs or not (OUT / "fullsky-ms" / "linc" / "img-residual.fits").exists():
        return None
    from astropy.io import fits

    def load(t, v):
        return fits.getdata(OUT / t / v / "img-residual.fits").squeeze().astype("float64")

    ref = load("fullsky-ms", "linc")
    rel = [max((load(t, v) - ref).std() / ref.std(), 1e-7) for t, v, _ in runs]
    colors = {"upstream": "#8C8C8C", "upstream-fix": "#4C72B0", "mx-p3": "#C44E52"}
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.barh([f"{n}, run {FULLSKY_MS_RUNS.index(t) + 1}" for t, v, n in runs], rel,
            color=[colors[v] for _, v, _ in runs])
    ax.set_xscale("log")
    ax.invert_yaxis()
    ax.set_xlabel("rms(residual - LINC residual) / rms(LINC residual)")
    ax.set_title("Full-sky multiscale (1024², niter 5000), repeated runs: run-to-run spread "
                 "(1e-6 to 5e-3)\nis the same for every build, so no build is closer to LINC "
                 "than another", fontsize=10)
    fig.tight_layout()
    return save(fig, "fullsky_multiscale_spread.png")


def fullsky(tag, clean, out_name):
    base = OUT / tag
    names = [("linc", "LINC"), ("upstream", "upstream"), ("mx-p3", "wsclean-mx")]
    if not all((base / v / "img-image.fits").exists() for v, _ in names):
        return None
    from astropy.io import fits

    def sigma(x):
        return 1.4826 * float(np.median(np.abs(x - np.median(x))))

    img = {v: np.nan_to_num(fits.getdata(base / v / "img-image.fits").squeeze().astype("float64"))
           for v, _ in names}
    ref = img["linc"]
    vmin, vmax = -3 * sigma(ref), np.percentile(ref, 99.95)
    pairs = [("upstream", "linc"), ("mx-p3", "linc"), ("mx-p3", "upstream")]
    diffs = [img[a] - img[b] for a, b in pairs]
    dlim = 5 * max(sigma(d) for d in diffs)
    label = dict(names)

    fig, axes = plt.subplots(2, 3, figsize=(13, 9.5), layout="constrained")
    for ax, (v, title) in zip(axes[0], names):
        ax.imshow(img[v], origin="lower", cmap="inferno", vmin=vmin, vmax=vmax,
                  interpolation="nearest")
        ax.set_title(f"{title} restored image", fontsize=10)
    for ax, (a, b), d in zip(axes[1], pairs, diffs):
        im = ax.imshow(d, origin="lower", cmap="RdBu_r", vmin=-dlim, vmax=dlim,
                       interpolation="nearest")
        ax.set_title(f"{label[a]} - {label[b]}\nrms(diff)/rms(LINC) = {d.std() / ref.std():.1e}\n"
                     f"max|diff|/peak = {np.abs(d).max() / ref.max():.1e}", fontsize=9)
    fig.colorbar(im, ax=axes[1].tolist(), shrink=0.8,
                 label=f"difference [Jy/beam]  (image noise ≈ {sigma(ref):.1e})")
    for ax in axes.flat:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f"Full-sky restored image, 1024² at 0.125° ({clean}, briggs 0).\n"
                 "Top: same colour scale. Bottom: differences at ±5σ (MAD) of the differences",
                 fontsize=11)
    return save(fig, out_name)


def save(fig, name):
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / name
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def main():
    for f in [fig_stages, fig_scaling, fig_profile, fig_accuracy, fig_deep, fig_smallinv_bug,
              fig_multiscale, fig_fullsky, fig_fullsky_multiscale, fig_fullsky_ms_spread,
              fig_subminor, fig_platforms, fig_p11]:
        path = f()
        print(f"{f.__name__}: {path.relative_to(ROOT) if path else 'skipped (no data)'}")


if __name__ == "__main__":
    main()
