# GPU FFT feasibility (the "CPU gridding + GPU FFT" proposal)

Question: the Metal grid kernel is 7.5x slower than ducc0's gridding (see
`phase-costs.md`), so should we drop GPU gridding, grid on the CPU, and put the
FFT on the GPU, using unified memory to avoid the copy? And could the two
overlap?

Measured with `bench/metal/mps_fft_bench.mm` (MPSGraph `fastFourierTransform`,
complex64, 2-D transform, 5 reps after warm-up, verified against the exact DC
term = sum of inputs).

## MPSGraph FFT vs ducc0 CPU FFT (full transform, one plane)

| grid | factorisation | MPSGraph GPU | ducc0 CPU (8 thr) | GPU speedup |
|---|---|---|---|---|
| 2048 | 2^11 | 4.5 ms | 5.6 ms | 1.24x |
| 3072 | 2^10*3 | 17.3 ms | 16.6 ms | 0.96x |
| 3840 | 2^8*15 | 20.6 ms | 23.9 ms | 1.16x |
| 4096 | 2^12 | 20.1 ms | 28.4 ms | 1.41x |
| **3968** | **2^7*31** | **102.6 ms** | **34.6 ms** | **0.34x** |

The real grid for 4096px/2amin is 3968 = 2^7*31 (nu rounded up to a multiple of
32 for tile alignment). That is the worst case for MPSGraph: 3x slower than the
CPU. Power-of-two sizes are the only ones where the GPU wins, and then only
1.2-1.4x.

## Why that is not enough

Our production path does not run a full FFT — it band-limits to the occupied
lines and the dirty rows, which already costs only **18.6 ms/plane** (1.34 s for
72 planes). That is faster than the best MPSGraph full transform (20.1 ms at
4096) and nearly 6x faster than MPSGraph at the real grid size.

So "CPU gridding + GPU FFT" would be:

    0.44 s gridding + 1.44 s GPU FFT (72 x 20.1 ms) + 0.27 s wscreen = 2.15 s

against ducc0's 1.75 s for the whole inversion. Slower, even ignoring the wscreen
and extract that also have to run.

For the GPU to win here it would have to run the FFT at < 6.1 ms/plane (the CPU
gridding cost) to hide behind gridding, or < 12.6 ms/plane to beat the
band-limited CPU FFT. MPSGraph is at 20.1 ms in its best case.

## What would change the answer

1. **Band-limit on the GPU too.** MPSGraph can transform a sliced tensor, so the
   occupied-column / dirty-row structure could in principle be kept. That is the
   only route to single-digit ms per plane. Untested.
2. **Batch the planes into one call** (`(nplanes, N, N)` transform over axes 1,2).
   Measured, and it does not help at our size:

   | grid | batch | GPU total | GPU per plane | CPU 8thr per plane |
   |---|---|---|---|---|
   | 4096 | 1 | 20.1 ms | 20.1 | 29.3 |
   | 4096 | 2 | 39.3 ms | 19.7 | 30.1 |
   | 4096 | 4 | 77.3 ms | 19.3 | 29.3 |
   | 4096 | 8 | 340.7 ms | 42.6 | 32.1 |
   | 2048 | 1 | 4.5 ms | 4.5 | 5.9 |
   | 2048 | 4 | 15.1 ms | 3.8 | 6.0 |
   | 2048 | 16 | 50.8 ms | 3.2 | 5.9 |

   At 4096 MPSGraph already pipelines single calls, so batching only adds memory
   pressure (8 planes = 2.1 GB and per-plane time doubles). At 2048 batching
   does amortise (3.2 vs 4.5 ms) but that size is not ours.
3. **vkFFT — MEASURED, and it does deliver.** See below.
4. **MLX** (`mlx.core.fft`) dispatches to MPSGraph/MLX primitives for FFT, so it
   inherits the same size sensitivity; it is also a C++/Python framework that
   would have to be linked into wsclean.

## The overlap idea, bounded

