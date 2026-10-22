# GPU plan after dropping GPU inversion

Decision: **inversion goes back to ducc0.** Our cpu-vkfft engine stays behind
`MX_METAL_ENGINE=cpu-vkfft` as an experiment; `-mgpu` is redefined to mean
"GPU for prediction and deconvolution only". Measured reason: at 3k/2.7amin
ducc0 inverts in 8.29 s, our engine in 19.44 s, and the gap is ducc0's per-tap
SIMD gridding kernel, which we do not have.

## Where the remaining time actually is (3k^2, 2.7amin, exo-pipe deep)

| stage | CPU | gpu-dev today | note |
|---|---|---|---|
| inversion | 8.29 s | 19.44 s | ducc0 wins; keep it |
| prediction | 3.81 s | 3.74 s | `-mgpu` does not touch it |
| deconvolution | 6.70 s | 6.35 s | unchanged CPU code |

## Deconvolution: it is peak-finding, not subtraction

`sample` of the 6.7 s deconvolution (radler), 7 s at 1 ms:

| function | samples | share |
|---|---|---|
| `ThreadedDeconvolutionTools::FindMultiScalePeak` | 591 | 78% |
| `multiscale::MultiScaleTransforms::Transform` (Gaussian conv) | 240 | 25% |
| `ThreadedDeconvolutionTools::FindSingleScalePeak` | 78 | 8% |
| `peak_finder::FindWithMask` | 23 | 2% |

CLEAN's serial component subtraction — the part people assume dominates — does
not appear. The cost is a **memory-bound argmax scan over the scale stack**,
which is the ideal GPU shape.

Feasibility probe (`bench/metal/gpu_peakfind_bench.mm`, one threadgroup per
scale, threadgroup tree reduction, verified against the CPU argmax):

| scales | bytes | CPU | GPU | speedup |
|---|---|---|---|---|
| 8 | 302 MB | 87.0 ms | 10.5 ms | **8.3x** |
| 16 | 604 MB | 174.0 ms | 10.9 ms | **15.9x** |

GPU time is almost flat in the number of scales (parallelism-bound), and the
argmax matches the CPU exactly in both cases.

**Projection:** peak finding is ~5.2 s of the 6.7 s; at 8x that is ~0.65 s. The
Gaussian convolution (~1.7 s) is separable and GPU-friendly for another
~0.6 s. Deconvolution 6.7 -> ~2.2 s, total run 20.1 -> ~15 s.

### Integration

- Hook: `radler::algorithms::ThreadedDeconvolutionTools::FindMultiScalePeak`
  (`work/radler/cpp/algorithms/threaded_deconvolution_tools.*`). It already has
  the per-scale images in memory as `aocommon::ImageBase<float>`; the scan is
  the loop to replace.
- Bridge: add a small C API in `work/wsclean/metal` (`mx_peak_find(const float*
  const* planes, size_t n, size_t npix, float* out_val, size_t* out_idx)`) so
  radler does not need to know about Metal or ObjC. radler links against a thin
  static lib; wsclean already links `mx-metal`.
- Fallback: if the symbol is absent (non-macOS builds), keep the current CPU
  scan. Nothing about radler's public API changes.

## Prediction: FFT is 57% of it

`WGridder::PredictVisibilities` -> ducc0 `dirty2grid` (w-screen + FFT per plane)
-> `degrid_visibilities`. Instrumented cost at 4k: degrid 0.42 s, **FFT 1.05 s**,
w-screen 0.22 s, zeroing 0.08 s, index 0.03 s.

Integration: ducc0 is vendored, so add a hook at the per-plane FFT inside
`wgridder_impl.h` (`if (mx_fft_hook) mx_fft_hook(...)`) and chunk the plane loop
(~8 planes in flight) so group N+1's GPU FFT overlaps group N's degridding.
Projection: 1.85 -> ~0.8 s at 4k; 3.8 -> ~1.7 s at 3k.

## Order

1. GPU peak finding (validated 8-16x, largest single win).
2. Prediction FFT hook + chunked pipeline.
3. Multiscale convolution on GPU if the remaining 25% is worth it.
4. Re-benchmark 3k/2.7amin deep: CPU vs `-mgpu` (prediction+deconv only).

Gate for every step: same dirty image from both runs (already proven identical
to 5.3e-06), so any change in image/model/residual is attributable to the new
code alone.
