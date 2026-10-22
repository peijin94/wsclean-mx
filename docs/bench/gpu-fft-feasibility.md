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


## MLX — custom Metal kernels, and the size dependence is the whole story

Checked `ml-explore/mlx` `mlx/backend/metal/fft.cpp` (877 lines) and
`mlx/backend/cpu/fft.cpp`. **MLX does not use MPSGraph for FFT**: it generates its
own Metal kernels from a Stockham mixed-radix core (radices 13,11,8,7,6,5,4,3,2)
executed in threadgroup memory, with pocketfft only on the CPU stream and for
twiddles.

Plan selection (`plan_fft`):

| condition | algorithm |
|---|---|
| n <= 4096, all factors in the radix set | Stockham mixed-radix, one threadgroup |
| n <= 2048 with one unsupported prime p, p-1 radix-decomposable | Rader |
| otherwise (n > 2048 with an unsupported prime, or p-1 not decomposable) | Bluestein, padded to `next_fast_n(2n-1)` |
| n > 4096, power of two | four-step, no transpose (n2 = 1024 if n > 65536 else 64) |
| n > 4096, not power of two | multi-upload Bluestein (four-step) |

Hard limits: `MAX_STOCKHAM_FFT_SIZE` 4096, `MAX_RADER_FFT_SIZE` 2048,
`MAX_BLUESTEIN_FFT_SIZE` 2048; largest transform 4096^2.

Measured, MLX 0.32.4 (`/tmp/mlxvenv`, `mx.fft.fft2`, complex64, GPU, 5 reps):

| grid | MLX | vkFFT | ducc0 CPU 8thr |
|---|---|---|---|
| 1024 | 1.6 ms | — | — |
| 2048 | 3.8 ms | 3.7 ms | 6.6 ms |
| **3968 = 2^7*31** | **107.5 ms** | **14.2 ms** | 37.8 ms |
| **4096 = 2^12** | **10.4 ms** | 14.6 ms | 29.8 ms |

3968 has the prime 31, which is not a supported radix, and 3968 > 2048 so Rader
is out, so MLX falls to **Bluestein with a padded ~8000-point transform** (three
transforms of double size). That is why it lands at 107 ms — essentially the same
as MPSGraph's 102 ms. The penalty was never about the vendor, it is the prime
factor.

At 4096 MLX is the fastest thing measured: 10.4 ms, 2.9x ducc0 and 1.4x faster
than vkFFT.

Batching: 4 planes = 9.09 ms/plane, 8 planes = 10.98 ms/plane (memory pressure),
3968 with batch 4 fails outright with `[METAL] Command buffer execution failed:
Insufficient Memory` because each Bluestein plane needs the ~8000^2 padded buffer.

### Consequence: choose the grid size first

| grid choice | best GPU FFT | per plane | 72 planes |
|---|---|---|---|
| 3968 (current, = nu rounded to 32) | vkFFT | 14.2 ms | 1.02 s |
| 4096 (next power of two) | MLX | 10.4 ms | 0.75 s |

Rounding the grid up to 4096 costs ~3% more samples and is the only case where
MLX beats vkFFT. vkFFT is the robust choice (any size, header-only); MLX is
faster but only at power-of-two sizes and brings a much heavier dependency
(mlx + mlx-metal dylibs and its kernel library).


## Why MPSGraph is slow: the prime-factor cliff (measured)

MPSGraph is Apple's own stack, so it should be the best-tuned option. It is —
right up to the point where the size contains a prime factor it has no radix
kernel for. Same-size / different-factorisation 2-D sweep
(`bench/metal/mps_fft_2d_sizes.mm`, complex64, 3 reps):

| size | factorisation | time | ns/point |
|---|---|---|---|
| 4032 | 2^6*3^2*7 | 24.2 ms | 1.49 |
| 4096 | 2^12 | 22.9 ms | 1.37 |
| 3960 | 2^3*3^2*5*11 | 30.8 ms | 1.97 |
| 3969 | 3^4*7^2 | 31.6 ms | 2.01 |
| **3968** | **2^7*31** | **102.8 ms** | **6.53** |
| 3001 | prime | 51.1 ms | 5.67 |

3960, 3969 and 4032 are all within 1% of 3968 in size and run at 1.5-2.0
ns/point. 3968 runs at 6.53 ns/point — **3.3-4.4x slower, and the only
difference is the prime 31**.

So MPSGraph has no radix-31 kernel, and a size containing an unsupported prime
falls back to Bluestein: pad to a smooth/power-of-two length >= 2n-1, then pay
~3 transforms of the padded length plus pointwise multiplies. That is where the
4x goes. A prime size (3001) shows the same penalty, slightly milder because its
padded length is smaller.

1-D transforms at the same sizes hide this because the measurement is dominated
by ~0.5 ms of fixed call overhead: 4096 = 0.52 ms, 3968 = 0.89 ms, 4096^... so a
1-D microbenchmark would wrongly conclude the penalty is only 1.7x.

For contrast, vkFFT reports `useBluesteinFFT=[0,0]` at n=3968 — it generates a
dedicated radix-31 kernel and transforms the size directly, no padding, hence
14.2 ms. MLX has radices only up to 13, so it takes the same Bluestein path as
MPSGraph and lands at 107.5 ms.

### Ranking, for the record

| grid | MLX | vkFFT | MPSGraph | ducc0 CPU 8thr |
|---|---|---|---|---|
| 4096 (2^12) | **10.4 ms** | 14.6 ms | 22.9 ms | 29.8 ms |
| 3000-ish smooth | — | — | ~19-31 ms | — |
| 3968 (2^7*31) | 107.5 ms | **14.2 ms** | 102.8 ms | 37.8 ms |

MPSGraph is not bad at FFT — it is 1.6x behind vkFFT and 2.2x behind MLX at
power-of-two sizes. Its failure is categorical, not gradual: one unsupported
prime factor and it drops to a padded Bluestein.
