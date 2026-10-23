# Next development steps for wsclean-mx

> This records the CPU-focused initial plan. The current `gpu-dev` audit,
> implementation and unresolved gates are in
> [the 2026-10-22 GPU plan](gpu-next-optimization-2026-10-22.md), which supersedes
> the older Metal roadmap below. The follow-on bounded-resource implementation,
> native gates and unresolved convolution science checks are in
> [the resource-residency report](gpu-resource-optimization-2026-10-22.md).
> The subsequent [CPU audit and weighted-scan optimization](cpu-audit-2026-10-22.md)
> records fresh CPU profiles, native verification, timing controls and retained
> image-gate failures. The [CPU correctness repair report](cpu-correctness-repairs-2026-10-22.md)
> records the subsequent provider/RMS/Dijkstra and threaded-ordering repairs;
> strict old/new scientific acceptance remains separate from repeatability.
> The [2026-10-23 copy-removal and masked-peak report](cpu-copy-and-masked-peak-2026-10-23.md)
> adds the subsequent full-depth CPU optimization: 19 runs / 114 bitwise product
> comparisons, measured CLEAN improvement, A/A timing caveats and bounded next
> candidates. It does not waive the earlier legacy-reference failures.

**Initial audit:** 2026-10-17 (EDT), starting at `333cea8` on `main`; published as `43c6cae`.
**Continuation:** [CPU correctness repairs and verification](continuation-2026-10-17.md).
**Tracking read during the initial audit:** Linear **PZ-19**, “wsclean-mx: Apple Silicon optimized WSClean build,” including all five comments then present; GitHub issue **#1**, including all nine comments then present. Both were open/in progress. This continuation does not change remote issue state.

## Recommendation

**Make the CPU patch stack demonstrably robust before starting Metal.** The existing stack already reproduces approximately a twofold wall-time improvement on the current snapshot. The immediate bottleneck in development is trustworthy validation across selections, MS layouts, and numerical modes—not the absence of another FFT backend.

This audit covers the first-party build/benchmark scripts, active patch files, modified upstream functions and their callers, local build configuration, documentation, and linked issue history. It is not a claim to have exhaustively verified every line of WSClean, casacore, ducc0, or every observing configuration.

## Architecture and ownership

| Layer | Role | Development rule |
|---|---|---|
| `upstream/wsclean` | Pristine pinned WSClean `2d5c1ed8d7559e5178d243661b408baa288681e6` | Never edit it in place |
| `patches/build` | Shared macOS portability fixes | Apply equally to references and mx |
| `patches/mx/{wsclean,aocommon,schaapcommon,radler}` | Distributable source of truth for optimizations | Export developer commits as patches |
| `work/<repo>` | Patched developer checkouts | Check cleanliness before edits; never force-reinitialize to “fix” a build |
| WSClean providers | MS selection, block I/O, reordering | Preserve selected-row and writeback semantics |
| schaapcommon / ducc0 | FFTs, resampling, convolution, gridding, locking | Validate normalization, buffer ownership, threading and non-finite handling |
| aocommon / radler | Median/MAD, peak search, minor loops, multiscale caches | Preserve ties/masks/RMS weighting; bound actual memory under concurrency |
| `bench/` | Timings and T0/T1/T2 numerical comparisons | Never destroy previous evidence or permit known MS-writing overrides |

The effective scientific baseline is **upstream plus the zero-padding fix**, not pristine upstream: the latter has the documented Apple-clang small-inversion hazard. The LINC container is a cross-ISA scientific comparison, not a bitwise reference.

## Findings and priorities

