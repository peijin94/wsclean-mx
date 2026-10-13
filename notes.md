# notes.md — wsclean-mx design notes

Apple Silicon optimization of WSClean. Facts, pins and environment live in
`mem.md`; this file is the reasoning and the plan.

## 1. Thesis

Accelerating WSClean on Apple Silicon is plausible, but MLX is the wrong
abstraction for the whole application. Target architecture:

> WSClean C++ stays in control → Metal GPU backend for gridding →
> Accelerate/vDSP for CPU-side FFT where it helps → MLX only as an optional
> prototyping layer for kernels.

WSClean's own docs say runtime is dominated by either gridding or
deconvolution, and the gridder choice is the biggest performance lever. The
gridders are well isolated behind a C++ interface (`WStackingGridder` is
documented as reusable on its own), so a GPU backend does not require
rewriting WSClean.

## 2. Where the opportunity is

| Component                     | Metal opportunity | Expected payoff |
|-------------------------------|-------------------|-----------------|
| Visibility → UV gridding      | Excellent         | Very high       |
| Visibility weighting          | Excellent         | Medium          |
| w-layer phase correction      | Excellent         | Medium/high     |
| UV-grid accumulation          | Excellent, tricky | Very high       |
| 2-D FFT                       | Moderate          | High            |
| Deconvolution (radler)        | Moderate          | Variable        |
| MS / FITS / casacore I/O      | Poor              | Low             |
| Whole WSClean on MLX          | No                | —               |

Ranking of approaches:

1. Native Metal gridding backend: most promising.
2. Accelerate/vDSP FFT: low risk, but **only for the `wstacking` gridder**
   (see 3.1).
3. Metal port of the wgridder (ducc0 algorithm): long-term high-performance path.
4. MLX custom Metal kernels: good for prototyping and benchmarking kernels.
5. Rewriting WSClean around MLX: avoid.

## 3. Corrections from reading the upstream code (2026-10-13)

### 3.1 The default gridder does not use FFTW

`wgridder` (the default) wraps ducc0 (`ducc0::ms2dirty_bda` / `dirty2ms`,
vendored through schaapcommon). It uses **ducc0's own FFT**, not FFTW.
So "replace FFTW with Accelerate" only speeds up:

- `-gridder wstacking` (`gridding/wstackinggridder.cpp`, nearly all FFTW calls)
- `math/fourierdomainrenderer.*` (model rendering)
- possibly radler/schaapcommon (to be checked after the first configure)

To accelerate FFTs in the default path, we would have to swap the FFT inside
ducc0 for vDSP, which is a much more invasive change. Measure first: ducc0's
FFT is already well vectorized on NEON.

### 3.2 No FP64 on the Apple GPU

Metal has no double-precision support. Upstream computes UVW coordinates, the
`freq * uvw / c` scaling, w-correction phases and recentering phases in
`double`. On the GPU:

- Pixel coordinates in fp32: at 16k grids, the integer part uses 14 of the 24
  mantissa bits, which leaves about 2^-10 for the sub-pixel fraction. That is
  marginal against the kernel oversampling. Compute the integer cell and
  fractional offset on the CPU in double (or with double-float arithmetic),
  and send `(int cell, float frac)` to the GPU.
- Phases (`2π·w·(n−1)`, `exp(i·φ)`) lose accuracy in fp32 for large |w| and
  wide fields. Options: range-reduce in double on the CPU, use compensated
  double-float math in the kernel, or incremental phase rotation with periodic
  re-anchoring.
- Grid accumulation in fp32 complex is what the CPU float path already does,
  but the summation order differs (see 5).

This constraint shapes the kernel design more than anything else.

### 3.3 IDG's GPU path is CUDA-only

IDG's GPU speedups (documented for images above ~6k) come from CUDA, so they
are unavailable on macOS. A Metal IDG port is a possible later alternative to
a Metal wgridder, but it is not a starting point.

## 4. Plan

### Phase 0: build the reference (done 2026-10-13)

