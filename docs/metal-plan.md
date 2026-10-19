# Metal backend: plan and progress

Status 2026-10-18: **infrastructure stage complete** (build flag, device
wrapper, runtime-compiled kernels, differential probe). Not yet wired into the
imaging path; no science or performance claim for wsclean itself is made here.

## Why the gridding accumulator is the first target

The 4k profiling run (`bench/out/prof4k/mx-profile/top.txt`, `sample` at 1 ms)
puts the non-idle time in the ducc0 w-gridder kernels:

| hot symbol | samples |
|---|---:|
| `ducc0::…Wgridder…::x2grid_c_helper` | 9624 |
| `ducc0::…Wgridder…::grid2x_c_helper` | 4006 |
| ducc0 FFT internals (`cfftp3`/`copy_input`/`copy_output`) | ~5400 combined |
| FFTW3 (`apply`, `t2_25`, `t2_10`, …) | ~4600 combined |

So the visibility→grid accumulation dominates, and it is the most regular,
most parallel part of the pipeline — the right first port. The FFT stage is the
second candidate (MPS provides tuned FFT primitives there).

## What is built (WSCLEAN_MX_METAL=ON, off by default)

* `metal/mxshaders.h` — Metal Shading Language sources as a raw string. They are
  compiled **at runtime** by the OS Metal runtime, so no Xcode or `metallib`
  toolchain is needed (this Mac has only CommandLineTools).
* `metal/metaldevice.{h,mm}` — Objective-C++ device wrapper behind a plain-C++
  interface: device info, host-side visibility bucketing, and the gridding
  dispatch. One threadgroup per 32×32 output tile; the tile lives in threadgroup
  memory and is merged once with device atomics, so only the merge pays atomic
  traffic. Float adds go through bit-cast `atomic_uint` CAS because Apple GPUs
  have no native float atomics.
* `metal/probe_main.cpp` → `mx-metal-probe` — differential self-test against a
  float64 CPU twin of the same arithmetic, plus a kernel-accuracy check.

## Findings from the probe (these are the point of the exercise)

1. **MSL reserves `half`** as a type name — the first runtime compilation failed
   on `float half = …`; the compiler is also the linter here.
2. **Threadgroup atomics need their own overload**: a `device atomic_uint*`
   function cannot take a `threadgroup` pointer.
3. **The substantive one: cell placement must be computed in centred
   coordinates.** Forming `u + G/2` in float32 rounds at the magnitude of `G/2`
   (6e-5 near `u = 460` on a 1024 grid). For visibilities within half a float32
   step of a half-integer cell, that rounding moves the nearest integer — the
   whole 6×6 footprint lands one cell away from the double-precision CPU result.
   Measured rate ≈ 1 in 10⁴ uniformly drawn visibilities; on the 200k-visibility
   probe it produced ~20 affected footprints and a 3.4e-2 relative grid error
   that no aggregate statistic would have flagged as a placement bug. Computing
   `round(u)` and `fx = u - round(u)` (exact in float32) fixes it completely:
   rel_max 3.4e-7 afterwards. WSClean computes grid coordinates in double, so
   the GPU path must reproduce double-precision placement, not approximate it.
4. Fast-math `exp`/`sqrt` in the ES kernel are accurate to 3.8e-7 relative;
   the `precise::` namespace reaches 1.2e-7. The gridding path keeps the direct
   evaluation for now; a precomputed kernel table (the ducc0 design) removes the
   question entirely and is the M1 optimization.

## Probe results (Apple M2, 8 GPU cores, macOS 27.0.1)

`mx-metal-probe --quiet`, kernel support 6, beta 2.3, 32×32 tiles, direct kernel
evaluation (no table yet), CAS atomics — an **unoptimized baseline**:

| visibilities | grid | GPU kernel | throughput | rel_max vs CPU twin |
|---:|---:|---:|---:|---:|
| 200 000 | 1024² | 2.56 ms | 78 Mvis/s | 3.6e-7 |
| 1 000 000 | 1024² | 11.61 ms | 86 Mvis/s | 3.5e-7 |
| 2 000 000 | 2048² | 18.26 ms | 110 Mvis/s | 2.9e-7 |

