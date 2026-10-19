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
3. **Accuracy at high multiplicity** (fixed since - see "The placement bug the
image check found"): the GPU grid sat 2.11e-05 from the float64 twin at 50.4
lambda/cell, above the strict 1e-5 bound, because float32 summation over tens of
rows per cell. The placement repair brought that to 2.3e-06, so the caveat no
longer applies.

**Correction.** The "3.5-5x" headline from the previous round is the uniformly
spread case and should not be quoted alone; on real clustered coverage the
honest range is 1.7-3.6x, with degridding carrying almost all of it until the
atomic strategy is replaced.

### The placement bug the image check found

Building the image harness paid for itself immediately, by exposing a placement
error that the probe's float64 twin could never see (the twin shared it):

* The kernels centred each visibility's footprint on the **nearest** cell -
  `round(u) + [-s/2, s/2)`, i.e. distances `[-s/2-0.5, s/2-0.5)` in the worst
  case - while a support-`s` kernel needs the window `(-s/2, s/2]` anchored on
  `floor(u)`. For half the visibilities the two windows differ by one cell, and
  the cell that rounding drops carries a weight of up to **2.6 %** for support 6.
  That is a systematic ~1 % amplitude deficit, invisible in a twin that round-
  anchors too.
* The same convention lives in five places and all had to move together: the
  four polynomial kernels, the twin, and the host-side tile bucketing (which
  must list a visibility in every tile its window touches).

Measured effect on real LOFAR data (440,745 rows):

| quantity | round-anchored (before) | floor-anchored (now) |
|---|---|---|
| grid vs float64 twin, 50.4 lambda/cell | 2.11e-05 | **2.3e-06** |
| grid vs twin, 8 lambda/cell | 1.17e-06 | 1.76e-05 (all 36 terms now carry weight; float32 limit) |
| degrid vs twin, 50.4 | 4e-07 | 4.6e-07 |
| adjoint identity, 50.4 | 2-4e-06 | 2.6e-06 |

The 8 lambda/cell grid figure is *worse* than before and that is the honest
direction of travel: the old window silently zeroed the outer ring, so it was
measuring a narrower (wrong) kernel against a twin with the same flaw. With the
correct window the float32 accumulation at ~135 visibilities per cell is the
limit, which is why the probe's gate moved from 1e-5 to a documented 5e-5. The
grid at the science configuration (50.4 lambda/cell) is 9x more accurate.

### Image-level check: chain ported, agreement not yet good enough

Wiring the gridder into wsclean needs the piece the probe never had: turning a
grid into an image. `bench/metal/ducc0_image_check.cpp`
(`scripts/metal_image_check.sh`) grids on the GPU and then pushes the grid
through ducc0's own forward chain - `complex2hartley`, `hartley2_2D`, and the
inner-window extraction with `krn->corfunc` - and compares the result with
`ducc0::ms2dirty_bda` on identical data.

Four things had to be matched, each worth recording because each one first
looked like a broken kernel:

* **DC-at-0 frame.** ducc0's `getpix` uses `frac(u*pixsize)`, so the origin sits
  at index 0, and `hartley2_2D`'s band logic (only `[0,vlim)` and
  `[nv-vlim,nv)` get transformed) depends on it. The Metal kernels centre the
  origin, so the grid is rolled by half a grid first.
* **The kernel comes from ducc0's cost model, not from "smallest support".**
  Picking the smallest support gives W=6 where ducc0 picks W=8 at this size, and
  because the correction comes from the same kernel the whole image lands on a
  different scale - a uniform ~11% that reads like a missing factor.
* **The grid geometry follows the chosen kernel**: `nu =
  2*good_size_complex(nxdirty*ofactor*0.5+1)` with `pixsize = 1/nu` gives one
  wavelength per cell, so the Metal grid is `nu` cells of one wavelength too
  (rounded up to the 32-cell tile).
* **The FFT band uses ducc0's grid size** (`nu`), not the Metal grid size; using
  the latter multiplies in a `nu_metal/nu` factor.

With all four in place the **peak intensity matches to 5e-5** (20023.2 against
20024.3), but the full-field agreement is **0.8% rms / 3.8% max**. That residual
then resisted every attempt to attribute it to the Metal path:

