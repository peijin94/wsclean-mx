# Phase costs: gridding, w-screen, FFT, degridding

LWA 4-slot, 4096², 2amin, briggs 0, I, j8, 72 w-planes, dirty-only inversion.
"CPU" figures are ducc0's own `TimerHierarchy` output (`MX_WGRIDDER_VERBOSE=1`
exposes wsclean's never-set verbosity flag; off by default, no behaviour change).

## Inverse (dirty) — the comparable pair

| phase | CPU ducc0 | Metal path | ratio |
|---|---|---|---|
| **gridding proper** (u/v taps, all 72 planes) | 0.439 s | 3.3 s (kernel) | 7.5x |
| **FFT** (72 planes) | 0.912 s | 1.33 s | 1.5x |
| **wscreen + grid correction** | 0.267 s | 2.4 s (screen 0.20 + extract 2.2) | 9x |
| zeroing grid | 0.078 s | ~0.1 s (blit) | ~1x |
| index / visibility prep | 0.021 s | 1.60 s (item pass 0.77 + gather 0.83) | 78x |
| global corrections + alloc + scan | 0.032 s | ~0.5 s | 15x |
| **total** | **1.751 s** | **9.3 s** | 5.3x |

## Degrid (prediction) — CPU only, both paths

| phase | time |
|---|---|
| degridding proper | 0.420 s |
| FFT | 1.052 s |
| wscreen + grid correction | 0.224 s |
| zeroing grid | 0.082 s |
| building index | 0.030 s |
| **total** | **1.852 s** |

Prediction is not accelerated by `-mgpu` at all; both paths run the same ducc0
code, which is why prediction times matched in every clean comparison.

## Where "w-gridding" cost lives

Neither implementation has a separate w-gridding pass. The w-kernel weight is
folded into each visibility (ducc0: `wgt` per (row,channel,plane); ours:
`wWeight` on the host during gather), and the 72 w-planes each get their own
gridding + FFT + w-screen. So the w-term cost **is** the plane multiplier: 72x
the per-plane gridding and FFT work. Per plane that is 6.1 ms of gridding and
12.7 ms of FFT on the CPU, and 46 ms of kernel time on the GPU.

Consequence: the GPU kernel's 3.3 s is essentially all "w-plane replication" —
a 2-D inversion would run one plane and cost ~46 ms of kernel time.

## What this says about priorities

The FFT is 52% of ducc0's inversion but only 14% of the Metal path's, so
optimising it further is not where the Metal gap is. The gap is:

1. gridding proper, 7.5x slower on the GPU (0.44 -> 3.3 s),
2. w-screen/extract, 9x slower (0.27 -> 2.4 s),
3. visibility prep, 78x slower (0.02 -> 1.6 s).

Item 3 is host code we own and can parallelise further; item 2 is a
non-vectorised per-pixel complex multiply-add that should be SIMD; item 1 is
the kernel rewrite discussed in `why-gpu-slow.md`.
