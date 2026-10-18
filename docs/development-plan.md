# Next development steps for wsclean-mx

**Reviewed:** 2026-10-17 (EDT), starting at `333cea8` on `main`.
**Tracking read:** Linear **PZ-19**, “wsclean-mx: Apple Silicon optimized WSClean build,” including all five comments; GitHub issue **#1**, including all nine comments. Both remain open/in progress. No remote issue status was changed.

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
| P1 — open | Block reads touch physical rows excluded by a selection | `work/wsclean/msproviders/msreaders/contiguousmsreader.cpp:192–226`, `rowproviders/msrowprovider.cpp:127`, `columnblock.h:28` | Add selected/excluded undefined-`CORRECTED_DATA` fixtures; fall back to selected-row reads without hiding failures in selected cells |
| P1 — open | Full upstream unit suite is not green | After downloading fixtures: 126 passed, 7 `std::bad_alloc` failures, 4 skipped; same seven failures appeared before the scratch change | Isolate the failures with small reproducers before calling this a release-quality build |
| P1 — open | Full-stack multiscale scientific equivalence is not established by residual RMS alone | Fresh mx-p11 vs upstream restored-image relative RMS is 1.36–1.47%, above this session's upstream-rerun maximum of 0.858%; default T2 also fails for upstream reruns | Define source/flux/position and perturbed-reference gates on broader data; do not silently loosen pixel thresholds |
| P1 — partly addressed | Tests were disabled and several microbenchmarks copied implementations rather than linking production code | Existing `BUILD_TESTING=OFF`; `ctest -N` enumerated zero tests | New `scripts/test.sh` links production numerical routines and exercises actual block-cache code; add dependency suites and reader-level fixtures next |
| P2 — open | Fixed reference and build provenance are not reproducible from one tracked command | No `build_upstream_fix.sh`; snapshots do not freeze all dynamic dependencies; work trees are reused without patch validation | Add the fixed-reference builder and a manifest of source/patch/binary/compiler/library hashes |
| P2 — open | Cache budgets do not bound total RSS | Shared kernel cache plus per-clone residual/PSF caches, temporary buffers and concurrent cache misses | Measure aggregate peak memory for multiple facets/channels/scales; consider budget coordination and eviction |
| P2 — open | Numerical/resource edge cases remain | Even-median finite overflow is inherited; subnormal-only peaks retain upstream semantics; nested independent thread pools can contend | Add explicit edge tests and profile concurrency before changing semantics |
| P3 — open | Plan and issue descriptions lag their comments | `notes.md` still proposed a first FFT patch; PZ-19 description checklist includes work completed in later comments | Treat this document and the latest dated benchmark report as the active plan; update tracking only with verified results |

### New optimization: conditional multiscale scratch

`ThreadedDeconvolutionTools::FindSingleScalePeak` allocated a full image even when no RMS-factor image was supplied. Move that allocation into the RMS-weighted branch. The arithmetic, tie order, masks, and output structures remain unchanged.

The public-API allocation regression failed in all four unweighted cases before the change (two full-image allocations rather than one), then passed all eight weighted/unweighted, masked/unmasked, RMS-enabled/disabled scenarios. This removes one allocation request of `width × height × sizeof(float)` per scale search. **It does not imply the same reduction in resident memory:** the old scratch was uninitialized and untouched in the unweighted branch. End-to-end timings, not allocation size, determine any speedup claim.

## Ordered implementation plan

### 1. Fix selected-row correctness and complete the CPU gate

- Make tiny real casacore fixtures covering homogeneous shapes, differing SPW/channel counts, differing polarization counts, `WEIGHT` versus `WEIGHT_SPECTRUM`, row-block boundaries, selected ranges, and undefined excluded cells.
- Exercise both `ContiguousMSReader` and `DirectMSRowProvider`, not just `ColumnBlock`.
- Preserve row-by-row behavior when a bulk request contains excluded invalid cells. Selected invalid cells must still fail loudly; do not silently substitute zeros.
- Add `-j 1` full-product comparisons for dirty, Högbom, multiscale, Stokes I/V, and joined-channel cases.
- Separate new-patch bitwise equivalence from full-stack scientific validation. The scratch patch preserves all five products exactly at `-j 1`; that does not prove equivalence of the earlier FFT-changing stack to upstream.
- Isolate the seven upstream failures: four `visibility_modifier` H5 cases, two `interface` cases, and `in_memory_provider/read_write`. Do not assume missing data or insufficient RAM once fixtures are present.

**Exit criterion:** these reader fixtures and the supported unit suites pass; remaining exclusions have named causes, not a blanket “tests green.”

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
- Preserve high-precision coordinate/phase preprocessing rather than naively converting all math to GPU float.
- Test point-source flux/position, wide-field and high-|w| cases, masked/nonfinite data, adjoint consistency and repeatability.
- Evaluate tiled accumulation versus atomics on the actual visibility distribution. Measure end-to-end transfer/preprocessing/FFT costs, not only kernel time.
- Integrate with WSClean only if correctness, RSS and wall-time gates beat the validated CPU path.

## Artifacts and commands

- Results and limits: `docs/audit-2026-10-17.md`.
- Raw evidence (local, gitignored): `bench/out/audit-20261017/` and the `audit-20261017-*` run directories.
- New automated gate: `scripts/test.sh build-test` (or another configured mx build).
- Upstream suite, separate from the new gate: run `./unittest --report_level=detailed --log_level=message` from `build-test/` after fetching its fixture targets. Root CTest enumeration is not a substitute for this executable, and dependency suites require their own configuration.

No claim is made here that all observing modes, Linux portability, Metal, or larger measurement sets have been validated.
