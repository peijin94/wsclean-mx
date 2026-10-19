# mem.md — project memory for wsclean-mx

Short, durable facts and decisions. Update when something changes; put
reasoning and long-form design in `notes.md`.

## Active validation and next work

- Current plan: `docs/development-plan.md`; evidence and limits:
  `docs/audit-2026-10-17.md` and `docs/continuation-2026-10-17.md`.
  Read the continuation before the historical measurements below.
- `scripts/test.sh <mx-build>` runs Python harness/FITS tests and linked numerical
  regressions. Full upstream/dependency suites are separate; CTest can list zero
  even when the upstream `unittest` target is available.
- Patch 12 (`radler/0005`, developer commit `c468d5c`) moves unused peak-search
  scratch into the RMS-weighted branch. Allocation behavior is tested; all five
  1024² multiscale products match p11 bitwise at `-j 1`. No reliable wall-time
  gain is claimed from the noisy four-repeat experiment.
- The initial seven `std::bad_alloc` failures came from invalid fundamental
  alignment passed to macOS aligned_alloc, not a diagnosis of exhausted RAM.
  aocommon/0002 uses malloc for fundamental alignment and keeps extended alignment.
- wsclean/0004 adds selected-row fallback and complete DATA/FLAG/WEIGHT shape
  validation. Expected DDID shapes are cached; invalid selected arrays still fail.
- wsclean/0005 returns MJD days from InMemoryProvider::StartTime; in-memory
  storage and per-row metadata stay in MS seconds. FITS date is explicitly tested.
- Native suite counts, real-MS product checks and timing samples are in the
  continuation report. Broader multiscale scientific acceptance remains open.
- The earlier dirty-4k timing gap was a host stall mode, not code: retired
  instructions match to <=0.2% while the slow mode burns ~1.5x cycles. Interleaved
  A/A plus both-variant sweeps on throttle give 0.3-0.5% differences at -j1/-j8.
  Record per-run instructions/cycles and keep an A/A copy control.
- The older bench/profile.sh still deletes outputs. Use fresh, owned profiling
  directories until that harness has the common validation/immutability guards.
- Harness convention since 2026-10-18: run.sh writes counters.txt, ab.sh adds
  instructions_G/cycles_G columns and a <tag>-ab.mode.txt verdict
  (comparable / stall mode mismatch / counters unavailable), and bench/aa.sh runs
  an A/A null control on two byte-identical snapshots. Wall time alone is not a
  regression verdict.
- ab.sh prints the mode verdict before the ratio table and reports unclassified
  when counters are missing/incomplete/invalid, when repeats span cycle levels,
  when instruction counts differ >20%, or for the linc container (its counters
  measure the host CLI, not the guest). aa.sh also compares the snapshot's
  libschaapthreading.dylib. bench/plot_report.py is NOT mode-aware yet.