- casacore 3.8.2 built into `deps/install`; pybind11 installed; Homebrew
  CMake pinned in scripts.
- Upstream needed two build-only patches on macOS (see `mem.md`); they live in
  `patches/build/` and are applied to both the reference and mx builds.
- `build-upstream/wsclean` is the reference for every comparison.

### Phase 1: Apple CPU baseline + profiling

- Benchmark matrix: gridder ∈ {wgridder, wstacking} × size ∈ {1k, 2k, 4k, 8k}
  × `-j` ∈ {1, 4, 8} × {dirty only, with deconvolution}.
- Collect per-stage times: reordering, gridding (inversion/prediction), FFT,
  deconvolution, I/O. WSClean prints inversion/prediction/deconvolution totals;
  use Instruments (Time Profiler) for finer breakdown.
- Watch P-core vs E-core scheduling: `-j 8` on an M2 mixes 4P + 4E, and
  E-cores can become the stragglers in a thread pool.
- Try Accelerate vDSP FFT in place of FFTW behind a compile switch (affects
  `wstacking` only, see 3.1).

### Phase 2: standalone Metal gridder

- Extract the low-level gridder interface into a standalone harness that feeds
  identical visibility buffers to `gridder_cpu` (upstream code) and
  `gridder_metal`.
- Prototype kernels quickly with MLX `mx.fast.metal_kernel` from Python, then
  port the proven kernel to native C++/Metal (metal-cpp), with no MLX at runtime.
- Validate CPU vs GPU grids and images per the comparison contract (section 5).

### Phase 3: tiled Metal gridding

Irregular accumulation is the central problem: many visibilities hit the same
cells, and naive global float atomics serialize under contention. Approach:

- CPU (or GPU) bins visibilities by UV tile, sorted by tile then w.
- One threadgroup per tile accumulates into threadgroup memory, then writes
  the tile once (no global atomics, or only at tile borders/halos).
- Precomputed oversampled kernel tables or on-the-fly ES kernel (ducc0 style).
- Fixed in-tile accumulation order, so the result is deterministic run to run
  (see 5).
- fp16 only where it is provably safe; probably nowhere in the accumulators.

### Phase 4: GPU wgridder / fuller pipeline

```
MS → CPU preprocessing → [Metal: weighting, w calc, gridding, w correction]
   → FFT (Accelerate or Metal) → radler deconvolution (CPU)
```

GPU deconvolution only after the above has been measured.

### Realistic speedups

No blanket 10x promise. Hypotheses to test:

| Workload                 | Apple GPU potential |
|--------------------------|---------------------|
| 1–2k images              | Low/moderate        |
| 4k                       | Moderate            |
| 8k                       | High                |
| 16k+                     | Very high, memory permitting (not on a 16 GB M2) |
| Huge visibility count    | High                |
| Tiny MS                  | Low                 |
| Deconvolution-heavy      | Low/moderate        |
| I/O-heavy                | Low                 |

## 5. Comparison contract (upstream vs wsclean-mx, side by side)

The end goal is a side-by-side, bit-by-bit comparison. "Bit by bit" is only
meaningful once we know what upstream itself reproduces, so this is defined
in tiers.

### 5.0 Three variants, one source

All three run the same WSClean commit (`2d5c1ed8`, the one inside
`astronrd/linc:5.2.1`), with the same arguments, through `bench/run.sh`:

| Variant    | What                                                | Role |
|------------|-----------------------------------------------------|------|
| `linc`     | LINC container, x86_64 gcc build, Rosetta in Apple `container` | deployed-pipeline reference (T2) |
| `upstream` | native arm64 build of the pinned commit + build-only patches | bitwise ground truth (T0) |
| `mx`       | native arm64 build of the same + `patches/mx/`      | the thing under test |

`upstream` and `mx` share dependencies, compiler and the exact CMake
configuration (`scripts/configure_wsclean.sh`), so any difference between
them comes from `patches/mx/`.

### 5.1 Upstream's self-consistency (measured 2026-10-13)

