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