- Science gates (docs/science-gates.md, bench/compare_sources.py): candidate
  deviations are judged against the reference's own rerun envelope with a
  predeclared 1e-5 float32 floor. Dirty/PSF pass at ~1e-7; multiscale cleaned
  products now pass against a 10-rerun envelope (the 3-run failure was
  under-sampling; the perturbed upstream-fix-ulp reference behaves like mx).
  Source positions are sub-pixel centroids with a 1% peak detection floor and a
  0.01 px position floor. On LOFAR 3C196 (real calibrator, fixture pinned by
  sha256 in upstream's CMakeLists) mx agrees with the reference at ~1e-7.
  Quiet-Sun boundary resolved with a 50-rerun family + the predeclared
  `--criterion p95` gate (candidate vs the 95th percentile of the family's own
  members): all four mx runs pass both criteria; one perturbed-reference outlier
  out of five fails. Family runs are stored as bench/out/envelope18-ref-r4..r53.
- Config sweep on 3C196 (one argument changed at a time): base and
  `-multiscale-scale-bias` reproduce the reference at the float floor; at
  `-niter 10000` cleaning switches between discrete basins and the 1-ulp control
  reaches the far basin as often as mx (a patch bisect shows no mx-specific
  effect); at `-weight natural` mx's typical aggregate deviation is
  statistically larger than the control's (permutation p 0.0013-0.0108) but
  ~25x below the reference's own scatter, source fluxes identical, components
  placed as consistently as reference runs. Always compare against the
  perturbed-reference family before calling a deviation mx-specific.
- Four native skips are not passes: two BDA cases need an unavailable hard-coded
  external MS; two average-correction benchmarks are explicitly disabled upstream.
- Harness housekeeping (2026-10-18): plot_report.py reads `<tag>-ab.mode.txt`
  and marks every non-mode-verified ratio; profile.sh uses the shared guards and
  refuses existing output; median/subnormal edge cases are pinned by
  tests/median_edge_regression.cpp plus a gate test. Peak RSS tracks image size
  (512² 97 MiB, 1024² 435 MiB, 2048² 1393 MiB), not channel count; WSClean 3.7
  `-facets` does not exist (facet regions are prediction-only).
- External fixtures for the real-source gate live in build-test/test_data as
  read-only MSs: MWA-single-timeslot.ms (real MWA, PupA, 24 ch @133.795 MHz),
  L258627-one-timestep.ms (real LOFAR HBA, 1 ch @138.477 MHz), lba.MS (LOFAR
  LBA, 4 ch @57.8125 MHz), plus LOFAR_3C196.ms. LBA passes at the float floor,
  HBA is mx ≡ control, MWA is chaotic (mx and control both on the envelope).
- bench/out was trimmed 50.8 GB → 35 GB by removing 68 superseded runs that no
  tracked file cites (`bench/trim_plan.py`, manifest docs/trim-2026-10-18.md);
  every figure input and the current gate evidence are kept.
- Metal backend (2026-10-18): infrastructure stage lives in the mx tree under
  `metal/` behind `WSCLEAN_MX_METAL=ON` (OFF by default, so every other build is
  unchanged). MSL compiles at runtime — no Xcode on this Mac. Build/run with
  `scripts/metal_build.sh`; the probe's differential test against a float64 CPU
  twin is what found the float32 placement divergence (u + G/2 rounds at the
  magnitude of G/2 and moves ~1 in 1e4 visibilities one cell off; centred
  `round(u)`/`u - round(u)` is exact and fixes it). Numbers and the M1 path are
  in docs/metal-plan.md; do not quote a GPU speedup before `-mgpu` wiring and
  the science gates.
- ReadMsInMemory remains a separate follow-up: its source opens antenna2 using
  ANTENNA1 and assumes WEIGHT_SPECTRUM. Do not infer full CLI in-memory support
  from the passing provider/interface time and allocation tests.
- Benchmark run/snapshot names are now immutable: use a new tag instead of
  replacing old results. AB order reverses on alternate repeats. Known write
  flags, including `-no-reorder`, are rejected; keep inputs OS-level read-only.
- Fresh full-stack multiscale comparisons are not universally inside upstream's
  sampled rerun spread. Dirty/PSF checks pass; close residual RMS alone does not
  establish cleaned-image equivalence.

## Goal

Apple Silicon (M-series) optimized WSClean. WSClean C++ stays in control;
add a Metal GPU gridding backend and Accelerate/vDSP where it helps. MLX is a
prototyping harness for kernels only, never a runtime dependency.

Deliverable: upstream WSClean vs wsclean-mx compared side by side, bit by bit
(see "Comparison contract" in `notes.md`).

## Repo layout

```
wsclean-mx/                   git@github.com:peijin94/wsclean-mx.git (origin)
├── mem.md / notes.md
├── upstream/wsclean/         git submodule, pristine upstream (NEVER EDIT)
├── patches/
│   ├── build/<dep>/<commit12>/*.patch   build-only portability fixes (macOS);
│   │                                    applied to reference AND mx builds
│   ├── mx/<repo>/*.patch     the wsclean-mx patch set (source of truth),
│   │                         repo in {wsclean, aocommon, schaapcommon, radler}
│   └── candidates/<repo>/    measured but unproven patches, NOT applied
├── scripts/
│   ├── env.sh, lib.sh        shared env (Homebrew cmake, deps prefix) + helpers
│   ├── build_deps.sh         casacore 3.8.2 -> deps/install
│   ├── prepare_fetched_deps.sh  aocommon/schaapcommon/radler at pinned commits + build patches
│   ├── configure_wsclean.sh  the ONE cmake configuration used by both builds
│   ├── build_upstream.sh     reference -> build-upstream/ (from deps/src/wsclean-ref)
│   ├── mx_tree.sh            init/export the dev trees work/<repo>
│   ├── build_mx.sh           work/<repo> -> build-mx/
│   └── check_headers.sh      fails if foreign casacore headers were used
├── bench/
│   ├── run.sh <linc|upstream|mx|snapshot> <tag> [wsclean args]  -> bench/out/<tag>/<variant>/
│   ├── ab.sh <tag> <v1,v2,..> [args]  alternating repeats, min/median per stage
│   ├── profile.sh <upstream|mx> <tag> [args]  macOS `sample` profile
│   ├── sample_tree.py        inclusive/self time per thread from a sample report
│   ├── compare_fits.py <dirA> <dirB> [--tier T0|T1|T2]
│   ├── plot_report.py        figures -> docs/bench/*.png
│   ├── flake.sh <tag> <v1,..> [args]  N repeats, first noise estimate per run
│   ├── snapshot.sh <build-dir> <name>  freeze a build as variant bench/bin/<name>
│   ├── micro/fft_resample.cpp  FFTW vs ducc0 microbenchmark
│   ├── micro/median_select.cpp  Median/MAD radix select: bitwise check + timing
│   └── requirements.txt      numpy, astropy, matplotlib (venv at .venv/, via uv)
├── docs/bench/*.png          figures posted in the tracking issue
└── (gitignored) deps/ work/ build-upstream/ build-mx/ bench/out/ bench/bin/ test_data/ .venv/
```

Fresh setup: `git clone --recursive ...`, `scripts/build_deps.sh`,
`scripts/build_upstream.sh`, `scripts/build_mx.sh`,
`uv venv .venv && uv pip install --python .venv/bin/python -r bench/requirements.txt`,
`container system start`, `container image pull --platform linux/amd64 docker.io/astronrd/linc:5.2.1`.

### Patch-set workflow

- `work/<repo>`: branch `mx` on tag `mx-base` (= pinned commit + build patches).
- Develop by committing on `mx`, then `scripts/mx_tree.sh export [repo]` -> `patches/mx/<repo>/`.
- `scripts/mx_tree.sh init --force [repo]` recreates trees from patches (discards unexported work).
- Never run `checkout_patched` on `work/` — it does `checkout -f` + `clean -fdx`.
- A/B a patch: snapshot `build-mx/wsclean` to `bench/bin/<name>/` before rebuilding,
  then `bench/ab.sh <tag> <name>,mx ...`. Builds are byte-reproducible.
- Tracking issue: https://github.com/peijin94/wsclean-mx/issues/1 ("wsclean-mx build", WIP). Post updates as dated comments; keep the description current; pin figure links to a commit SHA. Linear: PZ-19 (team Peijin-lab, project "data processing LWA"); update its Progress/Next sections alongside.

## Pins

The upstream submodule is pinned to the **exact commit inside the LINC
container**, so all three variants build the same source.

| What        | Value |
|-------------|-------|
| upstream    | https://gitlab.com/aroffringa/wsclean.git @ `2d5c1ed8d7559e5178d243661b408baa288681e6` (reports `v3.7-79-g2d5c1ed8`, "WSClean version 3.7 (2026-02-16)") |
| aocommon    | `e1b7980e02211ade95eef176a3ac7f9ba3dcc55c` (FetchContent) |
| schaapcommon| `b47f19dace28ad420c0a7c8ab1014b55b75205e9` (FetchContent; provides ducc0) |
| radler      | `940e9617a4b3210228a849513752f0732df8104a` (FetchContent; deconvolution) |
| LINC image  | `docker.io/astronrd/linc:5.2.1` (amd64 only, image id b78fba7c17f9), WSClean v3.7-79-g2d5c1ed8 |
| casacore    | v3.8.2, built locally into `deps/install` |

Bumping upstream means: new LINC tag with matching wsclean commit, re-pin the
submodule, regenerate `patches/build/*/<commit12>/`, rebase `patches/mx/`.

## Build patches (patches/build), all non-numerical

- `schaapcommon/b47f19dace28/0001`: skip ELF-only `-Wl,-z,notext` on Apple (ld rejects it).
- `wsclean/2d5c1ed8d755/0001`: `#include <semaphore>` in `gridding/msgridder.h`
  (libstdc++ includes it transitively, libc++ doesn't).

## Dev machine (as of 2026-10-13)

- Apple M2, 4P + 4E cores, 16 GB, macOS 27.0.1, Apple clang 21.0.0, SDK 26.5
- Homebrew: fftw 3.3.11, cfitsio 4.7.0, hdf5 2.2.0, gsl 2.8, boost 1.92.0,
  openblas 0.3.34, cmake 4.4.4, ninja 1.13.2, pybind11 3.1.0 (installed for this),
  open-mpi 5.0.11 (so wsclean builds with HAVE_MPI)
- Apple `container` 1.5.0 (`container system start`; run x86 images with
  `--platform linux/amd64 --rosetta`). Default VM is small: pass `-c`/`-m`.
- MLX: not installed

### Gotchas

- **Three casacores on this machine**: `/usr/local` 3.6.1 (old native wsclean
  install, Dec 2024, also `/usr/local/bin/wsclean`), Homebrew 3.4.0
  (ska-sa tap, too old), ours 3.8.2 in `deps/install`.
- **Apple clang searches `/usr/local/include` before all `-isystem` dirs.**
  Hence `-I$DEPS_PREFIX/include` in `CMAKE_CXX_FLAGS`; `check_headers.sh` verifies.
- MacPorts cmake 3.24 (`/opt/local/bin`) shadows Homebrew cmake; scripts pin `$BREW/bin/cmake`.
- macOS `/bin/bash` is 3.2: no `mapfile`; zsh doesn't word-split `$VAR` (use bash arrays).
- `scripts/env.sh` honours an existing `$ROOT`; a stale `ROOT` in the shell
  silently points `DEPS_PREFIX` elsewhere (old casacore headers). `unset ROOT`.
- The Homebrew python-casacore wheel links the broken Homebrew casacore 3.4;
  inspect MSs inside the LINC container (`work/ms_inspect.py`).
- `bench/run.sh` host RSS for `linc` is the CLI process only, not the VM.
- Seen once (not reproduced): native run failed right after reordering with
  "Error opening meta file for ms ..."; the rerun succeeded.
- First container run after pull is slow (Rosetta translation warm-up): 22.7 s vs ~6 s later.
- 16 GB RAM caps realistic image sizes at ~8k.

## Test data

- `test_data/20260906_170040_50MHz.ms` (from `inti:/nas8/lwa/event-MS/20260906WeakType4pol/50MHz/17/`, tar 409661440 bytes)
- OVRO-LWA all-sky, 352 antennas, 62128 rows = 1 integration (10 s), 192 ch
  x 23.9 kHz from 50.148 MHz (4.59 MHz BW), XX/XY/YX/YY, phased to zenith.
  maxuvw 322.5 lambda, beam ~10.7', w in [0, 4.55] lambda. No WEIGHT_SPECTRUM.
  ~11.8M gridded visibilities for Stokes I.
- All bench runs suppress normal final model updates with `-no-update-model-required`.
  This flag alone does not prevent every write path; the harness rejects known
  overrides, and the test MS must remain read-only.
- The MS is `chmod -R a-w` (read-only) after a `-no-reorder` clean run once
  added MODEL_DATA to it; restore from the tar if it ever changes. wsclean
  runs fine on it read-only.

## Key facts about upstream code

- Gridders (`-gridder`): `wgridder` (default), `wstacking`, `idg`, `direct-ft`, `wtowers`.
- **`wgridder` is ducc0-based and uses ducc0's own FFT, not FFTW.**
- FFTW users: `gridding/wstackinggridder.*` (bulk), `gridding/wsmsgridder.cpp`,
  `math/fourierdomainrenderer.*`, `main/wsclean.cpp`. Radler: not yet checked.
- Apple GPU (Metal) has no FP64; upstream does uvw/phase math in double.

## Measured results

Self-consistency, 1024² dirty, Stokes I (tag `self-*`):

| Comparison                        | Bitwise | rel_rms  |
|-----------------------------------|---------|----------|
| native `-j 1` vs native `-j 1`    | yes     | 0        |
| LINC `-j 1` vs LINC `-j 1`        | yes     | 0        |
| native `-j 8` vs native `-j 8`    | no      | 3.7e-7   |
| LINC `-j 8` vs LINC `-j 8`        | no      | 3.7e-7   |
| native `-j 1` vs native `-j 8`    | no      | 8.0e-7   |
| LINC `-j 1` vs native `-j 1`      | no      | 2.8e-7   |
| mx (0 patches) vs native, `-j 1`  | yes     | 0        |

Timing, 4096² @ 0.03125°, Stokes I, briggs 0, niter 1000, mgain 0.8,
auto-threshold 3, default threads (tag `b4k`):

| Variant          | Wall   | Inversion | Prediction | Deconvolution |
|------------------|--------|-----------|------------|---------------|
| native upstream  | 13.0 s | 7.0 s     | 2.8 s      | 1.5 s         |
| LINC (Rosetta)   | 30.3 s | 15.0 s    | 5.8 s      | 2.2 s         |

LINC vs native at 4k: all products T2 pass, rel_rms ~7e-7, identical stopping peak.

Upstream thread scaling (4k): -j1 27.7 s, -j2 18.6, -j4 13.9, -j6 14.2, -j8 13.6.
Cause: serial main-thread work (profile: main thread busy 90% of wall, ducc0
workers ~28%).

### mx patches (4k clean workload, min of 3 alternating runs, `bench/ab.sh`)

| Patch | Where | Wall | Inversion | Prediction | Status |
|-------|-------|------|-----------|------------|--------|
| (upstream) | | 12.69 s | 6.71 | 2.75 | |
| 1. Resampler: multithreaded ducc0 FFT instead of single-threaded FFTW | schaapcommon `math/resampler.cc` | 9.25 s (1.37x) | 4.40 (1.52x) | 1.49 (1.84x) | in patch set |
| 2. ducc0 `expi()`: vForce `vvsincosf` | schaapcommon ducc0 `wgridder_impl.h` | 9.24 vs 9.80 (p1), median worse | 4.27 vs 4.42 | — | candidate (within noise) |
| 3. Convolve: multithreaded ducc0 r2c/c2r instead of FFTW row/column composite | schaapcommon `math/convolution.cc` | 2k multiscale niter 5000 -j1: deconv 37.3 -> 17.6 s | | | in patch set |
| 4. Median/MAD: radix-histogram select instead of full `nth_element` | aocommon `image.h` | micro 4096²: MAD 300 -> 65 ms | | | in patch set |
| fix. `WGridder::RealImage` padding 0 instead of NaN (bug below) | wsclean `wgridder_implementation.h` | — | | | in patch set |
| 5. SubMinorLoop: chunked DynamicFor PSF subtraction + per-chunk peak search, 32-bit positions | radler `subminor_loop.cc` (radler/0001) | 4k Högbom niter 5000: deconv 6.2 -> 2.4 s | | | in patch set |
| 6. Multiscale: residual FFT once per peak search, cached scale-kernel FFTs (<=1 GiB) | radler `threaded_deconvolution_tools.cc`, `multiscale_transforms.cc` + schaapcommon/0003 `ConvolutionFft`/`ConvolveTransformed` | 1k ms -j1: deconv 4.4 -> 3.1 s | | | in patch set |

Accuracy: dirty/psf ~7e-7 rel_rms vs upstream for both; residual/image vary
6e-7..1.8e-3 between *upstream reruns* (multithreaded clean picks different
components), mx stays inside that range. Patch 4 is bitwise identical to
`nth_element` except the sign of a zero median (`bench/micro/median_select.cpp`).

Baseline for A/B is now `upstream-fix` (pinned upstream + only the RealImage
fix, `build-reffix/`), since plain upstream is corrupt at 2048² (below).
Snapshots: `bench/snapshot.sh <build-dir> <name>` (carries its own
libschaapthreading.dylib). `mx-p3` = patches 1+3+4+fix, `mx-p6` = + 5 + 6.
`bench/profile.sh` also takes snapshot names.

Deep runs, 4096² @ 0.03125°, briggs 0, mgain 0.8, no threshold, default threads,
min of 2 alternating (`bench/ab.sh`, tags `d4k-*`), upstream-fix vs mx-p3:

| Run | upstream-fix wall | mx-p3 wall | Inversion | Prediction | Deconvolution |
|-----|------|------|------|------|------|
| Högbom niter 2000 | 14.85 s | 10.88 s (1.36x) | 1.56x | 1.48x | 1.23x |
| Högbom niter 5000 | 18.44 s | 14.00 s (1.32x) | 1.56x | 1.74x | 1.13x |
| multiscale niter 5000 | 88.22 s | 42.95 s (2.05x) | 1.63x | 1.85x | 2.18x |

Högbom: mx within upstream rerun spread (residual 2e-6, same majors, same
stopping peak, model flux equal to 1e-6). Remaining Högbom deconvolution time
is the minor loop itself, not Convolve.

Patches 5+6 (`mx-p6` = p3 + 5 + 6), tag `p6-n5k`, Högbom niter 5000, min of 2:
upstream-fix 18.40 s (deconv 6.97), mx-p3 13.63 s (6.20), mx-p6 10.33 s
(2.42) -> 1.78x wall vs upstream-fix.
- Subminor loop at 4k: 420k selected pixels x 4387 iterations, memory bound
  (scattered PSF gathers from a 64 MB PSF, ~27 MB/iteration). Static chunks
  wait for the E-cores; DynamicFor with ~4 chunks/thread fixes that.
- Peak search must not be a single running max: clang turns it into
  csel/fcsel, a 5-cycle dependency chain per pixel (3.5x slower than the
  branchy upstream loop). 16 independent lanes + first-index pass vectorizes.
  The PSF subtraction loop needs `#pragma GCC unroll 8` to match upstream -j1.
- Multiscale 2k niter 5000 (`p6-ms2k`, min of 2, machine swapping + hot, so
  noisy): deconv upstream-fix 17.6 s, mx-p3 7.97 s, mx-p6 5.87 s. A 4k
  multiscale A/B under 14 GB swap gave unusable numbers; redo when the
  machine is idle and cool.
- Exactness: patches 5 and 6 are bitwise identical to mx-p3 at -j1 (Högbom
  2k, multiscale 1k), and an MX_CHECK run compared every chunked peak against
  GetMaxComponent() at 1, 12 and 32 chunks (5000/5000 equal).

Multiscale is chaotic w.r.t. Convolve rounding: a 1-ulp change of the scale
factor in upstream's own FFTW Convolve (`upstream-fix-ulp`) moves model flux
0.6282 -> 0.6330 and the residual 3e-3 (LINC vs upstream: 8.6e-4). mx-p3:
flux 0.638, residual 1.8e-2 vs LINC, residual rms 24.388 vs 24.396 µJy (not
worse). Convolve itself matches FFTW to 3.5e-7 (`bench/micro/convolve_check.cpp`,
both 3e-7 from a double reference). Multiscale A/B therefore needs a
"perturbed upstream" spread, not just reruns.

Full-sky check (1024² at 0.125°, i.e. |l|,|m| <= 1.12; `bench/out/fullsky*`,
figures `fullsky*.png`): Högbom upstream/mx vs LINC 1.2e-6 restored, same 561
iterations. Multiscale niter 5000, 3 reruns each: the same binary lands at
~1e-6, ~5e-5 or ~4e-3 from LINC run to run (every build hit >1 level), so
threaded multiscale is nondeterministic on its own. Note `-scale` is in
direction-cosine units: full sky needs size*scale >= 114.6°.

Cross-platform 2048² @ 0.0625° multiscale niter 3000 (`ms2k-n3k-r{1,2}`,
figure `platforms_ms2k.png`), min of 2. M2 at default threads: mx-p6 12.4 s
(deconv 4.4), upstream-fix 20.6 s (11.8), LINC Rosetta 43.4 s (17.0). Linux
native = `astronrd/linc:5.2.1` (same 2d5c1ed8) via docker on inti (2x Xeon
Silver 4214, 24C/48T, shared, load avg 23-33): -j 8 49.3 s (deconv 31.9),
-j 24 55.6 s (deconv 40.0; inversion faster 8.2 vs 10.2 s, deconvolution
slower). All runs 3000 iterations / 3 majors; residual rms 24.64 µJy
everywhere; residual vs LINC run 1 5e-3..2.6e-2, LINC's own rerun 2.2e-2.
Dirty: 6e-7 vs LINC for all except inti -j 24 at 2e-5 (both runs).
inti setup: MS extracted read-only in `/data1/users/pz47/wsclean-bench/`,
runner `run_linux.sh` there (docker, `--user`, same args + `-j`).

Patches 7-11 (2026-10-17, commit a6f5381; snapshots `mx-p7`..`mx-p11`, each
adds one patch; all bitwise identical to the previous at -j1):

| Patch | Where | Single-patch A/B (min of 3) |
|-------|-------|-----------------------------|
| 7. Multiscale: reuse scale-convolved residual from peak search; per-scale twice-convolved PSF + kernel FFT caches | radler/0003 | 2k ms: deconv 4.18 -> 3.64 s, wall 12.71 -> 11.94 |
| 8. ducc0 x2grid: `alignas(128)` atomic spin lock (aarch64 `yield`, then `this_thread::yield`) per grid row instead of `std::mutex` | schaapcommon/0004 (ducc0 `wgridder_impl.h`) | 4k niter 0: inversion 3.45 -> 3.30; lock samples 3758 -> 770 |
| 9. ContiguousMSReader: `ColumnBlock` (getColumnCells, <=1024 rows / 16 MiB) for UVW/DATA/FLAG/WEIGHT | wsclean/0002 | 4k niter 0: wall 3.58 -> 2.11 (1.70x) |
| 10. MSRowProvider/DirectMSRowProvider (reordering): same blocks; `ColumnBlock` moved to `msproviders/columnblock.h` | wsclean/0003 | 512² `-reorder` niter 0: wall 1.85 -> 1.12 (reorder 2.3x) |
| 11. `peak_finder::Simple`: lane-wise row max, original scan only on rows that raise the peak | radler/0004 | micro 2048²: 4.9 -> 0.6 ms; 2k ms deconv 4.39 -> 3.90 |

- Test MS: every main-table column is a variable-shape indirect array in one
  StandardStMan file (`table.f0i`, 401 MB) behind a 64 KB FilebufIO buffer.
  Row-by-row reads across columns refill it every access, and each
  `ArrayColumn::get` also reads the cell shape from the file
  (`SSMIndColumn::getShape`). `bench/micro/ms_read.cpp`: 0.90 s/pass row by
  row vs 0.09 s with 1024-row blocks per column.
- Cleaning runs reorder (DirectMSRowProvider); only niter 0 runs read through
  ContiguousMSReader. So patch 9 helps dirty imaging, patch 10 cleaning.
- `getColumnCells` takes the cell shape from the first row and does not check
  the others, so `ColumnBlockRows()` returns 1 if SPW NUM_CHAN or
  POLARIZATION NUM_CORR differ between rows of those tables.
- vDSP rejected: 2048² r2c+c2r ducc0 17.9 ms (1 thr) / 4.7 ms (8 thr) vs
  `vDSP_fft2d_zrip` 51 ms single-threaded (`bench/micro/fft2d_vdsp.cpp`).
- Final (tags `p11-final-ms2k`, `p11-final-inv4k`, min of 3, figure `p11.png`):
  2k multiscale niter 3000: upstream-fix 23.66 s, mx-p6 14.06 (1.68x),
  mx-p11 11.37 (2.08x; deconv 13.40 / 4.52 / 3.30). 4k dirty: 4.23 / 3.54 /
  1.94 s (2.18x). Residual rms upstream-fix 24.641-24.646, mx-p11
  24.636-24.657 µJy.
- Remaining main-thread profile (2k ms, mx-p9): waiting on gridder/FFT
  workers, ~0.4 s reorder temp-file read/write per run, serial FITS writes,
  `CalculateWeightsImplementation` ~0.16 s.

### Upstream bug: small-inversion padding is uninitialized under clang -ffast-math

- `wgridder_float.cpp`/`wgridder_double.cpp` are compiled with `-ffast-math`
  (CMakeLists "NaNs are avoided" list). `WGridder::RealImage()` fills the
  border around the trimmed image with `quiet_NaN()`, relying on the
  Resampler to zero non-finite pixels. Apple clang folds the NaN fill away:
  `std::vector<float>(n, NaN)` becomes a bare `operator new` (verified with a
  minimal test), so the border is stale heap.
- Effect (small inversion only, i.e. resampled 2352² -> padded size): dirty
  image = true image + resampled garbage. 2048² -niter 10 -j2: 4/6 runs
  garbage (6.52 mJy / 1.43 mJy / 29007 KJy noise), the rest "look fine" at
  25.35 µJy but are 31% rms off. Correct value 24.54 µJy (= LINC,
  = `-no-small-inversion`, = `MallocScribble=1`). 4k runs happened to get
  clean pages (match LINC 7.5e-7) but are exposed too.
- Garbage is deterministic (same heap reuse) -> bitwise identical bad images
  across runs/builds. GCC keeps the NaN fill, so LINC is unaffected.
- Fixed by mx patch `wsclean/0001`; 12/12 runs 24.54 µJy, 5e-7 vs LINC.
  Should go upstream.
- Related latent fast-math hazards (not on our path): `msgriddermanager.cpp:322`
  `std::isfinite` on visibilities (folded to true), and the CMake fast-math list
  names `wsclean/{direct,wstacking}gridder.cpp`, paths that no longer exist.
- Debug tools that worked: `MallocScribble=1` (fills new allocations with 0xAA
  -> near-zero float), checksum instrumentation in a scratch copy
  (`/tmp/wsclean-dbg`). ASan build of wsclean crashes in casacore at startup
  (`observationinfo.cpp:59`, unrelated), lldb can't attach (no entitlement).

## Key performance facts (M2)

- Small inversion: 4096 padded 1.2 -> 4916² (= 4·1229, prime factor) image,
  gridded at 2352². Resampler did r2c 2352² + c2r 4916² single-threaded FFTW:
  ~0.8–1.2 s serial per call, 4 calls per 1-major-cycle run.
- **Homebrew FFTW on arm64 is built without NEON** (formula only passes SIMD
  flags on Intel). A NEON FFTW 3.3.11 is built in `deps/fftw-neon` (single
  precision, threads) for experiments; not linked by any build yet.
- Microbench, resampler FFTs (2352->4916): Homebrew FFTW 1 thr 0.67 s, NEON
  FFTW 1 thr 0.30 s, 8 thr 0.11 s; ducc0 1 thr 0.20 s, 8 thr 0.06 s.
- ducc0 already uses 128-bit NEON (`DUCC0_USE_NEON`); `-march=native` on M2
  resolves to `apple-m1` (+v8.6a). Build uses `-O3 -march=native -ffast-math`.
- ducc0 homegrown SIMD sin/cos are scalar libm per lane (`__sincosf_stret`).
- Remaining serial work after patch 1: MS reordering ~0.9 s, radler
  single-threaded run ~1.3 s (FFTW `Convolve` in `CorrectResidualDirty`),
  weights ~0.2 s, FITS writing ~0.4 s.
- `<Accelerate/Accelerate.h>` breaks the WSClean build (CoreServices macros);
  include `<vecLib/vForce.h>` etc. directly.
- Machine is a fanless MacBook Air (Mac14,2): throttles; use `bench/ab.sh`
  (alternating, cool-down, min-of-N). Spotlight indexes bench/out.

## Decisions

- 2026-10-13: Upstream tracked as a pinned git submodule, never edited.
- 2026-10-13: wsclean-mx is a **patch set** on the pinned upstream (not a full fork).
- 2026-10-13: Upstream pin = the commit inside `astronrd/linc:5.2.1` (2d5c1ed8),
  not upstream HEAD (4edaf77d, 10 commits newer, incl. wgridder recentering).
- 2026-10-13: casacore built from source into `deps/install` rather than
  upgrading the Homebrew/`/usr/local` copies (other projects use those).
- 2026-10-13: Bitwise (T0) ground truth for mx = native reference at `-j 1`.
  The LINC container is a T2 reference (different compiler/arch, never bitwise).

## Open questions

- Benchmark matrix beyond the single LWA snapshot: need a larger MS (many
  integrations) where gridding dominates, plus 8k runs.
- Link mx against NEON FFTW (`deps/fftw-neon`)? Remaining FFTW users are
  radler `Convolve` and restore; mixing with Homebrew double-precision FFTW is OK
  (separate symbol prefixes).
