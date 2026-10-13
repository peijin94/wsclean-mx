# mem.md — project memory for wsclean-mx

Short, durable facts and decisions. Update when something changes; put
reasoning and long-form design in `notes.md`.

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
│   ├── micro/fft_resample.cpp  FFTW vs ducc0 microbenchmark
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
- Tracking issue: https://github.com/peijin94/wsclean-mx/issues (title "wsclean-mx build").

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
- `bench/run.sh` host RSS for `linc` is the CLI process only, not the VM.
- First container run after pull is slow (Rosetta translation warm-up): 22.7 s vs ~6 s later.
- 16 GB RAM caps realistic image sizes at ~8k.

## Test data

- `test_data/20260906_170040_50MHz.ms` (from `inti:/nas8/lwa/event-MS/20260906WeakType4pol/50MHz/17/`, tar 409661440 bytes)
- OVRO-LWA all-sky, 352 antennas, 62128 rows = 1 integration (10 s), 192 ch
  x 23.9 kHz from 50.148 MHz (4.59 MHz BW), XX/XY/YX/YY, phased to zenith.
  maxuvw 322.5 lambda, beam ~10.7', w in [0, 4.55] lambda. No WEIGHT_SPECTRUM.
  ~11.8M gridded visibilities for Stokes I.
- All bench runs use `-no-update-model-required` (run.sh enforces) so the MS is never written.

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

Accuracy: dirty/psf ~7e-7 rel_rms vs upstream for both; residual/image vary
6e-7..1.8e-3 between *upstream reruns* (multithreaded clean picks different
components), mx stays inside that range.

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
