# CPU gridding + GPU FFT (vkFFT) engine

New engine on `gpu-dev`: `MX_METAL_ENGINE=cpu-vkfft` with `-mgpu`. ducc0-quality
gridding on the CPU, vkFFT's 2-D inverse transform on the GPU through a shared
`MTLBuffer` (no copy), and the existing screen/extract step on the CPU.

## Status

| | 1024² (10amin) | 4096² (2amin) |
|---|---|---|
| ducc0 CPU (baseline) | 1.11 s | 2.65 s |
| Metal engine (gridding on GPU) | 4.87 s | 30.5 s |
| **cpu-vkfft engine** | **3.6-4.3 s** | **7.2 s** |
| numerical gate vs ducc0 | rel_rms 4.83e-06 | rel_rms 5.25e-06 |

Both PASS at the T2 tolerance the Metal path uses (5e-6). The grid the CPU
produces matches the Metal kernel's grid to rel_rms 4.1e-07, i.e. float32
rounding, and vkFFT matches ducc0's c2c to 3.5e-07 (`mx-vkfft-probe`).

So the engine is correct and 1.4x faster than the Metal path at 1024 and ~4x at
4k, but **still 2.7x slower than plain ducc0** — the win is not there yet.

## Where the 7.2 s goes (4096², 2amin)

Per w-plane: gridding, transform and extract together account for roughly 1.5 s
of the 7.2 s:

- gridding 16-180 ms per 4-plane group (~1.0 s total, cold-start skewed)
- FFT 50-75 ms per group of 4 planes (~13-18 ms/plane, matching the standalone
  vkFFT benchmark)
- screen + extract 11-13 ms per group

The remaining ~5.7 s is w-gridding bookkeeping that the engine still inherits
from the Metal path: the item pass, the per-plane gather (which materialises
~71M (item, weight) pairs), the occupied-line bitsets, and the global
corrections pass. That bookkeeping is now the entire optimisation target; the
gridding and FFT themselves are already at the right order of magnitude.

## What was built

- `metal/mxvkfft.{h,cpp}` — vkFFT wrapper. Owns a shared-memory `MTLBuffer`,
  plans a 2-D complex64 transform, `submit()`/`wait()` so the caller can
  pipeline. Verified against ducc0 by `metal/vkfft_probe.cpp`
  (`mx-vkfft-probe 3968` → rel_rms 3.5e-07 PASS).
- `metal/mxcpugrid.{h,cpp}` — CPU port of the Metal gridding kernel: same tap
  window, same ducc0 polynomial coefficients, same centred frame. Parallelised
  by output ownership (a thread owns a 32×32 tile and adds only the taps that
  land in it) so there are no atomics and no races; items are bucketed by the
  tiles their window can touch, including the periodic wrap.
- `metalinversion.mm` — engine switch plus `extractPlane()` lifted out of the
  loop so both engines share exactly one copy of the science step.
- Fallback: `MX_METAL_ENGINE` unset keeps the previous Metal behaviour.

## Pitfalls found (all fixed, all worth remembering)

1. **`polynomialKernel::eval()` does not take cell units.** Its argument is
   normalised to [-1,1]; using it with cell coordinates gives a smoothly varying
   error that no constant can fix (measured: grid 6x low, then 12x low). The
   poly shader's own interval-major Horner evaluation is the correct
   interpretation, so the CPU port evaluates `Coeff()` exactly that way.
2. **The poly kernel is not normalised.** ducc0 divides the kernel out in image
   space afterwards, so gridding must use the raw weights. The older hoisted
   shader normalised by the per-visibility sum, and copying that scales the grid
   by 1/support.
3. **metal-cpp returns autoreleased command buffers.** Releasing them double
   frees at the autorelease-pool drain (EXC_BAD_ACCESS inside `objc_release`,
   only reproducible inside wsclean's per-group pools, never in a standalone
   probe). The wrapper retains in `submit()` and releases in `wait()`.
4. **vkFFT 1.2.31's Metal LUT upload releases autoreleased objects** (two sites,
   `VkFFT_transferDataToGPU`/`FromGPU`). Patched in the vendored header with a
   comment; without it every run crashed in `initializeVkFFT`.
5. **The per-plane gather was doing ~71M random reads of the 16 GB MS** just to
   skip exact-zero visibilities. That check now happens once, in the
   row-ordered pass that builds the item lists.

## Next

1. Fold the per-plane gather into the gridding call: grid straight from the
   w-buckets, computing the w-weight inline, instead of materialising 71M
   `(item, weight)` pairs. That is the 5.7 s.
2. Drop the occupied-line bitsets for this engine (they only exist to band-limit
   a CPU FFT).
3. Then add the overlap: `submit()` without `wait()` and grid plane N+1 into a
   second buffer while vkFFT transforms plane N, which is what makes the GPU
   FFT free.