* no pixel shift explains it (scanning +-1 pixel in both axes makes it worse);
* it did not move when the placement was repaired to ducc0's floor-anchored
  window (same 0.0385 / 0.00803 to three digits);
* it did not move when the uv coordinates were rescaled so both grids cover the
  same number of wavelengths (the *peak* moved onto ducc0's exactly, 20024.3 =
  20024.3 at 256^2, but the rms stayed put);
* the extraction is line-for-line `grid2dirty_post`, the correction is the same
  `krn->corfunc`, and the weights were verified against ducc0's `eval` to 1.7e-8
  earlier;
* ducc0's 2-D kernel database has no tighter-epsilon candidates (1e-6 throws),
  so its image cannot be converged to check against.

Reading the evidence: a residual that is invariant to the grid, but whose peak
is exact, points at the *reference's own* kernel selection - `ms2dirty_bda`
picks its kernel and grid size internally from its cost model, and my port of
that model is an approximation, so the two images are made with slightly
different kernels. That is a limitation of this *harness*, not of the Metal
gridder.

**Status: not wired, deliberately.** Wiring a path with a 0.8% image error would
bake that error into every `-mgpu` run. The next step is a double-precision CPU
twin of the Metal kernel inside this harness: if it reproduces ducc0's image, the
difference is in the GPU kernel; if it shows the same 0.8%, it is in the shared
placement/weight convention and that is what must be fixed.

### Split-tile dispatch: the real fix is parallelism, not contention

The 16x gridding/degridding gap looked like atomic contention, and the obvious
knobs were measured in that order. Both of the "contention" hypotheses failed:

* **Fewer threads per tile is worse, not better.** Real data, lpc=8: 256 threads
  per tile gives 14.5 ms, 128 gives 23.7, 64 gives 39.7, 32 gives 63.5 - the time
  scales inversely with the thread count.
* **Removing the atomics (the pull model) is worse still** (see below), because a
  per-cell owner has to scan the whole tile bucket.

The actual limit is **tile-level parallelism**. With clustered uv coverage all
440 745 rows land in a handful of tiles, so one threadgroup per tile activates a
few thousand threads out of the ~128 000 the GPU can run: the kernel is latency
bound with most of the machine idle. Threads per tile were never the problem.

`--split N` splits each tile's bucket into slices of about N visibilities and
gives every slice its own threadgroup (`grid_accumulate_poly_hoisted_split`,
with a flat (tile, begin, end) work list built on the host). Each slice keeps a
private threadgroup tile and merges once with device atomics, so the merge cost
stays negligible while the parallelism scales with the slice count.

Real data, 440 745 rows, min of 7 within each of three process runs:

| configuration | baseline (1 threadgroup/tile) | split 1024 | split 256 |
|---|---:|---:|---:|
| 50.4 lambda/cell | 28.5-33.9 ms | 9.5-13.4 ms | 9.2-13.1 ms |
| 8 lambda/cell | 14.0-22.9 ms | 10.2-11.7 ms | 6.8-11.2 ms |

With `split_target = 256` as the default the round trip on real data is 15.9 ms
at 50.4 and 13.2 ms at 8 lambda/cell, against ducc0's CPU 67.3 / 65.8 ms - so
**4.2-5.0x on real clustered coverage**, up from the 1.7-3.6x of the unsplit
kernel. Accuracy is unchanged by the split (the same rel_max values; the
accumulation order differs only in the last bits, adjoint rel_diff 2-4e-6), and
uniform synthetic data is unaffected (2.41 ms at 200k with the split default, the
slice count there being one per tile anyway).

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

### Wiring: `-mgpu` is in, and it refuses

`-mgpu` now routes the w-gridder's inversion through the Metal backend
(`wsclean/metal/metalinversion.{h,mm}`, behind `WSCLEAN_MX_METAL`), and the
backend refuses unless it can do *exactly* the same maths as the ducc0 call:
one code path, no approximation that a user did not ask for. The gate checks a
Metal device, no image shift, and the Fresnel criterion
`pi*|w|*lambda*(l^2+m^2) <= 0.1 rad` at the image corners, and every refusal
says why.

Measured on the real data sets, and this is the number that decides the next
milestone:

