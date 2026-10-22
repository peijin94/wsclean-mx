# Why is the Metal path slower than the CPU?

Measured on the LWA 4-slot MS, 4096², 2amin, briggs 0, I, dirty only —
an apples-to-apples single inversion where the CPU takes 2.73 s.

## Budget for the -mgpu inversion (10.4 s before this round)

| component | time | note |
|---|---|---|
| GPU grid kernel (`gpu_exec`) | 3.81 s | command-buffer GPU busy time |
| CPU FFT pair (ducc0, 72 planes) | 1.36 s | after band-limiting |
| host: item pass + bucket | 0.77 s | split coords, w-phase, plane index |
| host: gather per plane | 0.83 s | w-weights + packed visibility vectors |
| host: batch prep / encode | 0.47 s | buffer creation |
| host: extract + w-screen | ~2.2 s | 72 planes x 16.8M pixels |
| corrections + setup | ~0.8 s | |

## What it is not

**Not disk IO.** The CPU path reads the same MS in the same way and finishes the
whole inversion in 2.73 s. Reading cannot be the differentiator when the
dominant stage is already faster end-to-end.

**Not CPU<->GPU transfer.** Instrumented byte counters for one inversion:
upload 1.42 GB, grid zero-fill 8.45 GB, grid copy 8.45 GB — 18.31 GB total.
Deleting the entire per-plane zero-fill (8.45 GB, 46% of all traffic) moved
`gpu_exec` by 0.06 s and the inversion by 0.29 s. Buffers are
`MTLResourceStorageModeShared` (unified memory, zero-copy), so the host reads
the grid without a copy and the GPU blits run at full bandwidth.

**Not the GPU being weak.** The kernel sustains ~1.1 G taps/s. The CPU's ducc0
kernels sustain ~1.5 G taps/s across 8 cores. The M2 GPU is therefore running at
roughly the throughput of **one CPU core**, i.e. ~0.2% of its FP32 peak. The
hardware is idle; the kernel cannot feed it.

## What it actually is

1. **The grid kernel is scalar and tap-loop bound.** Each visibility is one
   thread doing ~49 taps, each tap = one `poly_sample` (degree-10 Horner chain)
   + two threadgroup atomic adds, with two bound checks. There is no
   vectorisation and no register blocking.

   Ablations (4096/2amin, `gpu_exec`, run-to-run spread measured at +/-5% over
   three repeats of the unmodified build: 3.23/3.37/3.56 s):

   | build | gpu_exec |
   |---|---|
   | baseline | 3.23-3.56 s |
   | Horner chain removed (constant weights) | 3.07 s |
   | float CAS atomics -> native integer atomics | 3.70 s |
   | empty-tile early return | ~-0.1 s |
   | bounds checks replaced by masking (always 49 taps, ~23% more work) | 4.09-4.15 s |

   The masked variant costs exactly the extra taps (4.12/3.30 = 1.25x time for
   49/40 = 1.23x taps), so the in-tile `continue`s and their divergence are
   free and the kernel time is strictly linear in tap count — about 0.78 ns per
   tap.

   So neither the polynomial nor the atomic implementation is the limiter.
   Note the atomics are **float32, not double**: MSL on Apple silicon has no
   `double`, and the tile is `atomic_uint` holding float bits, added with a
   compare-exchange loop because Metal has no native float atomic add. Removing
   that loop entirely buys nothing, so the CAS retry is not the problem.

2. **Only ~2% of the dispatched tiles carry work**, but every one of the 15,376
   threadgroups is launched. Guarding them (`if (begin >= end) return;`) is now
   in the kernel and is free, but it is not the bottleneck — the empty tiles
   cost almost nothing either way.

3. **Half the wall clock is host work that exists only because the grid
   round-trips to the CPU 72 times.** The FFT (1.36 s), extract/screen (2.2 s),
   gather (0.83 s) and item pass (0.77 s) all serialise with the GPU. macOS has
   no MPS FFT, so the grid must come back for the transform.

## Changes from this round

- `threads_per_group` 256 -> 512: `gpu_exec` 3.81-3.96 -> 3.23-3.56 s
  (-10 to -15% given the +/-5% spread), inversion 10.1 -> 9.3 s. Re-verified: probe 2.95e-07, 50k slice 1.53e-08,
  1024 dirty T2 4.94e-06.
- Empty-tile early return in `grid_accumulate_poly` (exact: the grid is zeroed
  per plane and skipped tiles have no taps).
- Parallelised `apply_global_corrections` over rows (bit-identical).

## What would actually close the gap

- **Overlap host and GPU work.** The GPU is busy 4 s of 10; gather + FFT +
  extract could run for group N-1 while group N grids. Ceiling ~1.8x.
- **Rewrite the kernel** to own output cells per thread with register
  accumulation (no atomics) and vectorised tap evaluation. Needs ~3-5x to reach
  parity with one ducc0 core, more to beat 8.
- **Keep the grid resident and FFT on the GPU.** Blocked on platform: MPS has no
  FFT and Metal has no built-in transform; would need a hand-written Stockham
  kernel.