All structural checks pass: every cell the reference finds non-zero is non-zero
on the GPU, and no cell without contributions was touched. Runtime compilation
costs ~25–35 ms per process (first call), so the real integration must compile
once at start-up and can later cache a `MTLBinaryArchive`.

Baseline measurements live in `bench/out/metal-20261018/probe-sweep.txt`;
reproduce with `scripts/metal_build.sh --quiet`.

## M1 and beyond

1. **Kernel table**: evaluate the ES kernel on the host into an oversampled
   table (ducc0's approach) and interpolate on the GPU — removes the exp/sqrt
   cost and the fast-math question; characterize the interpolation error against
   the direct evaluation with the same probe.
2. **Wire in behind a flag**: an `-mgpu` option on the w-gridder path
   (`wgridder/`, ducc0-backed), keeping the CPU path as the reference.
   Match ducc0's exact kernel constants and w-plane handling, then re-run the
   science gates (real LOFAR/MWA datasets, quiet-Sun family) — the same
   family-envelope criterion applies; a GPU path is a different implementation,
   not a bitwise twin.
3. **Then** the FFT stage (MPS) if the profile still says so, and only then any
   performance claim.

## Optimization round, 2026-10-18: what helped, what did not

The kernel now uses ducc0's own form and parameters, `K(v) = exp(beta
((1-v^2)^e0 - 1))` with `beta = betaNorm * support`, taken from the W=6,
ofactor=2.0, ndim=3, single-precision row of their kernel database
(`betaNorm = 2.10745629204644125`, `e0 = 0.520621490478515692`, epsilon
2.1e-5). This replaced a naive `beta = 2.3` variant whose edge value was
exp(-2.3) ~ 0.1 - a 10 % discontinuity at the support edge, i.e. a far worse
window than the gridder is supposed to use.

Three structural variants plus a timing ablation were implemented and measured
in one binary (`scripts/metal_build.sh`, `--repeat 5`, min kernel time, all
differential checks pass at <= 4e-6 against the float64 twin):

| grid | visibilities | analytic (generic) | hoisted (registers) | packed (bucket-ordered) | cost probe (no kernel math) | kernel-math share |
|---:|---:|---:|---:|---:|---:|---:|
| 1024² | 200 k | **2.33 ms** (86 Mvis/s) | 3.49 ms (0.67x) | 3.49 ms (0.67x) | 1.63 ms | 30 % |
| 1024² | 1 M | **4.32 ms** (232 Mvis/s) | 6.71 ms (0.64x) | 12.11 ms (0.36x) | 2.86 ms | 34 % |
| 2048² | 2 M | **12.64 ms** (158 Mvis/s) | 15.72 ms (0.80x) | 16.88 ms (0.75x) | 6.65 ms | 47 % |

All three variants agree with the float64 twin (rel_max 4e-7 to 4e-6); the
ablation's grid is intentionally wrong and its row is timing-only.

Conclusions, all measured rather than assumed:

1. **The generic kernel is the fastest.** Manual hoisting of the six 1D weights
   per visibility made the kernel 1.2-1.6x *slower*: the compiler already hoists
   the loop-invariant evaluations, while the manual version adds register
   pressure and fully unrolled 6x6 bodies. The "obvious" optimization was a
   deoptimization, and only the probe's variant comparison showed it.
2. **Packing the bucket data does not pay.** It duplicates every visibility into
   each tile its support touches and, at 1 M visibilities, was 2.8x slower than
   the gather through the index list. The gather is not the bottleneck.
3. **Kernel arithmetic is 30-47 % of the time; the tile/atomic machinery is the
   rest.** So the next lever is the atomic strategy (fewer, wider or
   contention-free updates), not the kernel formula.
4. **Linear interpolation tables cannot meet the accuracy requirement.** Measured
   maximum normalized-weight error: kernel table 2.0e-2 (os=2), 1.4e-3 (os=8);
   tabulating the smooth part `g = (1-v^2)^e0` is worse still (4.3e-2 at os=2)
   because `g` has an infinite derivative at the support edge and the
   exponential amplifies it. This is why ducc0 fits a polynomial instead of
   interpolating: the wiring stage should port their polynomial evaluation (or
   their precomputed coefficients) rather than a naive table.
5. Float32 evaluation of the ES kernel carries ~1.5e-6 relative error because
   `dK/K = beta * dg` amplifies float32 rounding by beta ~ 12.6. That is well
   under the kernel's own aliasing error (2.1e-5) and under the accumulation
   floor, so it is not a blocker - but it is the reason a host-side table, which
   stores values directly, reaches ~1e-7 and is the better base for the
   polynomial route.

Absolute throughput is not comparable with the first baseline (1 M visibilities:
11.6 ms then, 4.3 ms now) because both the kernel formula and the codegen
changed; every comparison above is within a single binary.

## Matching ducc0's actual kernel, 2026-10-19

ducc0 does not evaluate `exp(beta ((1-v^2)^e0 - 1))` at gridding time: it
approximates it with W piecewise polynomials of degree D and evaluates those.
So the kernel a Metal port must reproduce is *their polynomial*, not the
analytic formula.

`bench/metal/ducc0_kernel_tool.cpp` (built/run by `scripts/metal_kernel_coeffs.sh`)
links ducc0's `math/gridding_kernel.cc`, replicates its kernel-database
selection, and writes W, D, the row's `beta_norm`/`e0` and the W*(D+1)
coefficients. Two lessons from building it:

* **Several database rows share (W, oversample, ndim, single precision) with
  different fits**, so replicating ducc0's exact selection loop matters: their
  loop keeps the LAST row with the smallest support (`W <= Wmin`, with `Wmin`
  starting at `Wmax<T>()`). A loop that kept the first such row selected a
  different kernel, and the harness's analytic reference then described a
  *different* function - which showed up as a bogus 3.5e-2 "fit error" until
  the selection was mirrored and the row's beta/e0 were read back from the
  extracted file instead of being hard-coded.
* wsclean's default `-wgridder-accuracy` is **1e-4**, which selects the W=6
  row (index 340): `beta_norm = 2.1074562920464412`, `e0 = 0.52062149047851569`,
  row epsilon 2.1e-5 - the same parameters the harness had derived from the
  database listing.

Verification of the shader's evaluation convention against ducc0's own
`PolynomialKernel::eval` over 200001 points: **exact (0 difference)** with the
double-precision coefficients, 1.7e-8 with the float32 coefficients the
shader carries (which is also what ducc0's own float kernels store).

With those coefficients the probe gained `poly` (36 polynomial evaluations per
visibility) and `poly-h` (the 1D samples hoisted into registers, 6+6 per
visibility). Measured, min of 5, three consecutive runs agreeing:

| variant | kernel | throughput | rel_max vs its own reference |
|---|---:|---:|---:|
| analytic | 2.33 ms | 86 Mvis/s | 4.9e-7 |
| hoisted | 3.44 ms | 58 Mvis/s | 4.0e-6 |
| packed | 3.44 ms | 58 Mvis/s | 4.0e-6 |
| **poly** | 5.64 ms | 35 Mvis/s | **1.5e-7** |
| poly-h | 4.23 ms | 47 Mvis/s | 5.0e-6 |
| costprobe | 1.62 ms | 123 Mvis/s | (timing only) |

* The polynomial reproduces ducc0's kernel to 1.5e-7 - the best agreement of
  any variant, because a Horner evaluation has no beta-amplified error.
* ducc0's polynomial deviates from the analytic kernel by only **1.6e-8 where
  the kernel is significant** (3.2e-6 at the very support edge, where it
  contributes nothing) - so the analytic-formula variants were the same kernel
  shape all along, and the row's EPS column (2.1e-5) is an aliasing budget, not
  a pointwise bound.
* The polynomial is nonetheless *slower* on this GPU (5.6 ms vs 2.3 ms): 36
  Horner chains cost more than 12 evaluations of the hardware's fast-math
  `pow`/`exp`. Hoisting helps within the polynomial family (4.2 ms, 1.3x
  faster than `poly`) while it hurt the analytic family - consistent with the
  earlier finding that the compiler already hoists when the kernel is cheap.
  `poly-h` is therefore the wiring candidate: accurate to 5e-6 against ducc0's
  convention and 1.3x faster than the unhoisted polynomial.
* Measurement hygiene: one intermediate run measured the analytic variant at
  1.19 ms (half its repeated value) with a negative cost-attribution share.
  Three consecutive repeats agree on 2.33 ms, so that run is treated as an
  outlier and the repeated numbers are the record.

## Round trip (grid + degrid), 2026-10-19

The w-gridder does both directions, so the probe now measures both plus the
property that ties them together.

* `grid_degrid_poly` is the adjoint operation: one thread per visibility, no
  atomics, no tiles, summing the 6x6 neighbourhood with the same ducc0
  polynomial weights. The grid buffer is read as plain floats (the gridding
  kernel published it through atomics; the merge is complete by then).
* `--op roundtrip` measures both directions, checks each against its double
  twin, and checks the adjoint identity `<G x, Y> = <x, D Y>` with an
  independent random grid `Y`.

| quantity (603 814 visibilities, 1024², poly-h, min of 5) | value |
|---|---:|
| gridding kernel | 12.60 ms |
| degridding kernel | 10.10 ms |
| round trip | 22.70 ms (26.6 Mvis/s) |
| gridding vs its twin | rel_max 3.0e-6 |
| degridding vs its twin | rel_max 2.7e-7 |
| adjoint identity | rel_diff 4e-8 |
| round trip vs scalar double twin | 10.2x |

The adjoint identity is the useful new correctness property: it fails if the
degridding weights or the index mapping differ from the gridding ones in any
way, and at 4e-8 it says the pair is exactly adjoint to float32 precision.

### Improvement evaluation

The honest comparison is kernel against kernel: ducc0's own CPU w-gridder on the
same synthetic data, same machine, same visibility counts, measured with
`scripts/metal_cpu_baseline.sh` (which mirrors wsclean's own `ms2dirty_bda`
call with `do_wgridding=false` at 8 threads, so that it measures the same 2D
gridding the Metal kernels implement).

| nvis | CPU grid | CPU degrid | CPU total | GPU grid | GPU degrid | GPU total | CPU/GPU |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 200 064 | 19.18 ms | 19.19 ms | 38.37 ms | 4.21 ms | 3.44 ms | 7.65 ms | **5.0x** |
| 603 814 | 42.59 ms | 43.06 ms | 85.65 ms | 12.60 ms | 10.10 ms | 22.70 ms | **3.8x** |
| 1 000 064 | 69.61 ms | 70.09 ms | 139.70 ms | 22.46 ms | 17.52 ms | 39.98 ms | **3.5x** |

So the Metal kernels are **3.5-5x faster than ducc0's own optimized CPU
gridder** for the same work, with the same accuracy (gridding within 5.0e-6,
degridding within 3.2e-7 of a float64 twin, adjoint identity 2.3e-8-5.8e-7).
Two honest qualifications:

* The CPU numbers include ducc0's FFT and kernel correction; at 1024² the fixed
  part of the call is around 12 ms (20 064 visibilities cost 12.28 ms, of which
  the scatter is a small fraction). Removing it would make the gridding-only
  ratio larger, but the table measures calls, not loops.
* ducc0's gridder is a strong baseline - it is mature, SIMD-vectorized, and
  lock-based rather than atomic-based - so a 3.5-5x win is a real result, not a
  weak one. The remaining headroom is the GPU-side atomic traffic (70 % of
  kernel time per the ablation).

**Correction.** The previous round's summary compared the 12.6 ms gridding
kernel against wsclean's 484 ms `-niter 0` inversion stage on `LOFAR_3C196.ms`
and read the ratio as "~38x". That comparison is stage against kernel: the stage
does a w-gridded inversion over multiple planes, MS I/O, the FFT, and the
correction, while the kernel does one 2D plane. The kernel-vs-kernel table above
supersedes it; the stage figure stays useful only as a bound on what the pipeline
could recover if the whole stage were offloaded.

### Real uv coverage: the synthetic spread flattered the GPU

The table above uses uniformly spread synthetic uv points, which is the easy
case. Real LOFAR coverage clusters: for `LOFAR_3C196.ms` at 138.477 MHz the
621 250 rows collapse to 20 519 distinct footprint origins at the 4-arcsec
configuration (about 21 visibilities per cell) and 130 197 at 25 arcsec. Both
tools now read the same dump (a `taql` extract of `UVW`/`DATA[0,0]`/`FLAG[0,0]`,
621 250 rows of which 440 745 are usable; `work/wsclean/metal/uvw_file.h`),
scale it identically (`--lambda-per-cell`, the wavelength size of one grid cell)
and are timed on the same rows.

| configuration | rows | GPU grid | GPU degrid | GPU total | CPU total | CPU/GPU |
|---|---:|---:|---:|---:|---:|---:|
| 50.4 lambda/cell (wsclean 4 arcsec benchmark) | 440 745 | 33.4-37.9 ms | 2.0-2.3 ms | 35.7-40.1 ms | 67.3 ms | **1.7-1.9x** |
| 8 lambda/cell (LOFAR 25 arcsec typical) | 440 745 | 15.5-24.1 ms | 2.7-3.4 ms | 18.5-27.5 ms | 65.8 ms | **2.4-3.6x** |

(min of 5, three repeat runs; the clustered case has 25-35 % run-to-run
variance, so ranges are the honest form of these numbers.)

Three findings, in order of importance:

1. **The atomic accumulation is the bottleneck on real data.** At 50.4, GPU
   degridding is 2.0-2.3 ms while gridding the same rows is 33.4-37.9 ms - a
   factor of ~16 for the same footprint arithmetic, because degridding has no
   atomics (one thread per visibility) and gridding funnels every visibility
   through the tile CAS merge. Uniform data hid this: its footprints rarely
   collide. Fixing it means the pull model - bucket visibilities per tile and
   let a threadgroup own a tile exclusively, as ducc0's CPU gridder does with
   its sorted ranges - rather than pushing into shared cells.
2. **Clustering costs the CPU much less than the GPU.** ducc0's gridder sorts
   rows by uv index, so clustered data gives its threads long contiguous runs
   with no contention; the GPU's contention grows with multiplicity. This is
   why the ratio falls from 3.5-5x to 1.7-3.6x.
3. **Accuracy at high multiplicity.** At 50.4 the GPU grid sits 2.11e-05 from
   its float64 twin (stable across runs) - above a strict 1e-5 relative bound,
   the same effect the science gates recorded for the quiet-Sun field: hundreds
   of thousands of contributions per cell with a wide flux dynamic range make
   float32 summation noise fractionally larger. Degridding (1.1e-07-4.2e-07) and
   the adjoint identity (1.6e-06-4.5e-06) both pass, so the pair stays adjoint;
   the number is a statement about float32 accumulation, not about a placement
   or weight error.

**Correction.** The "3.5-5x" headline from the previous round is the uniformly
spread case and should not be quoted alone; on real clustered coverage the
honest range is 1.7-3.6x, with degridding carrying almost all of it until the
atomic strategy is replaced.

### Pull model (measured): correct, and scan-bound

The 16x gridding/degridding gap at 50.4 lambda/cell is the atomic CAS merge, so
the obvious fix is a pull kernel: give every cell exactly one owner and let that
thread sum its own contributions, with no atomics at all. `polycols` implements
the minimal form - one cell per thread, one scalar accumulator, a 32x32
threadgroup, the same placement and weights as the push variants - and it is
verified the same way (within 1e-7 of the float64 twin at grid 64/128/512/1024,
and it agrees with the push variants' own rel_max of 2.11e-05 / 1.17e-06 on the
real data, so two independent accumulation strategies cross-check each other).

It is also **4.8-5.1x slower** on real data:

| configuration | push (`polyh`) grid | pull (`polycols`) grid | degridding |
|---|---:|---:|---:|
| 50.4 lambda/cell | **31.6 ms** | 160.7 ms | 1.9-3.9 ms |
| 8 lambda/cell | **17.6 ms** | 84.9 ms | 1.7-2.5 ms |

The reason is the scan: with one thread per cell, every thread walks the entire
tile bucket, so the cost is `sum over tiles of (cells in tile) x (visibilities
touching that tile)`. For clustered data at 50.4 that is roughly
`16 tiles x 1024 cells x 100 000 visibilities ~ 10^9` iterations, which matches
the measured 160 ms. Removing the atomics does not pay for a 1024-way redundant
scan.

The fix is finer binning, not kernel arithmetic: bin the visibilities per
*(tile, column group)* on the host, so a threadgroup only scans the visibilities
that can reach its columns. With 8 groups the scan drops 8x, which the measured
cost model puts at ~20 ms (50.4) and ~11 ms (8 lambda/cell) - at or below the
push model, without atomics. That is the next experiment, and the cost model
now predicts its payoff before it is written.

Two probe bugs surfaced while building this, both of which faked a kernel
failure and are now fixed: a poly variant missing from the polynomial-reference
list compares a raw grid against the *normalised* analytic one (a ~4x "error" in
an exact kernel), and tie test visibilities at +-63.5 cells are outside any grid
smaller than ~136 cells (out-of-range footprints, i.e. crashes at 64/128).

### Resolved: standalone ducc0 CPU baseline

Reproducing the real-data runs (both tools take the same two flags):

```
deps/install/bin/taql -ps -m 2000000 -o dump.txt \
  "select UVW[0] as u, UVW[1] as v, UVW[2] as w, real(DATA[0,0]) as xr, \
   imag(DATA[0,0]) as xi, FLAG[0,0] as f0 from LOFAR_3C196.ms"
