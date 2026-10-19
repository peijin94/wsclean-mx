# Changelog

All notable changes to wsclean-mx are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[SemVer](https://semver.org/). Upstream WSClean remains at 3.7
(`2d5c1ed8d7559e5178d243661b408baa288681e6`, LINC 5.2.1 pin).

## [0.1.0] — UNRELEASED (staged; do not publish yet)

First installable release: a native Apple-Silicon (`arm64`) WSClean with
numerical equivalence to the fixed upstream reference and roughly twice the
imaging throughput.

### Added

- `Formula/wsclean-mx.rb`: Homebrew formula (tap-ready) that vendors the
  pinned casacore 3.8.2, applies the full patch set, and builds `wsclean`.
  Local bottle staging only until the `v0.1.0` tag exists.
- `bench/bin/v010-rc1` (+ byte-identical `v010-rc1-aa` control): frozen
  snapshots of this release candidate for A/B and A/A benchmarking.
- `scripts/build_upstream_fix.sh` + `build-reffix/provenance.json`: the
  fixed reference (pinned upstream + build patches + `wsclean/0001` only)
  with recorded commits, patch hashes, binary hash, libraries and compiler.
  A fresh rebuild reproduces the frozen snapshot bitwise (0 differing
  pixels, all five products, `-j 1` multiscale).

### Performance (Apple M2, 16 GiB; M4 throttle numbers agree within host modes)

- 1024² dirty `-j 1`: 3.4–3.8 s vs 7.4 s reference (~2×, fewer instructions).
- 1024² multiscale `-j 1`: 17.0 s vs 30.4 s (1.79×).
- 4096² dirty `-j 8` (`bench/out/v010-dirty4k/`, 4×AB/BA + A/A, counters):
  mx 2.05–2.28 s vs ref 4.11–4.42 s (~2.0×); A/A walls agree, cycles span
  ≤2% (no stall mode); instructions 52.7G vs 71.7G at equal IPC.
- 2048² multiscale n3000 `-j 8` (`bench/out/v010-ms2k/`, 4×AB/BA + A/A):
  host loaded mid-run (cycles +20%, instructions flat — all variants hit);
  pooled medians uninterpretable, but paired per-rep mx/ref wall ratios are
  2.48× / 2.25× / 2.28× / 2.60× (stable across host modes); deconvolution
  stage ~5× (mx 4.9–11.8 s vs ref 24.5–50.7 s), inversion ~1.4×.
  Instructions 2.14× fewer at equal IPC.
- All timing claims use interleaved AB/BA with per-run retired
  instructions/cycles plus a byte-identical A/A control (`bench/aa.sh`):
  an earlier +51% "regression" was retracted as a host stall mode
  (equal instructions, ~1.5× cycles) — see
  `docs/throttle-validation-2026-10-18.md`.

### Numerical equivalence (gate evidence, not adjectives)

- Determinism (`T0`, bitwise): release snapshot vs its byte-identical copy —
  PASS, 0 differing pixels.
- Reference comparison (`T2`, default limits rel-RMS `1e-4` / rel-peak
  `1e-3`): dirty + multiscale `-j 1` — PASS at ~2e-7 (float32 rounding).
- Real-source field (LOFAR 3C196, 1024², multiscale, niter 3000): candidate
  agrees with the reference at ~1e-7 in every measured quantity (total
  flux, peak, MAD rms, second moment, matched-source flux/position).
- Quiet-Sun full-sky multiscale: inside the reference's own chaotic spread;
  all four candidate runs pass both the max and the predeclared p95
  criterion against a 50-rerun family (1225 pairs); the only failing
  candidate across nine runs is a perturbed-reference outlier.
- External fixtures (LOFAR LBA/HBA, MWA PupA, incl. 4-output-channel MWA):
  pass or boundary-limited exactly where the perturbed control is.
- Native suite: 160 passed / 4 skipped (predeclared) / 869917 assertions;
  Python harness suite: 126 passed. Seven historical `std::bad_alloc`
  failures (macOS `aligned_alloc` contract) repaired and pinned.

### Scope and known limits

- CPU path only. The experimental Metal GPU backend (`-mgpu`,
  `WSCLEAN_MX_METAL=ON`) stays opt-in and refusing: 2-D inversion is wired
  behind a gate that falls back to ducc0 wherever the w-term matters (all
  real wide-field data); w-layer inversion is not equivalent (decorrelated
  phases) and 4.5× slower — see `docs/metal-plan.md`. Default bottles and
  binaries contain zero Metal symbols.
- Equivalence is established for the tested configurations (single- and
  multi-channel, Briggs/natural weighting families, 512²–4096²,
  `-j 1`/`-j 8`); `-weight natural` shows a statistically real but ~25×
  sub-scatter deviation, and deep `-niter 10000` lands in discrete cleaning
  basins unattributable to any patch. Linux, all MS layouts, in-memory
  loader promotion, and 8k images are not covered by this release.
- The original measurement set stays read-only; the benchmark harness
  rejects known MODEL_DATA-writing overrides and never replaces existing
  run output (immutable tags).

## Upstream reference

- Pinned upstream: `2d5c1ed8d7559e5178d243661b408baa288681e6` (WSClean 3.7).
- Fixed reference = upstream + shared macOS portability fixes +
  `patches/mx/wsclean/0001` (zero-padding instead of NaN under Apple-clang
  `-ffast-math`; pristine upstream corrupts 2048² images on macOS).
