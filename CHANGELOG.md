# Changelog

All notable changes to wsclean-mx are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[SemVer](https://semver.org/). Upstream WSClean remains at 3.7
(`2d5c1ed8d7559e5178d243661b408baa288681e6`, LINC 5.2.1 pin).

## [0.1.1] — 2026-10-24

### Executable and packaging

- The primary executable is now **`wsclean-mx`**, including native source
  builds and the Homebrew package. Update scripts that invoked the package as
  `wsclean`; no compatibility alias is installed to shadow upstream WSClean.
- `-version` reports MX 0.1.1 separately from upstream WSClean 3.7. FITS
  upstream-version metadata is unchanged. The internal CMake target remains
  `wsclean`; the optional MPI executable remains `wsclean-mp` and is not
  included in the Homebrew bottle.
- Active runners require the renamed MX executable instead of silently using
  a stale `build-mx/wsclean`. Existing frozen snapshots and unmodified upstream
  builds retain support for their historical names.
- The Homebrew package explicitly disables Metal and replaces its temporary
  build-directory runtime search path with an executable-relative library path.
- The native install component includes its private threading runtime. The
  formula explicitly declares the vendored casacore runtime dependencies,
  including GCC's Fortran runtime, libdeflate, readline and wcslib.

### CPU changes since 0.1.0

- Repair reordered-provider payload positioning, UV-bound coordinates, empty
  selections, Dijkstra/RMS boundaries and dormant loader contracts.
- Use bounded, ordered threaded gridding and drain scheduler exceptions safely.
- Fuse RMS-weighted peak selection, remove accidental full-image copies from
  transform/model adapters, and share the vectorized masked-peak scanner.
- Deep exo-pipe benchmark scripts default to a 150,000 iteration cap. The
  general-purpose WSClean CLI iteration default is unchanged.

The copy-removal pass preserves all six products bitwise in 19 full-depth runs
against the repaired current baseline. CLEAN medians fell about 10.8% at 3K
and 4K in that campaign; whole-run timing spread and unchanged RSS are documented
in [the measured report](docs/cpu-copy-and-masked-peak-2026-10-23.md).

### Scope and known limits

- This is a CPU release. Source-level experimental Metal code is not a claim
  that GPU imaging is scientifically accepted, and is not compiled into the bottle.
- Fixed-thread repeatability and incremental bitwise checks do **not** establish
  universal equivalence to 0.1.0 or upstream. Strict 4K old/new image checks and
  a one-thread legacy-bitwise comparison remain failed under their original
  thresholds; those failures are retained, not waived. See
  [CPU correctness evidence](docs/cpu-correctness-repairs-2026-10-22.md).
- Four existing native-test skips remain: two unavailable external BDA fixtures
  and two explicitly disabled upstream benchmarks. MPI runtime, every observing
  mode and every Apple Silicon/macOS combination are not covered by this release.

## [0.1.0] — 2026-10-19

First installable release: a native Apple-Silicon (`arm64`) WSClean with
numerical equivalence to the fixed upstream reference and roughly twice the
imaging throughput.

### Added

- `Formula/wsclean-mx.rb`: head-only Homebrew formula (local tap
  `peijin94/wsclean-mx`), verified end to end: installs clean, vendors
  casacore 3.8.2 into the keg's libexec, applies the full patch set, links
  with no build-dir references, `brew test` passes, and the installed binary
  is T0-bitwise identical to `bench/bin/v010-rc1`.
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
- Real LOFAR telescope data (3C196 fixture, 1024², multiscale, niter 3000):
  candidate agrees with the reference at ~1e-7 in every measured quantity.
  Correction: the fixture is geometrically phased to 3C196 but uncalibrated
  (10% visibility coherence, no detectable source) — this is pipeline
  equivalence on real data, not source photometry; the "real-source" label
  is withdrawn in `docs/science-gates.md`.
- Quiet-Sun full-sky multiscale: inside the reference's own chaotic spread;
  all four candidate runs pass both the max and the predeclared p95
  criterion against a 50-rerun family (1225 pairs); the only failing
  candidate across nine runs is a perturbed-reference outlier.
- 3C196 basin occupancy at HEAD (15 ref + 14 mx): 27/29 in one basin at
  ~6e-7; 2/14 mx share one alternate basin (1.25e-2 away, 6.7e-7 apart),
  0/15 ref excursions, Fisher p = 0.22 (n.s.). Off-basin images keep exact
  source positions with ~1% restored-flux difference — cleaning-basin
  variants, not corruptions. Rate unquantified: tag with this caveat.
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