mx-metal-probe --op realdata --uvw-file dump.txt --freq 138.477e6 --lambda-per-cell 8 ...
scripts/metal_cpu_baseline.sh --uvw-file dump.txt --freq 138.477e6 --lambda-per-cell 8 ...
```

Two traps worth remembering: `taql` prints **only the first 50 rows** unless
given `-ps -m N` (a 621 250-row dump silently became 54 lines the first time),
and the Homebrew `casacore` in `/opt/homebrew/bin` is linked against a removed
`libhdf5.310.dylib`, so the project's own `deps/install/bin/taql` is the one to
use in scripts and background jobs (interactive shells happen to resolve
`/usr/local/bin/taql`, which works).

`bench/metal/ducc0_wgridder_tool.cpp` (built and run by
`scripts/metal_cpu_baseline.sh`) times ducc0's own w-gridder, on the same
synthetic data or on the same real dump as the Metal probe, and is the CPU side
of both tables above. Getting it to run took
three separate fixes, each recorded in the tool's header because each one
produces a *crash rather than a wrong answer*:

* `pixsize = 1/nxdirty` - ducc0's grid coordinate is `frac(u_lambda*pixsize)*nu`,
  so an off-by-orders-of-magnitude pixel size makes the data land outside the
  grid and the unconditional scatter write bus-errors.
* `sigma_min/sigma_max = 1.1/2.0` - wsclean passes ducc0's defaults; passing the
  uv extent instead makes the w-plane count explode and the allocation die.
* The plain `ms2dirty`/`dirty2ms` entry points crash on this input even with
  correct parameters; wsclean only exercises `ms2dirty_bda`, so the tool does the
  same (one band, flat visibilities, empty weight and mask views, `flip_v`).
