# CPU audit and optimization plan — 2026-10-22

## Scope and baseline

Audit and optimize the CPU path on `gpu-dev`, starting at root `757e36a`:
WSClean `ff01a434`, Radler `ea55b61`, Schaapcommon `d6e5eee`, Aocommon
`dd2b059`. This is a follow-on CPU change, not a comparison to the initial
unoptimized upstream or a modification of the CPU release on `main`.

- Apple M2, 8 cores, 16 GiB; Apple clang 21, Release `-O3 -DNDEBUG`.
- Explicit `WSCLEAN_MX_METAL=OFF`; no `-mgpu`, no Metal work.
- Reconfigure and rebuild before freezing `cpu-audit-base-20261022`.
- Initial CPU regression suite passes. Preserve its named results and warnings.
- Real 15-integration MS: `bench/out/gpu-audit-20261022-0715/input-15.ms`.
  All files have non-writable permission bits. Content SHA-256 manifest covers
  all 108 files, including table locks, before execution; compare it again after.
- Fresh evidence directory: `bench/out/cpu-opt-20261022-2035/`.
- No source reset, original-MS prediction, output deletion, or automatic push.

## Read/check coverage

Trace CPU main/driver → MS selection/reorder/read → ducc0 inversion/prediction →
Radler multiscale transforms/peak search → restoration. Read callers and callees,
not just the old patch diffs. Inspect kernel ownership, buffer lifetimes,
thread-pool nesting, weighted/masked peaks, and the separate in-memory loader.
Record dormant APIs separately from standard CLI behavior. This is not a claim
that every line of external casacore/ducc0 or every observing mode is audited.

## Measurements declared before implementation

1. One warmup, then two reverse-ordered thread sweeps (`-j 1,4,8`) at 3072² /
   2.7 arcmin. Deep multiscale settings match the existing campaign: 20,000
   maximum iterations, mgain 0.95, scale bias 0.8, local RMS, auto-mask 3,
   auto-threshold 0.5, Briggs 0, horizon mask 10 degrees, memory fraction 40%.
2. Separate macOS sample profiles at 3072² / 2.7 arcmin and 4096² / 2 arcmin,
   eight threads, with ducc0 phase reporting. Do not use instrumented wall times
   as ordinary timing samples.
3. Capture real/user/sys, instructions, cycles, RSS, stage times, load and swap.
   Keep failures/outliers; no compilation or CPU-heavy tests alongside timings.
4. Choose a bounded change only after observing the measured hot path. A possible
   target from source inspection is the full-image RMS-weighted peak scratch;
   it is a hypothesis, not a speedup claim.

## Acceptance contract

- Resource/work regression fails against the unchanged linked baseline before
  implementation, then passes against the candidate.
- Preserve float32 multiplication, peak value/sign, row-major first ties,
  masks, borders, NaNs/infinities, normal/subnormal threshold and no-peak
  sentinels. Do not accidentally change the x86 AVX public behavior.
- Leave registered GPU-hook behavior unchanged; this is a CPU optimization.
- Differential tests use the real old arithmetic/peak oracle. Do not compare two
  copies of the new algorithm or assert only approximate aggregate image RMS.
- Deterministic one-thread before/after imaging must pass T0 for every FITS
  product. Matched-dirty/PSF threaded deconvolution also targets T0. Full threaded
  imaging keeps T2 results and reference A/A spread visible; no tolerance tuning.
- Sequential counterbalanced timing repeats and an identical-baseline A/A control;
  report whole-run and affected-stage changes separately. If noisy, retain a
  proven resource simplification without claiming a wall-time speedup.
- Run linked regression suites and native upstream tests, retain named skips,
  obtain independent review, rebuild/exercise the normal user executable,
  verify input hashes and exported-patch tree identity.

## Deliverable

A dated audit with source findings, profiling tables/figures, actual before/after
measurements, test receipts, narrow exported source patches, and explicit limits.
Existing GPU scientific failures are not resolved by CPU optimization.