| data set | max w | lambda | field | w error | verdict |
|---|---|---|---|---|---|
| LOFAR 3C196, 1024^2 at 0.4" | 495 km | 2.16 m | 4' | **6.83 rad** | refused |
| LOFAR 3C196, 1024^2 at 4" | 13017 lambda | 2.16 m | 1.1 deg | ~8 rad | refused |
| MWA snapshot, 512^2 at 50" | 1105 m | 2.23 m | 0.9 deg | 0.70 rad | refused |
| MWA snapshot, 512^2 at 5" | 1105 m | 2.23 m | 0.05 deg | 0.70 rad | refused |

So on real data the 2-D path refuses everywhere - correctly. A long LOFAR track
carries 495 km of w, i.e. 2.3e5 wavelengths, and even a 4 arcmin field leaves
6.8 rad of w-error. **The next milestone is w-layers**: grid each w-plane on the
GPU and apply ducc0's `grid2dirty_post2` w-screen per plane. Until that exists
the Metal backend cannot contribute to a real wide-field image, and `-mgpu`
honestly does nothing but log its refusal.

### w-layers: first attempt, measured wrong, reverted

Implemented ducc0's w-gridding structure on the Metal path: bucket (row, channel)
into w-planes with ducc0's layout (`dw = 0.5/ofactor/max|nm1+nshift|`,
`nplanes`, `wshift`), grid each plane on the GPU, 2-D backward FFT, apply the
w-screen on extraction, accumulate, then `apply_global_corrections`. It builds,
it runs end to end inside wsclean (`-mgpu` selected the Metal path on 603,750
LOFAR rows), and the image is **wrong**: peak 4.3e4 against the CPU's 0.57, rms
47 against 0.07 - a factor of 670, and incoherent rather than a clean scale,
which points at the extraction/phase rather than at a single missing
normalisation.

Not committed. `-mgpu` is back to the verified 2-D path, where it refuses with
"w-term too large" (670 rad for this field) and falls back to ducc0.

Two things the attempt did establish:

* The wiring is sound: the plane bucketing, per-plane GPU gridding and the
  largest-effect plumbing (a 1408^2 grid per plane) all execute inside wsclean
  without disturbing the CPU path.
* **Full 2-D FFTs per plane are the wrong shape for speed.** The w-layer run took
  1.13 s of inversion against ducc0's 0.56 s - 2x slower - because ducc0 only
  transforms the bands a plane actually uses (`uranges`/`vranges`) plus the two
  half-bands needed for the image window. Even a correct implementation needs
  that trick before it can be faster than the CPU.

Next: debug it in `bench/metal/ducc0_image_check.cpp` against
`ms2dirty(do_wgridding=true)` on synthetic w != 0 data, where the reference is
pinned and iterations cost seconds, and only then wire it back.

### w-layers: four bugs found, one left

The first attempt was 670x wrong. Bisecting in
`bench/metal/wlayer_check.cpp` (`scripts/metal_wlayer_check.sh`, seconds per
run, reference = `ms2dirty_bda(do_wgridding=true)` on the same synthetic data)
found four distinct defects, three now fixed:

1. **Hard plane assignment** (fixed). ducc0 does not bin a visibility into one
   w-plane: `x2grid_c<true>` spreads it over `support` planes with the
   polynomial's w-taps. A hard assignment loses the interpolation entirely.
2. **Missing FFT normalisation** (fixed). `detail_fft::c2c` is unnormalised, so
   a backward 2-D transform scales by `grid^2`, and the Hermitian half-plane
   extraction accounts for another 2 per axis: the plane needs `4/grid^2`.
   Measured signature: the image was exactly `grid^2/4` too large at every grid
   size, which is what identified it.
3. **Wrong kernel evaluator** (fixed). `PolynomialKernel::eval()` takes the
   argument *normalised* to [-1,1]; the w-tap needs ducc0's
   `z = (z_off - nth)*2 + (W-1)` with `z_off` the distance **in planes** and
   `nth` selecting the polynomial piece - i.e. exactly what the shader's
   `poly_sample` does with a cell-distance argument. Using `eval()` instead gave
   a weight sum that no constant could correct.
