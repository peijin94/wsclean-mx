# Science acceptance gates — reference-envelope comparison

**Created:** 2026-10-18 (EDT). **Tool:** `bench/compare_sources.py`. **Status:** gates defined and first measurements taken; the cleaned-product question below is **not** settled.

Pixel RMS is not a science gate. Multiscale cleaning is chaotic — the same binary lands at different cleaned images from run to run — so a candidate can differ from the reference by more than the reference differs from itself while still being scientifically equivalent, and vice versa. This document defines measurements that describe the products themselves (flux, position, size), and judges the candidate against the **reference's own run-to-run envelope** rather than against a pixel threshold chosen after seeing a failure.

## Predeclared method

`bench/compare_sources.py --candidate DIR REFERENCE_DIR [REFERENCE_DIR ...]` walks every `img-*.fits` product common to all directories and measures:

| Metric | Definition |
|---|---|
| `total_flux` | sum over all pixels |
| `peak`, `peak_x`, `peak_y` | brightest pixel and its position |
| `mad_rms` | 1.4826 × median absolute deviation about the median |
| `second_moment` | sqrt(Σ r² I / Σ I) about the peak: a size/PSF proxy |
| matched-source flux | sources ≥ 6σ (MAD) in each image, nearest-neighbour matched within 3 px; worst flux-ratio deviation |
| source position | worst matched-pair distance in pixels |

**Decision rule (predeclared):** for every metric, the candidate's deviation from the reference *median* must not exceed

`max(reference envelope, 1e-5 relative)` for scalar metrics, and `max(reference pair envelope, 0 px)` for positions,

where the **reference envelope** is the largest deviation observed between *reference reruns themselves*. Nothing is compared to the candidate, so the envelope is independent of what is being judged. Exit status is non-zero on any failure, so this is a gate, not a report.

**The numerical floor is 1e-5 relative.** It exists because the products are 32-bit FITS: sums over ~4M pixels carry ~1e-6 relative rounding before any algorithmic difference. It was added after the first run flagged dirty/PSF deviations of ~3e-6 as failures — i.e. it is justified by storage precision, not by the results below, and it cannot hide them: every cleaned-product deviation below is 3–4 orders of magnitude larger.

**Known limits.** The envelope comes from a small number of reruns (3–4 per reference), so it is a sampled spread, not a confidence interval. Source matching is only informative on a field with real sources; the current OVRO-LWA snapshot is a 10 s full-sky quiet-Sun integration whose "sources" are noise peaks, and its matched-source envelopes are large (tens of percent), which reflects that, not science.
Because the spread is sampled, quantities that are intrinsically mobile (residual-image
peak position) carry envelopes of the same order as the observed deviations, so one
more sample can flip such a check either way. That is an argument for widening the
envelope, not for excluding the metric.

## Results: 4096² dirty (niter 0), 8 threads

Candidate `mx-p11` run r1 against three `upstream-fix` reruns (r1–r3), `-size 4096 4096 -scale 0.03125 -weight briggs 0 -niter 0`:

**GATE PASSED.** Every metric — total flux, peak, peak position, MAD rms, second moment, matched sources, positions — agrees within the reference envelope, at deviations of ~1e-7 relative (float-rounding level). For a dirty image the optimization stack is numerically indistinguishable from the fixed reference on this dataset.

Source detection is identical on both sides (same count, all matched, none
unmatched, zero position offset), so the agreement is not an artefact of
detecting different peaks.

## Results: 2048² multiscale (niter 3000), 8 threads

Candidate `mx-p11` (three of its own reruns individually) against three `upstream-fix` reruns:

**GATE FAILED on integral metrics of the cleaned products.**

