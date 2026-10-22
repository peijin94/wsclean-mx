# Development note — audited GPU prediction and deconvolution

Updated 2026-10-22. Full evidence and plan:
`docs/gpu-next-optimization-2026-10-22.md`.

## Detailed utilization profile

`docs/gpu-profiling-2026-10-22.md` contains the current bottleneck audit:
52 real WSClean runs, same-clock CPU/GPU timelines, device gauges, CPU sampling,
thread scaling and validated plan/resource-reuse ablations. Default prediction
is CPU-fed; convolution suffers repeated resource creation and copies; peak
search copies and serializes. 4K all-hooks shows memory pressure. Instrumentation
is opt-in, not a delivered optimization. Raw scientific failures remain open.

## Follow-up

`docs/gpu-followup-2026-10-22.md` supersedes the suite/quarantine status below.
Retired inversion is excluded from production linkage and rejects explicit
selection; its separate archive diagnostic still fails. PSF reuse now retains
`WSCTBEAM` (radians), including correct MFS handling and malformed-key rejection.
With matching automatic scales, three GPU controls and the null control pass
all pixel/source gates; all seven common-input CPU/GPU/null models are bitwise
identical. A CPU-only +1 ULP input perturbation changes the model by 0.168%.
The corrected symmetric source metric still leaves the original family at
6/10: those failures are preserved, not waived. Final receipts and commit/patch
provenance are in `docs/bench/gpu-followup-20261022/delivery.json`.
Next optimization is bounded convolution-plan/kernel reuse, not GPU inversion.
The prior timing gain below is unchanged; this follow-up adds no speed claim.

## Earlier audit state (retained for provenance)

- Root `gpu-dev`; published CPU release / `main` unchanged.
- **Plain `-mgpu` now means GPU prediction only.** Inversion and
  gridding/degridding stay on ducc0. No hooks run without `-mgpu`.
- Prediction uses two compact shared planes, ordered consumption and per-plane
  CPU recovery. No grid-copy round trips; runtime counters verify actual work.
- Native padded R2C/C2R and batched multiscale convolution work numerically.
  Corrected tiled peak search uses real radler as its oracle.
- Deconvolution offloads are slower in current production measurements, so
  `MX_METAL_CONVOLVE=1` and `MX_METAL_PEAK=1` remain explicit experiments.
- CPU-only builds reject `-mgpu`. `MX_METAL_DEBUG_TIMING=1` prints proof counters.
- Do not use the retired `MX_METAL_ENGINE` inversion experiments: their archived
  GPU-gridding probe still fails.

## Measured result

Apple M2; 15-slot standalone MS; 3072² / 2.7amin; 20,000 multiscale iterations;
8 threads. Same frozen executable, two excluded warmups, four AB/BA pairs.

| Median | CPU | GPU prediction |
|---|---:|---:|
| Inversion | 11.388 s | 11.340 s |
| Prediction | 3.275 s | 2.599 s |
| Deconvolution | 5.135 s | 5.135 s |
| Wall | 21.890 s | 21.055 s |

**20.6% less prediction time, 3.8% less total time.** GPU won every pair.
This is not a claim that GPU deconvolution is faster.

## Validation and limits

- Identical-model CLI prediction into two disposable MS clones: all 178,928,640
  complex MODEL_DATA cells compared; relative RMS 5.90e-7, max/peak 7.01e-7.
- Deterministic deep CPU repeat is bitwise identical. All CPU/GPU deep products
  pass T2 at `-j 1`; image 7.18e-7 and residual 9.45e-7 relative RMS.
- Real-device prediction differential: 12 supported cases, 681 completed planes,
  zero fallback/copy bytes; production-size 3960² grid also passes.
- CPU build: 136 Python tests and linked native regressions pass.
- Metal: new active-path gates pass, but the aggregate suite intentionally fails
  on the archived gridding probe. Do not report blanket green.
- **Threaded scientific acceptance remains open:** initial 0/4 source-envelope
  passes; balanced follow-up gives 6/10 against 10 CPU references, with the same
  conservative limits. Saved model differences arise before GPU prediction in
  this workload, but failed gates remain recorded rather than waived.
- All 108 files in both the benchmark input and original 15-slot source retained
  their hashes. Science inputs were not predicted into.

## Corrections that must not be forgotten

Earlier end-to-end GPU claims were invalid: main's feature macro was missing,
so registration was compiled out. The old peak oracle also shared a sign bug.
The former claims that Metal R2C was broken and `vmav` could not wrap shared
storage were wrong. Historical numbers remain in the superseded
`docs/bench/gpu-plan-after-inversion.md`, not as acceptance evidence.

## Next

1. Resolve scientific boundary checks with a larger predeclared balanced family
   and a known-small CPU perturbation control; do not relax tolerances.
2. Quarantine/repair the failing retired inversion probe and selectable engines.
3. Remove deconvolution plan churn and copies; retain scale kernels/workspaces
   with an aggregate-byte budget and fuse weighting/peak extraction where valid.
4. Reuse prediction plans safely; broaden observing-mode/portability validation.

## Reproducible state

- Measured executable: `bench/bin/gpu-audit-final/wsclean`.
- Final rebuilt `build-mx-metal/wsclean` reports `mx-base-50-g0dbb1b06`; its
  1024² CLI recheck passes all six products with 89 actual GPU planes.
  Delivery snapshot: `bench/bin/gpu-audit-delivered/wsclean`.
- Evidence: `bench/out/gpu-audit-20261022-0715/`.
- Figures and raw summaries: `docs/bench/gpu-audit-20261022/`.
- WSClean `0dbb1b06`; schaapcommon `8bb0759`; radler `39d58d1`.
- Patch series: WSClean 50, schaapcommon 7, radler 7, aocommon 2; all replayed
  exactly from `mx-base` in isolated indices. No push or main merge.