| Priority | Finding | Evidence / impact | Next action |
|---|---|---|---|
| P0 — fixed in this pass | T2 accepted nonzero candidate data against an all-zero reference | `bench/compare_fits.py` used zero relative error when reference normalization was zero | Regression-tested fail-closed normalization; also corrected float64 ULP overflow, raw big-endian ULP handling, dtype-aware T0 and invalid inputs |
| P0 — fixed in this pass | Benchmark runners deleted an existing output path before validating arguments | Previous `bench/run.sh:27` and `bench/snapshot.sh:15`; traversal and unsafe overrides were possible | Reject invalid names, output symlinks/collisions, unavailable variants and known write/output overrides; never replace existing runs |
| P1 — repaired for tested reader paths | Speculative block reads touched excluded invalid cells; fallback also needed full-shape validation | 27 production-reader cases cover excluded/selected cells, shapes, weights, metadata and boundaries | Keep valid reads batched; fall back per column/block; reject malformed selected shapes before extraction; retain the documented ContiguousMS first-cell limitation |
| P1 — repaired | Seven native allocation failures and the exposed in-memory FITS date bug | Parent native run: 160 passed, 4 skipped, 0 failed; 869917 assertions | Fundamental allocation uses malloc; provider start time converts seconds to MJD days. Keep the four skips explicit rather than claiming all tests ran |
| P1 — retracted by measurement | Earlier dirty-imaging wall-time increases were a host timing mode, not a code cost | Chia batches were bimodal; on throttle the same binary bytes give 2.99/3.00 s at `-j 1` and 1.200/1.205 s at `-j 8`, with retired instructions ≤0.2% apart and an A/A copy control agreeing as well | Keep both earlier batches on record; require per-run instructions/cycles and an A/A copy control before any future regression verdict |
| P1 — resolved across the sweep and three more telescopes | Full-stack multiscale scientific equivalence | 3C196 base config and `-multiscale-scale-bias 0.5` agree at float32 rounding; quiet-Sun 2048² all four mx runs pass both criteria against a 50-rerun family; sweep's `-niter 10000` shift was basin sampling (control hits the same basins); `-weight natural` difference is statistically real but ~25× under the reference's own scatter with identical source metrics. External fixtures (2026-10-18): LOFAR LBA passes at the floor, LOFAR HBA mx ≡ control, MWA PupA is chaotic with mx and control both on the boundary | Optional: attribute the natural-weighting aggregate difference to specific patches; no code change is indicated |
| P1 — partly addressed | Test coverage and build provenance need portable automation | Dedicated native build and real-reader fixtures now pass; test.sh validates source mappings and runs 110 Python tests (harness, comparator, plotter, source gate) plus linked gates | Extend dependency/CI coverage; root CTest enumeration remains insufficient |
| P1 — dormant loader repaired, still disabled | In-memory disk loader had separate antenna/weight/selection contracts | The 2026-10-22 correctness follow-up fixes ANTENNA2, spectral/scalar weights, dimensions and intervals; linked synthetic provider/loader tests pass. Normal CLI routing remains unchanged | Keep disabled until observing-mode/CLI integration is explicitly requested; do not present it as a deployed normal-CLI defect |
| P2 — builder verified | Fixed reference and build provenance are not reproducible from one tracked command | `scripts/build_upstream_fix.sh` builds pinned upstream + build patches + wsclean/0001 only and writes `build-reffix/provenance.json`; a fresh build reproduces the frozen `bench/bin/upstream-fix` snapshot bitwise (0 differing pixels, all five products, `-j 1` multiscale) | Snapshots still do not freeze every dynamic library; record library hashes at snapshot time in a future revision |
| P2 — closed | Older profiling harness still has destructive output setup | `bench/profile.sh` now sources the shared guards (variant/tag/arg validation, `bench_output` refuses an existing directory, sampler availability checked, `SAMPLE_TOOL` override) and five harness tests cover collisions, slugs, forbidden options and the happy path | — |
| P2 — closed | Benchmark figures ignore the mode assessment | `bench/plot_report.py` reads `<tag>-ab.mode.txt`: ratios carry `[stall mode mismatch]`, `[unclassified]` or `[no mode file: wall-clock only]`, and each figure's axis names every comparison that is not mode-verified; eight tests pin the parsing | — |
| P2 — measured | Cache budgets do not bound total RSS | Peak RSS tracks image size, not channel count: 512² multiscale 97 MiB (1 channel) vs 96 MiB (4 output channels), 1024² 435 MiB, 2048² 1393 MiB. WSClean 3.7 has no `-facets` imaging option (facet regions are prediction-only), so the facet dimension could not be exercised | Revisit if a configuration with real facet imaging or much larger channel counts appears |
| P2 — partly closed | Numerical/resource edge cases remain | `tests/median_edge_regression.cpp` pins the inherited even-median overflow, the exact average where it does not overflow, non-finite filtering and subnormal-only median/MAD; a Python test pins subnormal-only handling in the gate. Nested thread-pool contention is still unprofiled | Profile concurrency (two concurrent multi-threaded runs) before changing semantics |
| P3 — open | Plan and issue descriptions lag their comments | `notes.md` still proposed a first FFT patch; PZ-19 description checklist includes work completed in later comments | Treat this document and the latest dated benchmark report as the active plan; update tracking only with verified results |

