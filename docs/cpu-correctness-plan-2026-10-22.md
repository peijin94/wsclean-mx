# CPU correctness repair plan — 2026-10-22

Outcome: source repairs and verification are recorded in
[the repair report](cpu-correctness-repairs-2026-10-22.md). Fixed-eight-thread
repeatability passes; strict legacy-image comparisons retain documented failures.

Baseline: root `f673e14`, Radler `1f1452e`, WSClean `ff01a434`, Schaapcommon `d6e5eee`, Aocommon `dd2b059`. User requested all remaining correctness issues, starting with Dijkstra. No release, push, merge to main, or scientific-tolerance relaxation is authorized by this work.

## Work and acceptance

| Area | Root-cause investigation / acceptance |
|---|---|
| Dijkstra | Preserve minimum-cost path semantics without imposing a new equal-cost tie order. Decouple exact mask fixture from unspecified priority-queue ties; preserve its exact mask assertions. Reproduce origin-padding underflow and empty-strip failures with sanitizers; verify all pixels in the existing randomized partition test. |
| Reordered reader | Independent DATA, WEIGHT and MODEL streams must follow logical row selection despite skips/repeats/interleaving; sequential reads should not acquire unnecessary seeks. Test actual provider on distinct synthetic rows and multiple channel/polarization sizes. |
| UV footprint | Vertical coordinate must use v; test rectangular images, unequal scales, finite bounds and Nyquist edges with independent expectations. |
| RMS window | Preserve ordinary clipped half-open windows. Define zero-radius identity, safe oversized bounds, aliasing, empty images and NaN policy. Validate actual code against an independent brute-force oracle under ASan/UBSan. |
| Dormant disk loader | Correct ANTENNA2, optional spectral/scalar weights, interval/empty selections and selected-cell dimensions. Test public ReadMsInMemory on synthetic MSs; do not enable the dormant CLI path. |
| Threaded inversion | Localize unordered bucket insertion and tile partial merges. Require a failing repeated-call test before fixing, bounded scratch, actual multi-thread participation, numerical accuracy and bitwise repetition. Test prediction separately. No one-thread default, larger precision as a determinism substitute, or threshold relaxation. |

## Scientific and delivery checks

- Keep historical failed gate files unchanged. New deterministic arithmetic cannot promise to reproduce every historical unordered CLEAN trajectory; report old/new equivalence separately from new/new repeatability.
- Repeat real 3K and 4K deep imaging with eight threads and compare every expected FITS product. Preserve T0 and T2 (relative RMS 1e-4, relative peak 1e-3).
- Keep the real MS read-only and verify the prior content/mode manifest before and after runs. Use fresh run directories.
- Do not benchmark while builds or heavy tests run. Record wall/stage times, RSS and host conditions; quantify any determinism cost rather than hiding it.
- Run complete linked and native suites after all source edits; separate disabled/missing-fixture cases from failures.
- Independent review of all changed/new files and caller paths; fix blocking findings, retest, commit component changes and export additive patches, verify all component trees by isolated-index replay.
- Update the audit and README with verified results and remaining limitations. P2 performance opportunities are not silently reclassified as correctness bugs or claimed fixed.

Raw RED/GREEN logs, worker receipts and run plans: `bench/out/cpu-fixes-20261022-2223/`.
