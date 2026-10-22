# dev-note.md — GPU deconvolution + prediction (2026-10-22)

Inversion is settled on ducc0. This round built the `-mgpu` path as
"GPU for prediction and deconvolution only" on `gpu-dev`, measured it
against pure CPU on the 15-slot LWA cutout, and kept what wins.

## Scope lock

- `work/wsclean/wgridder/wgridder.h`: Metal inversion runs only when
  `MX_METAL_ENGINE=metal|cpu-vkfft` is set explicitly. Plain `-mgpu`
  never touches inversion; the ducc0 call below runs untouched.
- `main/main.cpp`: the peak/convolution/prediction hooks register only
  when `settings.useGpu` is true. Same binary without `-mgpu` is pure CPU.

## Built (all behind `-mgpu`, all with CPU fallback)

| piece | hook | GPU core | gate |
|---|---|---|---|
| peak scan | radler `SetPeakScanHook` → `mx_peak_find` | Metal argmax, masked/bordered | `mx-peak-probe` ALL MATCH |
| convolution c2r | schaapcommon `SetConvolveC2RHook` → `mx_convolve_c2r` | Hermitian expansion (8e-08 CPU) + vkFFT c2c inverse | `expand-gpu-test` 3.0e-07 @1024, 5.1e-07 @3072 |
| prediction FFT | ducc0 `SetPredictFftHook` → `mx_predict_fft` | forward c2c, copy-swap per plane, thread-local plans | `mx-vkfft-fwd-probe` 3.3e-07 @1024, 5.9e-07 @3072 |

Probes: `mx-vkfft-probe` (c2c 3.2e-07), `mx-vkfft-batch-probe` (see below).

## Measured (15-slot flat, 931,920 rows, 3k/2.7amin exo template, `-j 8`)

| | CPU | `-mgpu` (peak+predict; convolve off) |
|---|---|---|
| inversion | 11.84 s | 12.12 s (ducc0 both) |
| prediction | 3.35 s | 3.41 s (tie) |
| deconvolution | 4.82 s | 5.17–5.39 s (hook overhead, in noise) |
| wall | 23.27 s | ~23.5 s |

Numerical gate with all hooks on: dirty, psf, image, model, residual
**all T2 PASS at 1–2e-06** (deep run converged to one basin this time;
earlier chaos splits were CLEAN basins, not hook errors — 1024/niter-200
passes all products bitwise-close).

## Negative results (pinned, do not retry blindly)

- Direct vkFFT R2C on Metal: 4 config variants, 100% mismatch incl.
  sign-flip character. Metal-backend R2C gap, not a stride fix.
  Probe removed; expansion + c2c supersedes it.
- Batched vkFFT (`numberBatches`) at 3072²: B=2: 13.0, B=4: 13.6,
  B=8: 23.7 ms/plane vs 12.5 serialized vs 7.1 CPU. Batching never beats
  serialized singles, which never beat the CPU (memory-bound; ducc0 does
  half the work, 4.7M-point c2r vs 9.4M c2c). `mx-vkfft-batch-probe`
  pins this.
- Consequence: convolve hook is **opt-in** (`MX_METAL_CONVOLVE=1`).
  Default `-mgpu` = peak + predict only.

## Scoped but deferred

Prediction shared-buffer pipeline (grids born in shared memory, chunked
FFT(N+1)/degrid(N) overlap): needs ducc0 `dirty2x` restructure
(`vmav` cannot wrap shared memory; signatures change). ROI cap ~0.5 s
(FFT itself ties), so deferred until deconv has a proven win to pair
with. Kill-switches `MX_METAL_NO_CONVOLVE` / `MX_METAL_NO_PREDICT`
stay for A/B.

## State

- Branches: `gpu-dev` (this work), `main` stays CPU.
- Patches (all verify vs `mx-base`): wsclean 0001–0049, schaapcommon
  0001–0006, radler 0001–0006.
- Harness: 125/128 (3 failures are pre-existing assertions in
  `metalinversion.mm`/`mxshaders.h`, untouched by this work).
- Datasets (`/tmp`): parent `ovrolwa-64mhz.ms` (17G), flat
  `lwa-15slot-flat.ms` (4.1G, rebuild: `mx-mscutout … "TIME < 5268786770"`,
  ~7 s), NRAO `srdp-3c286` (31G, never delete). Open: `ovrolwa-chunks`
  (16G staging, unattributed).
- Full write-up: `docs/bench/gpu-plan-after-inversion.md`.

## Next

1. True batched C2R needs working Metal R2C (blocked above) or an MLX
   `irfft2` probe (unmeasured; MLX drags runtime deps).
2. Prediction pipeline if a deconv win ever justifies ducc0 surgery.
3. The peak hook is the only shipped win; everything else is validated
   infrastructure waiting on (1).