### New optimization: conditional multiscale scratch

`ThreadedDeconvolutionTools::FindSingleScalePeak` allocated a full image even when no RMS-factor image was supplied. Move that allocation into the RMS-weighted branch. The arithmetic, tie order, masks, and output structures remain unchanged.

The public-API allocation regression failed in all four unweighted cases before the change (two full-image allocations rather than one), then passed all eight weighted/unweighted, masked/unmasked, RMS-enabled/disabled scenarios. This removes one allocation request of `width × height × sizeof(float)` per scale search. **It does not imply the same reduction in resident memory:** the old scratch was uninitialized and untouched in the unweighted branch. End-to-end timings, not allocation size, determine any speedup claim.

## Ordered implementation plan

### 0. Measurement method (closed 2026-10-18)

**Closed 2026-10-18:** the suspected dirty-imaging slowdown was a host timing mode.
[Throttle validation](throttle-validation-2026-10-18.md) used the same binary and
library bytes and added interleaved A/A plus single-thread controls. Retired
instruction counts match to ≤0.2% while the slow mode burns ~1.5× the cycles, and
interleaved sweeps give 0.3–0.5% differences at `-j 1` and `-j 8`.

- Keep the earlier chia and throttle first-pass batches on record; do not delete or silently mediate them.
- Record per-run retired instructions, cycles and host load in every timing run, and classify stall modes before comparing wall times.
- Keep an A/A copy control (byte-identical binary under a second name) in the harness so a host mode cannot masquerade as a patch effect.
- Do not weaken selected-cell shape or selection validation to chase a timing number.

**Exit criterion (met):** an attributable explanation for the earlier spread, plus a
measurement convention that would catch a recurrence. This is not a general
performance guarantee for untested sizes, thread counts or MS layouts.

### 1. Complete scientific and observing-mode acceptance

The selected-row, allocator and provider-time repairs now have passing native
regressions. The continuation records incremental `-j 1` image checks and
performance measurements separately from full-stack scientific equivalence.
[science-gates.md](science-gates.md) defines the source-level gates and reports
the first measurements: dirty/PSF pass, the multiscale cleaned products do not,
and patch 12 is neutral.

- Widen the reference envelope for the measured multiscale failure: many more upstream reruns plus the perturbed `upstream-fix-ulp` reference, so the chaotic spread is measured rather than inferred from three samples.
- Repeat the source gates on a field with real sources (calibrator or bright event) where flux-ratio and position gates are physically meaningful; the current quiet-Sun snapshot's matched-source envelopes are tens of percent.
- Add polarization gates (Stokes V products) once a suitable dataset exists; the current snapshot is Stokes I/V but noise-dominated.
- Keep the now-tested `ReadMsInMemory` antenna/weight/interval contracts when considering any future CLI in-memory experiment; this repair does not enable that mode.
- Extend BDA, calibration, joined-channel and variable-layout coverage beyond the current synthetic fixtures and single real snapshot.
- Keep four native skips explicit: two BDA cases require an unavailable hard-coded external dataset; two average-correction performance tests are disabled upstream.
- Treat exactness of each operation-preserving repair as a narrower claim than acceptance of the earlier FFT-changing stack.

