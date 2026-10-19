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
