# PZ-19 update (v0.1.0-rc1) — DRAFT, post when Linear reconnects

## v0.1.0-rc1: frozen, gated, ~2x

Commit `89c875b`. Snapshot `bench/bin/v010-rc1` (+ byte-identical `v010-rc1-aa`
A/A control). Default binary contains zero Metal symbols (`WSCLEAN_MX_METAL=OFF`).

### Numerical gates (all at HEAD)

- Determinism T0 (snapshot vs its byte-identical copy, `-j 1`): bitwise, 0 diffs.
- Reference comparison T2 (vs fixed `build-reffix`, dirty + multiscale `-j 1`):
  PASS at rel RMS ~2e-7 (limit 1e-4).
- 3C196 real-source field (1024², multiscale, niter 3000, `-j 8`, 5 ref + 4 mx):
  3/4 mx runs agree with the references at **~6e-7 pairwise rel RMS** —
  indistinguishable from reference repeats. One mx run took a different
  cleaning path (1.3%); the widened matrix below shows the structure.
- Standing evidence unchanged: native 160 passed / 4 skipped (869917 assertions),
  126 Python tests, 50-rerun quiet-Sun p95 family, LOFAR LBA/HBA + MWA gates.

![3C196 difference](https://raw.githubusercontent.com/peijin94/wsclean-mx/main/docs/bench/v010-lofar-difference.png)
*Fig 1 — 3C196 restored (mx1), mx−ref difference, histogram. max|Δ| 3.8e-07.*

![basin matrix](https://raw.githubusercontent.com/peijin94/wsclean-mx/main/docs/bench/v010-basin.png)
*Fig 2 — pairwise restored-image rel RMS, 5 ref + 4 mx. One basin at ~6e-7
(mx1/mx3/mx4 inside it); single mx2 excursion at 1.3%.*

### Benchmarks (this host, interleaved AB/BA + counters + A/A control)

![timing](https://raw.githubusercontent.com/peijin94/wsclean-mx/main/docs/bench/v010-timing.png)
*Fig 3 — wall time mx vs fixed reference. Speedup comes from inversion
(4096² dirty 1.96x) and deconvolution (3C196 stage-3: 0.77s vs 4.07s).*

- 1024² dirty `-j 1`: 3.76s vs 7.36s (**1.96x**, fewer instructions 37.8G vs 49.0G)
- 1024² multiscale n300 `-j 1`: 17.0s vs 30.4s (**1.79x**)
- 3C196 multiscale n3000 `-j 8`: 2.5s vs 6.0s median (**2.37x**, deconv stage 5x)
- 4096² dirty `-j 8` (4×AB/BA + A/A, quiet): mx 2.05–2.28s vs ref 4.11–4.42s (**~2.0x**)
- 2048² multiscale n3000 `-j 8` (4×AB/BA + A/A, host loaded mid-run): paired
  per-rep ratios **2.48x / 2.25x / 2.28x / 2.60x** — stable across host modes

### Also staged (no release yet)

- `Formula/wsclean-mx.rb`: head-only Homebrew formula, vendors casacore 3.8.2,
  patch flow validated to reproduce the work trees exactly. Bottle build after
  the benchmark; `v0.1.0` tag + release still gated on this review.
- `CHANGELOG.md`: staged 0.1.0 section with scope and known limits
  (CPU path only; Metal stays opt-in and refusing; natural-weighting and
  deep-niter caveats as previously measured).

### Open question (honest)

The single mx2 excursion (1/4 runs, 1.3%) vs 0/5 reference excursions: with
these n's the rate can't be quantified. The project's own standard says widen
the family; the next step is a 10+10 basin-occupancy comparison before 0.1.0
is tagged. Not a blocker for the formula/bottle work.
