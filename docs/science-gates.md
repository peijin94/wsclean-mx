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
The quiet-Sun family was subsequently enlarged to 50 reruns and a predeclared
p95 criterion added, which resolves that ambiguity for this configuration — see
"Enlarged family (50 reruns) and the p95 criterion". The 3C196 real-source family
remains four reruns, which is adequate there because the spread is at the float32
floor.
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

Nine candidate runs now sample this behaviour under the revised metric — four of
`mx-p11` and five of the perturbed reference:

| Family | Runs analysed | Runs that trip at least one check | Margin |
|---|---:|---:|---|
| mx-p11 | 4 | 1 | 2 % over the envelope, on the restored matched-source flux spread |
| upstream-fix-ulp | 5 | 4 | 2–14 % over, same metric; one exact-tie position check (2.93 vs 2.93 px) |

Every exceedance is on a metric whose reference scatter itself spans a factor of
~3 (the 45 reference pairs reach 1.457e-2 while the typical pair is well below
it), and the deliberate one-ulp change trips these checks **more often than mx
does** (4/5 versus 1/4). A check that fires four times out of five for a
known-tiny perturbation cannot be read as evidence about the stack under test.
The recommended refinement is therefore to increase the reference family
substantially and/or gate on the candidate's rank within the reference-pair
distribution instead of the max statistic.

## Enlarged family (50 reruns) and the p95 criterion — boundary resolved

Both refinements recommended above were implemented and the case re-measured
with **50 reference reruns** (1225 pairs) and nine candidates (four `mx-p11`, five
perturbed-reference runs).

New criterion, predeclared in `bench/compare_sources.py` as `--criterion p95`:
the candidate may not be more extreme than the **95th percentile of the reference
family's own members**, measured with the same statistic the candidate is judged
by (deviation from the family median for scalar metrics, worst pairwise spread
against the rest of the family for source metrics). The `max` criterion remains
the default and still exits non-zero on its own verdict; `p95` is opt-in and its
verdict drives the exit status when selected. Both are reported.

Family statistics (50 reruns) and candidate verdicts:

| Metric | family p95 | family max | pair max | candidates passing |
|---|---:|---:|---:|---|
| restored total flux | 3.75 % | 4.29 % | 8.15 % | 9/9 by max, 8/9 by p95 |
| model MAD rms | 6.69 % | 7.22 % | 13.5 % | 9/9, 9/9 |
| restored 2nd moment | 0.102 % | 0.154 % | 0.241 % | 9/9, 8/9 |
| residual total flux | 14.6 % | 15.0 % | 19.9 % | 9/9, 9/9 |
| restored source flux spread | 1.69 % | 1.75 % | — | 8/9, 8/9 |
| model source flux spread | 54.9 % | 55.0 % | — | 9/9, 8/9 |

**All four `mx-p11` runs pass under both criteria.** The single failing
candidate is the same perturbed-reference run (`ulp-r5`) that was the outlier in
the boundary tally above — one of five runs of a deliberately perturbed binary,
not the stack under test. The source-flux-spread checks that were tripping at the
boundary with ten references no longer do, because the family's own member
distribution (median 1.39 %, p95 1.69 %) now brackets the candidates rather than
being estimated from too few samples.

## Configuration sweep on the real-source field (2026-10-18)

The 3C196 agreement above was measured in one configuration. The sweep changes
**exactly one** argument at a time from that base (`-j 8 -size 1024 1024 -scale
4asec -weight briggs 0 -mgain 0.8 -multiscale -niter 3000`) and runs three
reference reruns, two `mx-p11` runs and one perturbed-reference run per
configuration (`bench/out/throttle-20261018/run_lofar_sweep.sh`).

| Configuration | First pass (3 refs) | Follow-up with a larger family |
|---|---|---|
| `-multiscale-scale-bias 0.5` | mx passes everything; perturbed ref fails | — |
| base (`briggs 0`, niter 3000) | mx ≡ ref at ~1e-7 (established earlier) | — |
| `-mgain 0.6` | mx fails a 0.036 px position tie; perturbed ref passes | — |
| `-padding 2` | ties at the envelope for all three candidates | — |
| `-weight briggs -1` | all three fail model MAD rms (mx 9.8e-3 vs 2.9e-3) | — |
| `-weight natural` | all three fail; mx 6e-3 total flux vs 4e-3 envelope, perturbed ref marginal | 13 refs, 10 mx, 12 perturbed: mx model-rms deviation median 2.0e-3 vs perturbed 6.8e-5, and mx reaches the family edge (4.8 %) in 2 of 10 runs while the perturbed does in 0 of 12 |
| `-niter 10000` | all three fail against a *tight* family (envelope 7e-5) | 6 refs, 5 mx, 4 perturbed: mx restored-flux deviation median 10.7 % vs perturbed 4.2 % — **superseded by the bisect below** |

**Reading.** A first pass with three references cannot be judged on its own — the
natural and deep configurations are themselves sensitive, and their three-rerun
envelopes were under-sampled exactly as before. The larger-family follow-up makes
the informative comparison *mx against the perturbed control*, both as candidate
families scored the same way:

- **base and `-multiscale-scale-bias`**: mx at the float32 floor; in the scale-bias
  configuration mx is closer to the reference than the one-ulp control is.
- **`-niter 10000`**: the apparent 2–3× shift does **not** survive the bisect
  below — the control lands in the same discrete cleaning basins, so that
  comparison was basin sampling.