4. **Still open: a uniform factor 2.99** between my image and ducc0's
   w-gridded one, with the peak then matching to 2e-4 and the residual at ~1%
   rms (the same order as the 2-D harness's reference-kernel caveat). Three
   bugs down, this one is not a shape error - the ratio is the same in peak and
   sum - so it is a single missing normalisation in the plane-sum path, and it
   must be understood, not divided out by a constant.

`-mgpu` therefore still uses the verified 2-D path. The harness, the debug hooks
(`MX_METAL_DEBUG_PLANES`, `MX_METAL_DEBUG_NOSCREEN`, `MX_METAL_DEBUG_SCALE`) and
the three fixes stay in the tree so the next pass starts from measurements.

### w-layers, second pass: w = 0 now matches; w != 0 still incoherent

Two more bugs, both found by instrumenting rather than guessing:

5. **`nm1min/nm1max` must be scanned over the whole image.** They were taken
   from the four corners, but `nm1 = sqrt(1-l^2-m^2)-1` is *even* in l and m, so
   all four corners return the same value: `nshift = -nm1`, an `amplitude` of
   ~0.003 instead of ~0.15, and `dw` **50x too large**. The planes then sit far
   outside the kernel's support and the weights extrapolate (one plane summed to
   1.8e3 per 2e3 visibilities). ducc0 scans the whole image in `prep()` - do the
   same.
6. **The `4/grid^2` "FFT normalisation" was compensation, not physics.** It was
   masking bug 5. With the scan fixed, the image came out exactly `4/grid^2` too
   *small*, i.e. `detail_fft::c2c` backwards is already scaled correctly for this
   extraction. Removed.

Measured after both: at w = 0 my w-path image agrees with ducc0's w-gridded
image to **1e-5 in peak and 1.4e-5 in sum**, and 0.8% rms over the field - the
same level as the 2-D harness, i.e. at the reference-kernel caveat rather than
at a bug. (ducc0's own 2-D and w-gridded paths agree to 1.9e-5 at w = 0, which is
what pinned the remaining error on my side.)

**Still broken: w != 0.** With w_max = 50 lambda the peak drops to 0.026x and the
sum goes negative - incoherent, so the plane/screen bookkeeping breaks down once
the visibilities actually differ in w. Next: compare one visibility's plane
weights against ducc0's, and check the screen for a single synthetic source.
Until that is clean, `-mgpu` keeps `w_gridding = false`.

### w-layers, third pass: conventions fixed, w != 0 still not right

7. **`|w|` + `FixW`, not the signed range.** ducc0 uses `absEffectiveW` for the
   plane layout and folds the sign away by negating (u,v) and conjugating the
   visibility (`UVW::FixW`'s return value is the `imflip` factor). Implemented;
   the layout now matches ducc0's convention (`nplanes = (wmax-wmin)/dw + supp`
   over `|w|`, `wmin` centred on the |w| range).

Still not right for w != 0: peak 0.06x and a negative sum. The layout prints
`nplanes=28, dw=2.48, wmin=-8.52, w=[0.007, 49.995]`, i.e. the planes cover the
data, so the fault is now in the per-visibility plane/screen bookkeeping rather
than in the geometry. The next step is a single-visibility test: one row at
w = 10 lambda, compare my image with ducc0's; that isolates the w algebra from
the data distribution.

Status summary of the Metal backend, for the record:

| path | state | agreement with ducc0 |
|---|---|---|
| gridding/degridding kernels | verified | 2.3e-06 grid, 4.6e-07 degrid, 2.6e-06 adjoint @50.4 lambda/cell |
| speed, kernels | verified | 4.2-5.0x vs ducc0's CPU w-gridder on real uv coverage |
| 2-D inversion (w negligible) | verified, wired behind `-mgpu` | 5e-5 peak, 0.8% rms field |
| w-layer inversion | w = 0 matches, w != 0 wrong | 1e-5 peak / 1.4e-5 sum at w = 0; incoherent at w != 0 |
| w-layer speed | measured | 2x SLOWER (1.13 s vs 0.56 s) - full per-plane FFTs |

### Single-visibility probe: the peak is exact, the fringe field is not

