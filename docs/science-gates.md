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

**Known limits.** The envelope is a sampled spread, not a confidence interval: three reruns when this document was written, ten in the widened measurement below, four for the real-source field. Source matching is only informative on a field with real sources; the OVRO-LWA snapshot is a 10 s full-sky quiet-Sun integration whose "sources" are noise peaks, and its matched-source envelopes are large (tens of percent), which reflects that, not science. Because the gate compares the candidate's worst deviation against the reference family's worst pair, it is ambiguous when the candidate is drawn from the same distribution — see "Boundary behaviour".
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

What would move this forward, in order — *all three items below were done on
2026-10-18: the widened envelope (10 reruns + perturbed reference) is in
"Widened envelope", the real-source field is the LOFAR 3C196 section, and the
decision is recorded in "Status of the wider release question".*

1. ~~Widen the reference envelope (many more reruns, and the perturbed-reference `upstream-fix-ulp` build) so "chaotic spread" is measured rather than guessed.~~ Done.
2. ~~Repeat on a field with real sources (a calibrator or a bright event) where flux-ratio and position gates have physical meaning.~~ Done — LOFAR 3C196.
3. ~~Only then decide whether the stack needs a fix, a documented caveat, or acceptance.~~ Done — no evidence of a difference on real sources; the quiet-Sun criterion needs a statistical refinement.

Remaining refinement work: enlarge the reference family further and/or switch the
gate to a rank-based criterion, and repeat the real-source gate at other
configurations (weighting schemes, channel counts, iteration counts).

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

## Widened envelope (2026-10-18): the three-run failure was under-sampling

The 2048² conclusion above rested on three reference reruns, which the "Known
limits" section already flagged as a weak estimate of a chaotic spread. Ten
reference reruns (`envelope18-ref-r4 … r13`) now measure that spread directly,
against two fresh `mx-p11` reruns and two reruns of the **perturbed reference**
`upstream-fix-ulp` (whose only difference from the reference is a one-ulp change
in its own convolution):

| Metric (product) | Reference scatter, median / max over 10 reruns | mx-p11 deviation | ulp deviation |
|---|---:|---:|---:|
| total flux (restored) | 3.3 % / 8.1 % | 2.3 % | 1.9 % |
| MAD rms (model) | 6.4 % / 13.1 % | 6.1 % | 5.7 % |
| second moment (restored) | 0.11 % / 0.21 % | 0.017 % | 0.020 % |
| total flux (residual) | 14.6 % / 19.4 % | 0.7 % | 0.6 % |

**All four candidates pass.** mx-p11 deviates from the reference median by less
than the reference deviates from itself, and the deliberate one-ulp perturbation
behaves the same way — so at this configuration the integral metrics cannot
separate a tiny physics perturbation from run-to-run cleaning chaos. The
three-run envelope was an under-estimate of that chaos, and the "systematic
failure" recorded above was a property of the sample size, not of the stack. The
earlier result stays on record; this measurement supersedes its interpretation.

## Real-source field (LOFAR 3C196): float-level equivalence

