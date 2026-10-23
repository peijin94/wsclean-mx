#!/usr/bin/env python3
"""Render measured CPU results and full-resolution image comparisons.

Run with the repository .venv. Image panels require the retained local FITS
products; their recorded hashes are checked before rendering.
"""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from astropy.io import fits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from report_validation import validate_report
COLORS = {"baseline": "#4c78a8", "candidate": "#e58b2b", "aa": "#62a89c"}
LABELS = {"baseline": "Baseline", "candidate": "Optimized", "aa": "Identical A/A control"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_image_pair(data, size):
    """Load/hash/validate the full-resolution arrays before any annotation."""
    images = []
    for role in ("baseline", "candidate"):
        item = data["figure_inputs"][str(size)][role]
        path = ROOT / item["path"]
        if digest(path) != item["sha256"]:
            raise ValueError(f"Changed figure input: {path}")
        image = np.array(fits.getdata(path), dtype=np.float64, copy=True).squeeze()
        if image.shape != (size, size):
            raise ValueError("Unexpected image geometry")
        images.append(image)
    reference, candidate = images
    if np.any(np.isinf(reference)) or np.any(np.isinf(candidate)):
        raise ValueError("Infinite image pixels")
    if not np.array_equal(np.isnan(reference), np.isnan(candidate)):
        raise ValueError("Mismatched image NaN masks")
    finite = np.isfinite(reference) & np.isfinite(candidate)
    if not np.any(finite):
        raise ValueError("No finite image coverage")
    difference = candidate - reference
    maximum = float(np.max(np.abs(difference[finite])))
    if maximum != 0:
        raise ValueError("Figure inputs disagree with recorded T0 result")
    return images, difference


def main():
    data = json.loads((HERE / "results.json").read_text())
    figure_gates = validate_report(data)
    runs = data["runs"]
    timed = [r for r in runs if r["phase"] == "timing"]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    panels = [("wall_s", "Whole imaging", "Seconds", 1),
              ("deconvolution_s", "CLEAN", "Seconds", 1),
              ("inversion_s", "Inversion (unchanged path)", "Seconds", 1),
              ("prediction_s", "Prediction (unchanged path)", "Seconds", 1),
              ("rss_bytes", "Peak resident memory", "GiB", 1024**3),
              ("instructions", "Retired instructions", "Trillions", 1e12)]
    for ax, (metric, title, unit, divisor) in zip(axes.flat, panels):
        for i, size in enumerate((3072, 4096)):
            for j, role in enumerate(COLORS):
                values = [r["timing"][metric] / divisor for r in timed
                          if r["size"] == size and r["role"] == role]
                if not all(np.isfinite(v) and v > 0 for v in values):
                    raise ValueError("Invalid plotted timing/resource value")
                x = i + (j - 1) * .22
                ax.scatter([x] * len(values), values, color=COLORS[role], s=35,
                           label=LABELS[role] if i == 0 else None)
                ax.plot([x - .07, x + .07], [statistics.median(values)] * 2,
                        color="black", linewidth=1.5)
        ax.set(xticks=[0, 1], xticklabels=["3072²", "4096²"], ylabel=unit, title=title)
        maximum = max(r["timing"][metric] / divisor for r in timed)
        ax.set_ylim(0, maximum * 1.10)
        ax.grid(axis="y", alpha=.2)
    axes[0, 0].legend(fontsize=8)
    modes = "; ".join(f"{s}: {data['modes'][str(s)]['status']}" for s in (3072, 4096))
    resolution = []
    for size in (3072, 4096):
        lines = [line for line in data["modes"][str(size)]["text"].splitlines()
                 if line.startswith("resolution:")]
        if len(lines) != 1:
            raise ValueError("Missing/duplicate classifier resolution caveat")
        resolution.append(textwrap.fill(f"{size} {lines[0]}", width=135))
    caption = ("150k cap, j8: all measured runs; marks = medians; warmups excluded\n" + modes
               + "\n" + "\n".join(resolution)
               + "\n4096 A/A: one sample; no repeatability estimate")
    fig.suptitle(caption, fontsize=10)
    fig.savefig(HERE / "performance.png", dpi=160)
    plt.close(fig)

    micro = data["micro"]
    if len(micro) != 12:
        raise ValueError("Incomplete masked microbenchmark")
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), constrained_layout=True)
    for ax, size in zip(axes, (3072, 4096)):
        rows = [r for r in micro if r["size"] == size]
        if len(rows) != 6:
            raise ValueError("Missing microbenchmark setting")
        for i, row in enumerate(rows):
            ax.bar(i - .18, row["baseline_ms"], .36, color=COLORS["baseline"],
                   label="Baseline" if i == 0 else None)
            ax.bar(i + .18, row["candidate_ms"], .36, color=COLORS["candidate"],
                   label="Optimized" if i == 0 else None)
        labels = [{1: "all", 3: "2/3", 16: "1/16"}[r["mask_stride"]] +
                  ("\n± peaks" if r["allow_negative"] else "\n+ peaks") for r in rows]
        ax.set(xticks=range(6), xticklabels=labels, ylabel="Milliseconds",
               title=f"{size}² synthetic masked scan")
        ax.set_ylim(0, 1.25 * max(max(r["baseline_ms"], r["candidate_ms"]) for r in rows))
        ax.grid(axis="y", alpha=.2)
        ax.legend()
    fig.suptitle("Single-call kernel microbenchmark: eight measurements per setting, warmup excluded")
    fig.savefig(HERE / "masked-microbenchmark.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(14, 9), constrained_layout=True)
    for row, size in enumerate((3072, 4096)):
        images, difference = load_image_pair(data, size)
        reference, candidate = images
        vmax = float(np.percentile(reference[np.isfinite(reference)], 99))
        if not np.isfinite(vmax) or vmax <= 0:
            raise ValueError("Invalid p99 image stretch")
        norm = Normalize(vmin=-.1 * vmax, vmax=vmax)
        for col, (image, label) in enumerate(zip(images, ("Baseline", "Optimized"))):
            rendered = axes[row, col].imshow(image, origin="lower", cmap="inferno", norm=norm)
            axes[row, col].set_title(f"{size}² {label}")
            fig.colorbar(rendered, ax=axes[row, col], shrink=.8,
                         label=f"Jy/beam; shared p99 vmax={vmax:.3g}")
        axes[row, 2].imshow(difference, origin="lower", cmap="RdBu_r", vmin=-1, vmax=1)
        axes[row, 2].set_title(f"{size}² optimized − baseline")
        gate = figure_gates[str(size)]["candidate"]
        annotation = ("Exactly zero on every finite pixel\n"
                      f"All {len(gate['products'])} products pass {gate['expected']}")
        axes[row, 2].text(.5, .5, annotation,
                          ha="center", va="center", transform=axes[row, 2].transAxes,
                          bbox=dict(facecolor="white", alpha=.9, edgecolor="#aaaaaa"))
        # No arbitrary colorbar for an identically zero difference field.
        for ax in axes[row]:
            ax.set_xlabel("Image x pixel")
            ax.set_ylabel("Image y pixel")
    fig.suptitle("Full-depth restored images: p99 stretch; differences evaluated at full resolution")
    fig.savefig(HERE / "image-consistency.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