The failure list is exactly the eight integral entries below. The source-level
checks themselves pass on every product (matched flux, positions and unmatched
counts all inside the reference pairs' envelopes); it is the aggregate
properties of the cleaned images that differ more than the reference differs
from itself.

| Product | Metric | mx deviation | Reference envelope | Result |
|---|---|---:|---:|---|
| `img-image` | total flux | 3.6e-2 | 1.0e-2 | FAIL |
| `img-image` | MAD rms | 1.6e-4 | 8.4e-5 | FAIL |
| `img-image` | second moment | 1.5e-3 | 5.1e-4 | FAIL |
| `img-model` | total flux | 2.5e-2 | 1.0e-2 | FAIL |
| `img-model` | MAD rms | 8.3e-2 | 7.9e-3 | FAIL |
| `img-model` | second moment | 2.6e-2 | 4.2e-3 | FAIL |
| `img-residual` | total flux | 1.6e-1 | 1.9e-2 | FAIL |
| `img-residual` | MAD rms | 7.2e-4 | 5.1e-4 | FAIL |
| `img-dirty`, `img-psf` | all | ≤1e-6 | (float32 floor) | PASS |

Matched-source flux and position checks pass, but with reference envelopes of ~47 % flux and ~2.2 px, so they carry little information on this field.

**Interpretation.** This reproduces, with a source-level method instead of pixel RMS, the earlier audit finding: the multiscale *cleaned* products differ from the fixed reference by more than the reference's own sampled rerun spread, while dirty/PSF products agree to rounding. It is **not** evidence that the sources are wrong, and it is not a threshold to relax: cleaning is chaotic, and 3 reruns are a weak estimate of its spread. What would move this forward, in order:

The three `mx-p11` reruns were each run as the candidate separately, and all three fail
the same metrics by the same amounts (restored-image total flux 3.6 %, 3.9 %, 3.6 %;
model MAD rms 8.3 %, 8.4 %, 8.6 %; residual total flux 16.2 %, 16.2 %, 16.3 % against
envelopes of 1.0 %, 0.8 %, 1.9 %). The difference is therefore **systematic for this
stack on this dataset**, not one unlucky run.

One further metric tripped in a single rerun: the r2 candidate's residual-image peak
row (8.1e-2 deviation against a 6.8e-2 envelope). That quantity is the brightest
un-cleaned artefact rather than a source, and the reference reruns already scatter by
7 % there, so it sits near the boundary and is recorded rather than explained away —
it is a different class of failure from the eight systematic ones.

What would move this forward, in order:

1. Widen the reference envelope (many more reruns, and the perturbed-reference `upstream-fix-ulp` build) so "chaotic spread" is measured rather than guessed.
2. Repeat on a field with real sources (a calibrator or a bright event) where flux-ratio and position gates have physical meaning.
3. Only then decide whether the stack needs a fix, a documented caveat, or acceptance.

## Results: patch 12 (conditional multiscale scratch) — neutral at source level

Candidate `audit-p12-scratch` against four `audit-p11-fresh` reruns of the immediately
preceding stack (4-round envelope), 2048² multiscale, 8 threads:

**GATE PASSED.** Every metric of every product is inside the p11 reference envelope:

| Product | Metric | p12 deviation | Reference envelope |
|---|---|---:|---:|
| `img-image` | total flux | 3.5e-3 | 5.6e-2 |
| `img-image` | MAD rms | 4.4e-6 | 3.9e-4 |
| `img-image` | second moment | 3.9e-5 | 1.4e-3 |
| `img-model` | total flux | 3.1e-3 | 4.8e-2 |
| `img-model` | second moment | 1.8e-4 | 2.4e-2 |
| `img-residual` | total flux | 8.4e-3 | 1.6e-1 |
| `img-residual` | MAD rms | 2.5e-5 | 8.6e-4 |

So the one change still awaiting a scientific verdict — patch 12's allocation
optimization — is source-level neutral, matching its earlier bitwise equivalence at
`-j 1`. The open question is the older FFT/deconvolution stack, not patch 12.
Its source detection also matches the reference reruns (no unmatched sources in
the restored image; the model matches all but within the envelope).

## Evidence

Local, gitignored: `bench/out/throttle-20261018/sources-*-final.json` and
`-final.log` (final tool revision, including the unmatched-source check);
products under `bench/out/audit-20261017-*`. Commands to reproduce are in the
logs; the reference products came from the 2026-10-17 audit runs.

## Status of the wider release question

Correctness (tests, selection, allocation, time units) is repaired and reviewed. Performance was re-measured and the earlier regression retracted (see `throttle-validation-2026-10-18.md`). **Scientific acceptance of the multiscale stack remains open** and is now expressed in measurable terms above instead of pixel RMS.