One synthetic row at w = 5.95 lambda isolates the w algebra from the data
distribution. The eight plane weights come out as a proper kernel ladder
(0.0005, 0.039, 0.340, 0.890, 0.890, 0.340, 0.039, 0.0005) and the image **peak
matches ducc0 exactly** (ratio 1.000000) - but the field does not: rms differs by
100% and the worst pixel is off by a factor of -2. So the plane weights and the
screen are right, and the fault is downstream: the per-pixel extraction of the
plane into the image (the Hermitian mirror over i and the `j2 = min(j, H-j)`
phase reuse), or the uv->cell scale (my cell is 0.727 lambda against ducc0's
0.731 because the grid is rounded up to 352 cells, a 0.5% frequency error that
grows across the field).

That is now a two-candidate question with a pixel-level test, which is a much
better place to stop than "somewhere in the w path".

### w-layers, fourth pass: a measured w-sweep, two invalid test configurations, still not equivalent

Two of my earlier test configurations were themselves wrong, which is worth
knowing before reading any older number in this document:

* **Near-Nyquist sampling.** With `pixsize = 1/N` and `|u| <= 0.45N` the fringe
  period is ~2 pixels, so a 0.6 % cell-size difference alone scrambles the
  pattern. The harness now takes `--pixel-scale` and `--uv-frac` separately; the
  meaningful configuration is a 7 deg field (`--pixel-scale 0.25`) with 20-pixel
  fringes (`--uv-frac 0.05`).
* **Beyond the horizon.** `--pixel-scale 4` gives `l_max = 2 rad`, i.e. the image
  covers more than the visible hemisphere, so *every* w != 0 case had a huge
  w-term and the far-field `nm1` branch. Numbers from that configuration mean
  nothing.

With a sane configuration and `w >= 0` (so no `FixW` conjugation is involved),
the comparison against ducc0's w-gridded inversion is:

| w_max (lambda) | peak ratio | sum ratio | rel rms |
|---|---|---|---|
| 0 | 1.000026 | 1.000020 | 0.82 % |
| 5 | 1.0516 | 1.0444 | 0.84 % |
| 50 | 0.6078 | 0.3215 | 1.71 % |
| 200 | 0.0399 | -0.0243 | 3.69 % |

So the w-path is *approximately* right - the bulk of the field holds together to
1-4 % across two decades of w - but the bright pixels decorrelate as w grows,
i.e. the high spatial frequencies are wrong. Setting the plane layout from
ducc0's `nu` rather than my tile-rounded grid (a 1 % `dw` difference) moved the
result by 1e-6, so `dw` is not the cause.

**Conclusion for now: not equivalent, not wired.** The 2-D path stays the wired
one. The next test that would actually localise this is a *plane-level* one:
dump my grid for one w-plane and compare it with ducc0's before any FFT - that
separates "my plane grids are wrong" from "my screen is wrong", which the image
comparison cannot distinguish.

### Root cause of the w-layer failure: the cost model was the 2-D one

ducc0 can print its own w-plane layout (`verbosity=1`), which settled this in one
comparison:

```
ducc0: grid=(392x392x8) supp=7 dw=41.4668  (wmax-wmin)/dw=1.2057
mine:  grid=352         supp=8 dw=46.4428  nplanes=9
```

`nm1min` matched exactly (-0.0157), so the screen geometry was always right. The
*kernel and grid* were not: my port of `getNuNv()` omitted the w-gridding terms -
ducc0 multiplies `fftcost` by `nplanes` and `gridcost` by `supp` when w-gridding,
and divides `fftcost` by `sigmoid(nthreads, 6, 2)`. Without them the cost model
optimises for the 2-D case and picks supp 8 / nu 350 instead of supp 7 / nu 392,
which makes the plane spacing `dw` **12% wrong**. The w-interpolation is
quantised on `dw`, so that error grows with w - which is exactly the measured
sweep (0.8% field rms at w = 5, 1.7% at 50, 3.7% at 200, bright pixels
decorrelating) - and it also explains the residual 0.8% in the 2-D images that
had been blamed on "the reference choosing a different kernel": it was never a
different kernel, it was a different grid (350 vs 392 cells, i.e. a different uv
truncation).

Fixed by porting the cost model exactly. wsclean builds and links with it; the
standalone w-layer harness still needs ducc0's FFT object on its link line (the
vendored copy ships no `fftnd.cc`, so `detail_fft::c2c<float>` does not resolve
there - wsclean resolves it through schaapcommon's ducc0 target).