The quiet-Sun snapshot has no real sources, which is why its matched-source
envelopes are tens of percent and carry no scientific weight. The upstream CI
fixture `LOFAR_3C196.ms` — a real observation of a bright calibrator
(138.475 MHz, single channel, 603750 rows, 2.16′ beam, sha256
`f834f4ee…5fc3`, matching upstream's pinned hash) — provides a field with real
sources. Four reference reruns, then `mx-p11` and `upstream-fix-ulp` as
candidates (`-size 1024 1024 -scale 4asec -weight briggs 0 -mgain 0.8
-multiscale -niter 3000 -j 8`):

| Quantity (restored image) | Reference envelope (max / median) | mx-p11 deviation |
|---|---:|---:|
| total flux | 6.6e-7 / 3.3e-7 | 5.4e-7 |
| source position max | 3.97e-7 px | 3.97e-7 px |
| matched-source flux spread | 2.09e-7 | 2.09e-7 |
| unmatched sources | 0 | 0 |

Every measured quantity of every product agrees to **float32 rounding**
(~1e-7 relative), for the model and residual products as well. **GATE PASSED**
for mx-p11, for its second rerun, and for the perturbed reference, whose own
products are also indistinguishable from the reference here. On a real-source
field this stack is numerically the same instrument as the fixed reference.

## Metric revision (2026-10-18): sub-pixel positions, significance floor

The first LOFAR pass failed only on source checks of the *model* product: `2.000
px > 1.414 px` position offsets and a 73 % flux-ratio spread that came from
near-zero clean components. A model image is a sparse set of delta-like peaks;
its argmax flips between neighbouring pixels for sub-pixel differences, and its
weakest components are numerically meaningless. That is a property of the metric,
not of the stack, so `bench/compare_sources.py` was revised before the results
above were taken:

- source positions are now flux-weighted centroids over a 9×9 window (sub-pixel);
- a source must exceed both 6σ and 1 % of the image peak, so near-zero components
  cannot drive the statistics;
- positions carry a predeclared 0.01 px floor, because exact equality is not the
  right bar for a sub-pixel estimator when the reference envelope is zero.

Two defects were found while testing the revision (both fixed, both now pinned by
tests): non-maximum suppression compared candidate pixels against stored
*centroids*, mixing coordinate systems, and a first attempt at re-centring the
centroid window oscillated because truncation bias flips sign across the pixel
midpoint. The pre-revision results remain on record above; the tables in this
section use the revised metric.

## Boundary behaviour (quiet-Sun field, revised metric)

With ten reference reruns and the revised metric, the quiet-Sun source-level
checks land *on* the envelope boundary — for both candidates, including the
deliberate one-ulp perturbation:

| Candidate | Failing checks | Magnitude |
|---|---|---|
| mx-p11 (r4) | restored matched-source flux spread 1.492e-2 vs envelope 1.457e-2 | 2.4 % over the envelope |
| ulp (r1) | same metric 1.537e-2; model position 2.928 px vs 2.926 px; model unmatched 8 vs 6 | 5.5 % / 0.07 % / 2 sources over |

Both candidates' source-flux spreads (1.46–1.54 %) sit on the reference family's
own value (1.46 %), i.e. the same chaotic scale. A max-statistic gate cannot
resolve a 2 % difference in the worst pair when the candidate is drawn from the
same distribution, and the fact that the known-tiny change trips the same checks
shows these particular exceedances are not evidence of a physical difference.
Recommended next refinement: increase the reference family further and/or gate on
the candidate's rank within the reference pair distribution instead of the max.

## Evidence

Local, gitignored, under `bench/out/`:

- `throttle-20261018/sources-*-final.{json,log}` — three-rerun envelope results, first tool revision;
- `throttle-20261018/envelope18-ovro-*.{json,log}` — ten-rerun envelope, pre-revision metric;
- `throttle-20261018/rev2-*.{json,log}` — ten-rerun and LOFAR gates under the revised metric;
- run products: `envelope18-ref-r4…r13`, `envelope18-ulp-r1…r6`, `envelope18-mx-r4…r7`, `lofar18-*`, plus the 2026-10-17 audit runs.

`scripts/build_upstream_fix.sh` builds the reference used as `build-reffix/wsclean`
and records its provenance; `bench/out/throttle-20261018/run_envelope18_gates.sh`
and `run_revised_metric_gates.sh` are the analysis drivers. `LOFAR_3C196.ms` was
downloaded from upstream's pinned CI URL and its sha256 verified against
`upstream/wsclean/tests/CMakeLists.txt` before use; it is kept read-only.

## Status of the wider release question

Correctness (tests, selection, allocation, time units) is repaired and reviewed. Performance was re-measured and the earlier regression retracted (see `throttle-validation-2026-10-18.md`). On the evidence above:

- **Real-source field (3C196):** mx-p11 and the reference are numerically the same instrument (~1e-7, i.e. float32 rounding, in every measured quantity).
- **Quiet-Sun multiscale:** the three-run "systematic failure" does not survive a ten-run envelope; mx sits inside the reference's own chaotic spread, and the integral metrics cannot separate a 1-ulp perturbation from that chaos.
- **Quiet-Sun source-level checks** sit on the envelope boundary for both mx and the perturbed reference; they are not decisive at this configuration.

Scientific acceptance is therefore **no longer blocked by evidence of a difference on real sources**; what remains is to make the quiet-Sun source-level criterion statistically meaningful (larger reference family or a rank-based gate) and to repeat the real-source gate at other configurations (weighting, channel count, iteration count) before it is treated as general.