- **`-weight natural`** (10 mx, 12 control runs): the mx family's *typical*
  deviation from the reference median is statistically larger than the control's
  on all three aggregate metrics — permutation test (20 000 resamples, one-sided)
  gives p = 0.0013 (restored total flux), 0.0034 (model MAD rms) and 0.0108
  (restored 2nd moment) — while the source-level metric stays *identical*
  (median source-flux spread 0.0721 in both families) and a component-level
  check shows mx's top-20 components coincide with the reference family's
  **exactly as often as reference runs coincide with each other** (0.695 vs 0.658
  exact-pixel agreement; the control reaches 0.808).

  Reading: mx is not a one-ulp change — it rewrites convolutions and FFT paths —
  so a somewhat larger typical deviation than the control is expected. What
  matters is scale: the mx deviations stay ~25× below the reference family's own
  run-to-run scatter (0.2 % vs 4.8 % max on model rms), the source fluxes are
  unchanged, and the model components land where the reference lands them. No
  code change is indicated by this evidence, and no further sampling is needed
  to act on it.

### Patch bisect at `-niter 10000`

Two runs of each archived build (`mx-p1`, `mx-p3`, `mx-p5`, `mx-p7`, `mx-p9`,
`mx-p11`, `audit-p12-scratch`, `continue-cpu-fixes`) and of the perturbed control,
scored against six references (`analyze_bisect.py`):

| Build | restored flux | model MAD rms | 2nd moment |
|---|---|---|---|
| mx-p1 | 1.6e-2 / 8.8e-3 | 4.6e-4 / 5.8e-3 | 6.6e-4 / 1.5e-4 |
| mx-p3 | 1.1e-1 / 3.4e-5 | 5.9e-2 / 1.7e-6 | 6.1e-4 / 3e-8 |
| mx-p5 | 1.1e-1 / 1.1e-1 | 5.9e-2 / 5.9e-2 | 6.1e-4 / 6.1e-4 |
| mx-p7 | 1.1e-2 / 1.1e-1 | 2.4e-3 / 5.9e-2 | 6.1e-4 / 6.1e-4 |
| mx-p9 | 1.1e-1 / 1.1e-1 | 5.9e-2 / 5.9e-2 | 6.1e-4 / 6.1e-4 |
| mx-p11 | 5.6e-2 / 2.9e-2 | 3.4e-2 / 1.3e-2 | 6.6e-4 / 4.1e-4 |
| audit-p12-scratch | 1.9e-3 / 7.7e-4 | 8.0e-2 / 7.9e-2 | 2.1e-4 / 3.0e-4 |
| continue-cpu-fixes | 1.8e-2 / 1.1e-1 | 1.5e-2 / 5.9e-2 | 3.0e-5 / 6.1e-4 |
| **control (1 ulp)** | 4.9e-2 / 3.5e-5 / 3.5e-2 / 5.0e-2 | 2.3e-2 / 1.1e-6 / 1.7e-2 / 6.6e-3 | 5.1e-4 / 1.3e-8 / 6.2e-4 / 1.5e-3 |

Deviations cluster at a handful of discrete values (1.1e-1, 5.9e-2, 6.1e-4 …) that
recur across unrelated builds — `mx-p3` and `mx-p9` are identical — and the control
is quantized the same way (its four runs take values 3.5e-5 / 3.5e-2 / 4.9e-2 /
5.0e-2). At this iteration depth the deconvolution switches between discrete basins
and every build, from the first patch onward, falls into the same set of outcomes;
the reference family's own reruns reach 2.5 % (p95) / 2.9 % (max) on restored flux,
and the control reaches 5.0e-2, so the control's spread brackets most of what the mx
builds show. **Conclusion: with two runs per build, the deep-configuration
difference cannot be attributed to any particular patch — the experiment cannot
separate the builds at this discreteness, and the earlier median comparison was
sampling which basin each run fell into.** (This does not prove the builds are
equivalent; it says the deep configuration cannot tell them apart this way.) In the
base configuration none of this arises: agreement at the float32 floor.

## Evidence

Figures (`bench/plot_science_gates.py` → `docs/bench/science-gates/`):

- `lofar-difference.png` — 3C196 restored image, mx−reference difference and its distribution: agreed at the float32 rounding floor;
- `quiet-sun-difference.png` — the same for the quiet-Sun case: structured differences an order of magnitude above rounding, at the level the reference differs from itself;
- `envelope-scatter.png` — the six gate metrics on one axis per dataset: reference-pair scatter (grey, with the max as the envelope line) against every mx-p11 and perturbed-reference rerun. It shows the contrast directly — candidates sit inside the envelope for the scalar metrics and at/just past it for the two source-flux-spread rows on the quiet-Sun field, while everything collapses onto ~1e-7 for 3C196.
- `family50-verdicts.json` and `analyze_family50.py` (in `bench/out/throttle-20261018/`) — the 50-rerun family statistics and per-candidate verdicts under both criteria.

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
- **Quiet-Sun, enlarged family:** with 50 reference reruns all four mx-p11 runs pass both the max and the predeclared p95 criterion; the only failing candidate across nine runs is one perturbed-reference outlier.

Scientific acceptance is therefore **no longer blocked**: the real-source field
agrees at the float32 floor, and the quiet-Sun criterion now passes for every run
of the stack under test with a statistically meaningful family. What remains is
to repeat the real-source gate at other configurations (weighting, channel count,
iteration count) before the equivalence claim is treated as general.