Measured on the LWA snapshot (1024² dirty, Stokes I):

- `-j 1` twice: **bitwise identical**, both natively and in the LINC container.
- `-j 8` twice: **not** bitwise identical (rel_rms 3.7e-7), both natively and
  in LINC. Thread-order-dependent float summation in the gridder.
- `-j 1` vs `-j 8`: rel_rms 8e-7.
- LINC vs native, both `-j 1`: rel_rms 2.8e-7. Different compiler and ISA
  (gcc/x86 vs clang/arm64: FMA contraction, vectorization, libm), so the
  container can never be a bitwise reference.
- mx with zero patches vs native upstream, `-j 1`: **bitwise identical**,
  which validates the build/bench harness itself.

Consequences:

- T0 claims are made at `-j 1` against the native `upstream` build only.
- Multithreaded comparisons have a noise floor of ~1e-6 relative RMS;
  anything mx does at `-j N` should be judged against that floor, not zero.
- LINC vs mx is a T2 comparison, with the LINC-vs-upstream numbers as the
  yardstick (~7e-7 rel_rms at 4k with deconvolution).

### 5.2 Tiers

| Tier | Meaning | Expected for |
|------|---------|--------------|
| T0 bitwise | FITS data arrays identical (sha256 of the data unit, headers excluded) | build-only changes, refactors, CPU paths with same op order, `-j 1` |
| T1 ULP-bounded | max ULP diff per pixel within a stated bound | FFTW → vDSP, reordered CPU reductions |
| T2 scientific | `rms(diff)/rms(ref)`, `max|diff|/peak(ref)`, residual RMS, source fluxes/positions within tolerance | Metal gridding (fp32 GPU, different summation order) |

Rules:

- Compare the **data arrays** of each FITS product, never file hashes:
  headers carry DATE, version and origin keywords that always differ.
- Same machine, same compiler, same flags for both builds; otherwise FMA
  contraction (`-ffp-contract`) alone breaks T0.
- Compare every product: `-dirty`, `-image`, `-model`, `-residual`, `-psf`,
  and component lists when using `-save-source-list`.
- Every new code path either ships with a "reference mode" that is T0 against
  upstream (e.g. GPU path disabled at runtime), or documents its tier and
  measured bounds.
- GPU float atomics make results nondeterministic and therefore not even
  T0-reproducible against themselves. The tiled, atomic-free design in Phase 3
  is partly motivated by this.

### 5.3 Tooling

- `bench/run.sh <linc|upstream|mx> <tag> [args]`: identical invocation per
  variant into `bench/out/<tag>/<variant>/`; records wall time, host peak RSS
  and WSClean's inversion/prediction/deconvolution times. Forces
  `-no-update-model-required` so the test MS is never modified.
- `bench/compare_fits.py <ref> <test> --tier T0|T1|T2`: per product, the
  bitwise match, n_diff, max ULP, max abs diff, rel_rms, rel_peak and peak
  ratio. Exits non-zero if the tier is violated. Max ULP is meaningless near
  zero-valued pixels (it blows up), so T1 needs a floor or a masked variant
  before it's usable on images.
- Test MS referenced by path and size in `mem.md`, not committed.

## 6. Status and next steps

Done (2026-10-13): Phase 0. Environment fixed, casacore 3.8.2 local,
reference + mx builds, LINC container runs, bench and compare tooling,
self-consistency measured, first 4k timing (native 13.0 s vs LINC 30.3 s).

Next:

1. Larger benchmark data: the LWA snapshot is one integration (~12M Stokes I
   visibilities), so gridding is only ~50% of runtime. Need a multi-integration
   MS where gridding dominates, and 8k runs.
2. Phase 1 profiling: Instruments Time Profiler on wgridder and wstacking at
   2k/4k/8k; split inversion into reorder / grid / FFT / w-correction.
3. Check P-core vs E-core effects: `-j 4` vs `-j 8` timings.
4. Masked/floored ULP metric for T1.
5. First mx patch candidate: Accelerate FFT for `wstacking` (T1 expected).