ducc0's inversion is 1.75 s: gridding 0.44, FFT 0.91, wscreen 0.27. A perfect
producer/consumer overlap of gridding with FFT can hide at most the smaller of
the two, i.e. ~0.44 s, giving ~1.3 s — a 25% win over ducc0, and only if the GPU
FFT is not slower than the CPU one, which at 3968 it is by 3x.

Against the current -mgpu path (9.2 s) the interesting number is different: the
Metal path is 5x slower than ducc0 overall, and the FFT is only 14% of it. Moving
the FFT to the GPU cannot fix a path whose losses are in gridding (7.5x), extract
(9x) and visibility prep (78x).

## Grid size side-note

Padding the grid to 4096 (power of two, ~3% more samples) measured
FFT 1.34 -> 1.28 s and inversion 9.32 -> 9.18 s (-1.5%). Reverted: not worth a
layout change, because band-limiting already dilutes the size penalty.


## vkFFT (native Metal backend) — this is the one that works

`bench/metal/vkfft_bench.cpp`, vkFFT v1.2.31 monolithic header + the repo's
`metal-cpp`, `-DVKFFT_BACKEND=5`. complex64 2-D transform, in-place, 5 reps,
correctness checked against the exact DC sum.

| grid | factorisation | vkFFT Metal | ducc0 CPU 8thr | speedup | MPSGraph (for contrast) |
|---|---|---|---|---|---|
| 512 | 2^9 | 0.1 ms | 0.3 ms | 2.0x | 1.4 ms |
| 2048 | 2^11 | 3.7 ms | 6.6 ms | 1.78x | 4.5 ms |
| **3968** | **2^7*31** | **14.2 ms** | **37.8 ms** | **2.67x** | **102.6 ms** |
| 4096 | 2^12 | 14.6 ms | 29.8 ms | 2.04x | 20.1 ms |

At the real grid (3968 = 2^7*31) vkFFT is **7.2x faster than MPSGraph** and
2.67x faster than ducc0's full FFT. The 31-point factor that destroys MPSGraph
costs vkFFT almost nothing.

### What that is worth against the band-limited path

Our production FFT only transforms the occupied lines (18.6 ms/plane at 3968),
so vkFFT's full transform (14.2 ms/plane) is just 1.3x faster, worth ~0.3 s of
a 9.2 s inversion. **But the point is not the raw speed, it is that the FFT is
now on the GPU while the CPU is free**:

    CPU gridding 0.44 s  ||  GPU FFT 1.02 s (72 x 14.2 ms)  ->  ~1.05 s
    serial ducc0                                              ->   1.75 s

The gridding fits entirely inside the FFT window, so a producer/consumer
pipeline could take the inversion from 1.75 s to roughly 1.0-1.1 s (1.6x) while
keeping ducc0's exact gridding maths. That is the first configuration in this
whole investigation where the GPU has a defensible role.

### Integration notes (learned the hard way)

- vkFFT master (v2) changed the config API completely (`buffer` is now
  `MTL::Buffer**`, `dimensionCount`, no `MTLDevice` field). The classic API used
  here is **v1.2.31**, whose `vkFFT.h` is still a single 2 MB header
  (`raw.githubusercontent.com/DTolm/VkFFT/v1.2.31/vkFFT/vkFFT.h`). v1.3.0+ split
  the header into `vkFFT/vkFFT_*` subdirectories.
- Metal needs `metal-cpp` (Apple's C++ bindings), included in the repo.
- `VkFFTAppend` is **async and does not submit**: you must create
  `queue->commandBuffer()` + `computeCommandEncoder()`, pass them in
  `VkFFTLaunchParams`, then `endEncoding`, `commit`, `waitUntilCompleted`.
  Timing without the wait reports 0.0 ms and the output buffer stays empty.
- The plan is **in-place**: refresh the input buffer before each timed run or you
  accumulate transforms.
- `deleteVkFFT()` segfaults with this header/metal-cpp pairing; skip it at exit
  (`MX_VKFFT_CLEANUP=1` to force it).
- Build the TU with `-O3` is fine, but a `-O2` build of the same source
  intermittently segfaulted during init; if that reappears use `-O1`.
