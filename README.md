# wsclean-mx

![wsclean-mx](docs/wsclean-mx-banner.png)

WSClean optimized for macOS on Apple Silicon.

**0.1.1 uses the executable name `wsclean-mx`.** The CPU release adds the
provider, threaded-ordering and deconvolution updates described below. Metal
is explicitly disabled in the Homebrew package. MX's release version and the
pinned upstream WSClean 3.7 version are printed separately by `-version`.
See [the changelog](CHANGELOG.md) for the rename, upgrade instructions and
remaining numerical-validation limits; older 0.1.0 measurements below are
not new 0.1.1 equivalence claims.

wsclean-mx is a patch set on top of upstream
[WSClean](https://gitlab.com/aroffringa/wsclean), pinned to the exact commit
that ships in the LINC 5.2.1 container (`2d5c1ed8`, WSClean 3.7). It builds
natively for arm64, moves serial FFT and deconvolution work onto all cores,
and removes I/O and locking bottlenecks.
It also fixes an upstream bug that corrupts 2048² images on macOS. Dirty/PSF
products agree with the fixed upstream reference at float32 rounding
(~1e-7 relative RMS). On real LOFAR telescope data (the 3C196 CI fixture —
geometrically phased to 3C196 but uncalibrated, so a pipeline-equivalence
check, not source photometry) the multiscale cleaned products agree at the
same floor in every measured quantity; on the
noise-dominated quiet-Sun snapshot they sit inside the reference's own
chaotic spread (50-rerun family, max and p95 criteria). Details:
[docs/science-gates.md](docs/science-gates.md) and
[CHANGELOG.md](CHANGELOG.md).

On a fanless MacBook Air M2 (16 GB), a full-sky 2048² multiscale clean
(niter 3000) of one OVRO-LWA snapshot takes:

| Build | Wall time |
|-------|-----------|
| **wsclean-mx** (native arm64, CPU patch stack) | **11.4 s** |
| upstream WSClean (native arm64, with the padding fix) | 23.7 s |
| LINC 5.2.1 container (Apple `container`, Rosetta)\* | 43.4 s |
| LINC 5.2.1 on Linux, 2× Xeon Silver 4214, `-j 8`\* | 49.3 s |

\*Measured 2026-10-13, when wsclean-mx (patches 1–6) took 12.4 s and
upstream 20.6 s; the Mac is memory-tight, so sessions differ by ~15%.
A 4096² dirty image takes 1.9 s with wsclean-mx vs 4.2 s with upstream.

![patches 7-11](docs/bench/p11.png)
![2048² multiscale on M2 and Xeon](docs/bench/platforms_ms2k.png)

Full results, plots and methodology: [benchmark.md](benchmark.md). Progress
log: [issue #1](https://github.com/peijin94/wsclean-mx/issues/1).

The current development plan is [docs/development-plan.md](docs/development-plan.md).
Deep exo-pipe / 15-slot benchmarks now default to **150,000 maximum CLEAN
iterations**; smaller caps require an explicit `--niter` or job-field override.
The initial [150k-budget measurements](docs/exo-deep-150k-2026-10-23.md) reach the configured
threshold at 93,854 / 97,873 iterations: **101.8 s at 3K, 147.2 s at 4K** on
M2 / eight CPU threads. Earlier 20k timings are capped runs, not these converged
measurements. WSClean's general-purpose CLI default is unchanged.
The subsequent [copy-removal and masked-peak pass](docs/cpu-copy-and-masked-peak-2026-10-23.md)
preserves all six arrays bitwise in 19 full-depth runs, including the rebuilt
default executable. CLEAN medians improve about 10.8% at both sizes; observed
whole-run medians are 93.63 / 142.43 s. Read the paired/A–A spread caveats before
treating those small-sample wall differences as a general speedup. Peak RSS is
essentially unchanged, and older legacy-reference gaps are not waived.
The [2026-10-22 CPU audit](docs/cpu-audit-2026-10-22.md) adds an allocation-free
RMS-weighted peak scan (4.1–4.5× kernel microbenchmark speedup), with fresh
thread scaling, native tests and retained threaded image-gate failures.
It does **not** establish an end-to-end speedup or a new scientific release.
The [CPU correctness repairs](docs/cpu-correctness-repairs-2026-10-22.md)
address Dijkstra/RMS boundaries, payload positioning, UV limits, empty selections
and the dormant loader, and introduce bounded ordered CPU gridding. Fixed-eight-thread
3K/4K repeats pass bitwise checks; strict 4K old/new image checks and an additional
one-thread legacy-bitwise check still fail.
This development work does not certify a new scientific release.
The [2026-10-17 audit](docs/audit-2026-10-17.md) records fresh benchmarks,
regression coverage, and initial correctness/test gaps. The
[CPU correctness continuation](docs/continuation-2026-10-17.md) covers selection-safe
readers, allocation portability, time metadata and the follow-up gates. This is a development
patch set, not a claim that every WSClean observing mode is validated.
An earlier suspected dirty-imaging slowdown did **not** survive controlled
measurement: interleaved A/A and single-thread sweeps put the candidate within
0.3–0.5% of the baseline with equal retired instructions, per
[docs/throttle-validation-2026-10-18.md](docs/throttle-validation-2026-10-18.md).

## The patches

The patch set lives in `patches/mx/<repo>/`, one directory per library:

| Patch | What it does | Effect |
|-------|--------------|--------|
| schaapcommon/0001 | Resampler: multithreaded ducc0 FFT instead of single-threaded FFTW | inversion 1.5×, prediction 1.8× at 4096² |
| schaapcommon/0002 | Convolve: multithreaded ducc0 FFT instead of FFTW | multiscale deconvolution ~2× |
| aocommon/0001 | Median/MAD: radix-histogram select instead of a full `nth_element` | MAD of 4096² image 300 → 65 ms |
| wsclean/0001 | `WGridder::RealImage` pads with 0 instead of NaN | fixes corrupt images under Apple clang `-ffast-math` |
| radler/0001 | SubMinorLoop: multithreaded PSF subtraction and peak search | Högbom deconvolution 6.2 → 2.4 s at 4096² |
| radler/0002, schaapcommon/0003 | Multiscale: one residual FFT per peak search, cached scale-kernel FFTs | fewer FFTs per multiscale iteration |
| radler/0003 | Multiscale: reuse the scale-convolved residual, cache per-scale PSF transforms | deconvolution 4.18 → 3.64 s at 2048² |
| schaapcommon/0004 | Historical ducc0 gridder: spin lock per grid row instead of `std::mutex` | lock time ~5× lower; superseded by ordered merges in development patch 0009 |
| schaapcommon/0009 (`gpu-dev`) | Canonical tile ranges, bounded ordered gridding partials and exception-safe scheduler draining | fixed-thread repeatability; old/new scientific acceptance and performance are separate gates |
| wsclean/0055, radler/0010 (`gpu-dev`) | Payload/UV/selection/loader and Dijkstra/RMS correctness repairs | targeted linked/native regressions; dormant loader remains disabled |
| wsclean/0002 | Read measurement set columns in blocks of rows (direct reads) | 4096² dirty image 1.70× |
| wsclean/0003 | Same, during reordering (cleaning runs) | reordering 2.3× |
| radler/0004 | Peak finder: vectorized row maximum skips rows | peak search 8×, deconvolution 1.12× |
| radler/0005 | Allocate multiscale peak scratch only for RMS-weighted searches | removes one unused full-image allocation per unweighted scale search; no promised wall-time gain |
| radler/0009 (`gpu-dev`) | Fuse CPU RMS weighting and peak selection, including masks | removes a touched full-image temporary per weighted scale search; exact one-thread imaging; whole-run benefit unestablished |
| radler/0011 (`gpu-dev`) | Remove accidental transform/model copies; share vectorized masked peak scan; simplify PSF setup | full-depth current-baseline T0; about 10.8% lower CLEAN medians at 3K/4K in the measured campaign |
| wsclean/0004 | Preserve selected-row reads; validate full data/flag/weight shapes | avoids speculative-read failures and unsafe malformed-array extraction |
| aocommon/0002 | Portable fundamental-alignment allocation in MultiArray | fixes invalid-alignment `std::bad_alloc` on macOS; retains over-aligned allocation |
| wsclean/0005 | Convert in-memory provider start time from seconds to MJD days | correct FITS observation dates; row metadata remains seconds |

The upstream padding bug: `WGridder::RealImage()` fills image padding with
NaN, but its source file is compiled with `-ffast-math`, and Apple clang
drops the fill. The padding is then uninitialized memory, so with the default
small inversion many 2048² dirty images are garbage. GCC builds (LINC) are
not affected. Details are in [benchmark.md](benchmark.md).

## Install

See [install.md](install.md) for CPU and experimental Metal installation,
verification, runtime controls, and safe source-update instructions.

Apple Silicon Mac, [Homebrew](https://brew.sh):

```bash
brew tap peijin94/wsclean-mx
brew install wsclean-mx        # prebuilt bottle, no compilation
wsclean-mx -version
```

## Building

To build from source instead (same result, ~4 min plus casacore):

Requirements: Apple Silicon Mac, Xcode command line tools, and
[Homebrew](https://brew.sh).

```bash
brew install cmake ninja gcc fftw cfitsio hdf5 gsl boost openblas wcslib \
    pybind11 open-mpi uv
brew tap ska-sa/tap && brew install ska-sa/tap/casacore-data

git clone --recursive git@github.com:peijin94/wsclean-mx.git
cd wsclean-mx
git checkout v0.1.1
scripts/build_deps.sh       # casacore 3.8.2 -> deps/install
scripts/build_mx.sh         # wsclean-mx      -> build-mx/wsclean-mx
scripts/build_upstream.sh   # (optional) unpatched reference -> build-upstream/wsclean
scripts/build_upstream_fix.sh  # (optional) fixed reference -> build-reffix/wsclean
```

`build_upstream_fix.sh` builds the pinned upstream plus the macOS build fixes plus
only `patches/mx/wsclean/0001` (the uninitialized-padding repair), from a
disposable clone in `deps/src/wsclean-ref-fix`, and writes
`build-reffix/provenance.json` (commits, patch hashes, binary hash, linked
libraries, compiler). Plain upstream is not a valid comparison baseline on macOS:
with `clang -ffast-math` it produces corrupt 2048² images, which is why the
repaired reference exists.

Verified 2026-10-18: a fresh `build-reffix/wsclean` reproduces the frozen
`bench/bin/upstream-fix` snapshot bitwise — zero differing pixels in all five
image products (dirty, restored, model, PSF, residual) on the deterministic
`-j 1` multiscale 1024² case. Binary SHA-256s differ only because the embedded
source paths differ.

`build-mx/wsclean-mx` accepts the usual WSClean options. Update scripts that
previously invoked this package as `wsclean`; the package no longer installs
that command name or an alias that could shadow upstream WSClean:

```bash
build-mx/wsclean-mx -size 2048 2048 -scale 0.0625 -weight briggs 0 \
    -mgain 0.8 -multiscale -niter 3000 -name out/img my.ms
```

Build notes:

- casacore is built locally because the Homebrew and `/usr/local` versions are
  too old; system packages are left untouched.
- If `ROOT` is set in your shell, `unset ROOT` before building; the scripts
  use it to locate `deps/`.
- `scripts/check_headers.sh` (run by the build) fails if headers from another
  casacore were picked up.

## Repository layout

```
upstream/wsclean/      git submodule, pristine upstream at 2d5c1ed8 (never edited)
patches/mx/<repo>/     the wsclean-mx patch set (source of truth)
patches/build/         macOS build fixes, applied to both reference and mx builds
scripts/               dependency, reference and mx builds; dev-tree tools
bench/                 benchmark and comparison harness
docs/bench/            benchmark figures
benchmark.md           benchmark results
mem.md, notes.md       project notes and design plan
```

Development happens in `work/<repo>` git trees (branch `mx`), created from
the patch set by `scripts/mx_tree.sh init`. After committing there,
`scripts/mx_tree.sh export <repo>` writes the patches back to `patches/mx/`.

## Benchmarking

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r bench/requirements.txt
container system start
container image pull --platform linux/amd64 docker.io/astronrd/linc:5.2.1

bench/run.sh mx mytag <wsclean args>              # one run -> bench/out/mytag/mx/
REPS=2 COOL=30 bench/ab.sh mytag mx,upstream,linc <wsclean args>   # alternating A/B
REPS=2 COOL=30 bench/aa.sh snapl snapl2 nullctl <wsclean args>     # A/A null control
.venv/bin/python bench/compare_fits.py bench/out/mytag-r1/linc bench/out/mytag-r1/mx
.venv/bin/python bench/plot_report.py             # regenerate docs/bench/*.png
```

Variants are `mx`, `upstream`, `linc` (the LINC container under Rosetta), or
any frozen build in `bench/bin/<name>/` (`bench/snapshot.sh`). `run.sh`
adds `-no-update-model-required` and rejects known MS-writing and output-path
overrides. Keep benchmark MSs read-only as an independent safeguard; this is
not a sandbox for arbitrary WSClean arguments. Existing run and snapshot
names are refused rather than deleted. A/B runs reverse variant order on
alternate repetitions and fail on missing/malformed timings.

Every run also records retired instructions and cycles when the platform's
`time` command provides them (`bench/out/<tag>/<variant>/counters.txt`), and
`ab.sh` writes the comparison's mode assessment to `bench/out/<tag>-ab.mode.txt`.
**Do not read a wall-clock difference as a patch effect until that file says
`comparable`:** similar instruction counts with much higher cycle counts is a
host stall/scheduling mode that has hit identical binaries alike. `bench/aa.sh`
verifies that two snapshots are byte-identical and runs the same A/B machinery on
them as a null control; use it to size the host's own spread next to any claimed
improvement. The verdict is printed before the ratio table and is also
`unclassified` when counters are missing, incomplete or invalid, when a variant's
own repeats span several cycle levels, when instruction counts differ by more
than 20% (different work, or counters measuring different things), or for the
`linc` container, whose counters describe the host container CLI rather than the
guest. `bench/plot_report.py` still labels historical wall ratios without reading
mode files; treat its figures accordingly until that is updated.

Comparisons follow three tiers: bitwise for operation-preserving incremental
changes at `-j 1`, ULP, and scientific metrics against the fixed native upstream
reference. The historical threaded baseline is not deterministic. The CPU
correctness follow-up separately tests fixed-thread-count repeatability; it does
not promise cross-thread-count/platform identity or erase old/new gate failures.
Reference rerun and perturbation spread still need source-level science gates.

## Regression tests

```bash
scripts/test.sh build-mx
```

This runs Python harness/FITS tests, rebuilds the selected mx binary, and runs
linked-production convolution/resampler, median, peak, MS column-block,
allocation, payload positioning, UV limits, loader/interval, RMS window,
threaded-gridder and scheduler exception checks. It rejects mismatched CMake source mappings.
Synthetic unit fixtures are separate from the real MS benchmarks.
Compiler output may include upstream's expected non-AVX warning on arm64.

Science acceptance is separate and measured at source level, not by pixel RMS:
`bench/compare_sources.py --candidate DIR REFERENCE_DIR ...` compares flux, peak
position, size and matched-source quantities against the reference's own rerun
envelope. Results and the predeclared decision rule are in
[docs/science-gates.md](docs/science-gates.md) — dirty/PSF pass, the multiscale
cleaned products pass against a ten-rerun envelope, patch 12 is neutral, and on
real LOFAR telescope data (3C196 fixture, uncalibrated — pipeline equivalence,
not photometry) the stack agrees
with the fixed reference to float32 rounding.

The upstream unit/integration suites are separate and require their test data.
The initial audit's seven allocation failures are repaired, together with the
in-memory date defect they exposed. The continuation report gives current native
counts, reader fixtures, remaining skips and exact commands. Zero tests from
`ctest -N` is not a successful validation; passing native tests does not settle
the broader multiscale scientific-acceptance question.

## Roadmap

The 0.1.1 release is cut from `release/0.1.1`; its Homebrew executable is
CPU-only. Experimental Metal remains opt-in on `gpu-dev`, not part of the
release bottle or its numerical-acceptance claim.
On `gpu-dev`, a Metal-enabled build's `-mgpu` flag uses a two-buffer GPU prediction
FFT pipeline; inversion and gridding/degridding remain on ducc0. GPU multiscale
convolution (`MX_METAL_CONVOLVE=1`) and peak search (`MX_METAL_PEAK=1`) are explicit
experiments, not default speedups. All require `-mgpu`; CPU-only builds reject it.

Read [the GPU audit and next-optimization plan](docs/gpu-next-optimization-2026-10-22.md)
for verified results and open limits. Earlier GPU attribution was invalid because
main's registration code was compiled out; the audit supersedes those claims.
Set `MX_METAL_DEBUG_TIMING=1` to obtain actual stage-execution counters.
The [quarantine and matched-input follow-up](docs/gpu-followup-2026-10-22.md)
passes the active CPU/Metal suites and GPU-specific controlled pixel/source
gates. PSF reuse preserves the theoretical beam and automatic scale choices.
Retired inversion is excluded from production linkage and explicitly rejected;
its failing probe is available only through `WSCLEAN_MX_METAL_ARCHIVE=ON` and
`scripts/test_archived_metal.sh`. The original full-pipeline source family still
fails 4/10 candidates under unchanged limits. This remains experimental, not a
blanket scientific-release approval.
The [detailed GPU profiling report](docs/gpu-profiling-2026-10-22.md) includes
CPU/GPU timelines, utilization limits, copy/plan budgets, thread scaling and
resource-reuse ablations. Set `MX_METAL_PROFILE=1` for optional structured traces;
GPU command residency is not shader occupancy.
The [resource-residency implementation](docs/gpu-resource-optimization-2026-10-22.md)
adds bounded plan/kernel reuse, a shared owned-buffer budget, and optional resident
weighted-peak processing (`MX_METAL_CONVOLVE=1 MX_METAL_FUSE=1`). Deterministic
reuse/fusion outputs match the previous GPU-convolution path bitwise. Matched-input
3K comparisons against CPU still fail strict T2 for both old and new convolution,
so deconvolution remains opt-in. `MX_METAL_MEMORY_MB` defaults to 1024 MiB for
backend-owned buffer capacities; it is not a whole-process RSS cap.
The broader CPU scientific-validation work remains in
[the development plan](docs/development-plan.md).

## License

wsclean-mx is a modified version of WSClean and is distributed under the
[GNU General Public License v3](LICENSE), like WSClean itself. Each patch
keeps the license of the upstream file it changes: the radler patches are
LGPL-3.0-only ([LICENSE.LESSER](LICENSE.LESSER) together with
[LICENSE](LICENSE)), the others GPL-3.0. Original files in this repository
are GPL-3.0-or-later.

[NOTICE.md](NOTICE.md) has the upstream copyrights and pinned sources, a
dated list of every modification (GPLv3 section 5), and what to include when
distributing a binary (section 6: the Corresponding Source is this repository
at the build commit plus the pinned upstream sources).

Copyright (C) 2026 Peijin Zhang. WSClean is Copyright (C) André Offringa and
contributors; aocommon, schaapcommon and radler are Copyright (C) ASTRON.
This program comes with ABSOLUTELY NO WARRANTY.