**Exit criterion:** predefined science/mode gates pass, and all exclusions have named causes. A green supported native suite alone is not release-wide scientific validation.

### 2. Make builds and benchmark evidence reproducible

- Add a builder for pinned upstream + shared portability patches + only `wsclean/0001`.
- Verify regenerated patch trees match `work/` before benchmarking, without modifying pristine upstream or deleting work.
- Record binary and patch hashes, compile flags, compiler/SDK/dependency identities, commands, MS content identity, thread count, image geometry, cache state, wall/stage times, RSS, load and swap.
- Keep counterbalanced AB/BA ordering, cooldowns, multiple repeats, and both median/minimum. Preserve raw results and failed runs.
- Report cleaned-image differences alongside upstream rerun/perturbed-upstream distributions. Equal residual RMS alone is not an image-equivalence proof. Do not raise thresholds after seeing a failure.

**Exit criterion:** a second clean checkout reproduces the source configuration and numerical gates; performance reports can be traced to exact executables and inputs.

### 3. Measure workloads that justify the next optimization

- Acquire a real multi-integration MS and document origin, integrations, row/channel counts, storage manager and read-only policy. Do not label a duplicated snapshot as independent science data.
- Matrix: dirty and multiscale, 2k/4k initially, `-j 1/4/8`, direct/reordered paths, small inversion on/off, multiple channels/polarizations.
- Attempt 8k only after measuring available memory and actual cache/RSS growth; a 16 GiB unified-memory laptop already using swap is not an unrestricted 8k test host.
- Test `-in-memory` as a configuration experiment, not an assumed improvement. Compare input-stage overhead and RSS as well as wall time.
- Reprofile gridding, FFT, locks, weight calculation, reorder I/O and FITS writing. Retest parked vForce only on a workload where its target is significant. Do not revive vDSP FFT merely because it is Apple-native.

**Exit criterion:** a measured dominant stage on representative data, with a reproducible numerical and memory budget.

### 4. Metal prototype only after those gates

- Start with a standalone CPU-vs-Metal grid/degrid harness feeding identical buffers; keep a runtime CPU fallback.

Status 2026-10-18: the standalone harness exists (`metal/`, `mx-metal-probe`,
`scripts/metal_build.sh`) and the CPU fallback is automatic (the backend is only
compiled under `WSCLEAN_MX_METAL=ON`; every other build is unchanged, verified by
the regression suite). The harness reproduced the plan's motivating case on its
first run: float32 arithmetic moved ~1 in 10^4 visibilities one cell away from
the double-precision placement, which the centred-coordinate rounding now
prevents on both sides. Next: kernel table, then wiring the w-gridder behind
`-mgpu` and re-running the science gates. Details and measurements in
`docs/metal-plan.md`.
- Preserve high-precision coordinate/phase preprocessing rather than naively converting all math to GPU float.
- Test point-source flux/position, wide-field and high-|w| cases, masked/nonfinite data, adjoint consistency and repeatability.
- Evaluate tiled accumulation versus atomics on the actual visibility distribution. Measure end-to-end transfer/preprocessing/FFT costs, not only kernel time.
- Integrate with WSClean only if correctness, RSS and wall-time gates beat the validated CPU path.

## Artifacts and commands

- Results and limits: `docs/audit-2026-10-17.md` and `docs/continuation-2026-10-17.md`.
- Raw evidence (local, gitignored): `bench/out/audit-20261017/`, `bench/out/continue-20261017/` and their immutable run directories.
- New automated gate: `scripts/test.sh build-test` (or another configured mx build).
- Upstream suite, separate from the new gate: run `./unittest --report_level=detailed --log_level=message` from `build-test/` after fetching its fixture targets. Root CTest enumeration is not a substitute for this executable, and dependency suites require their own configuration.

No claim is made here that all observing modes, Linux portability, Metal, or larger measurement sets have been validated.
