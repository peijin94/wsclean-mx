# CPU correctness continuation — 2026-10-17

## Scope and publication

The initial audit, harness/comparator gates and conditional multiscale scratch change were committed and pushed as **`43c6cae`**. This continuation addresses the next CPU correctness gates before more optimization. It changes neither the pristine upstream checkout nor the mathematical FFT/deconvolution algorithms.

This is a follow-up to [the initial audit](audit-2026-10-17.md), not a replacement for its historical results. The broader multiscale science-acceptance gap remains open.

## Changes and evidence

### Selection-safe array-column batching

Speculative `getColumnCells()` ranges can contain undefined or incompatible cells in rows that the requested selection excludes. The production readers now retain their normal bulk-read path, but a casacore bulk-read error switches that column to requested-row reads until the block is reset. Failures in requested cells propagate; nothing is zero-filled or silently skipped. `std::bad_alloc` is not caught as a selection fallback.

Both `ContiguousMSReader` and `DirectMSRowProvider` have real, synthetic casacore-MS fixtures covering data, flags, scalar and spectral weights, selection masks, DDIDs, different channel/polarization layouts, cache boundaries and deferred UVW failures. UVW must contain three values. The reordering provider chooses its initial block size from the first selected row rather than an undefined excluded first data cell; an empty selection does not inspect data shapes.

Independent review caught a further hazard: a row-wise fallback could return a short flag/weight array, or accept transposed dimensions with an equal element count. Those cases must be rejected before downstream extraction. Full-shape validation and its added regressions are part of the final delivery gate, not waived because the earlier selection tests passed.

**Inherited boundary:** `ContiguousMS` still derives its initial data shape from the first physical data cell. This continuation does not claim arbitrary undefined first-cell support for that constructor, nor unrestricted variable-shape support in every provider.

### Allocation portability, not physical out-of-memory

The seven original native failures were traced to `MultiArray` passing fundamental alignments such as 4 to this macOS `aligned_alloc`, which returned null with `EINVAL`. An independent parent regression reproduced failures for bool, char, float and the visibility/model/weight layout, while double and `alignas(64)` controls succeeded.

Use `malloc` for alignments it guarantees (up to `alignof(std::max_align_t)`); retain `aligned_alloc` for over-aligned types. The logical packed layout, byte length, construction, copy/move, resize and deallocation behavior are unchanged. The new gate passes 59 assertions across six layouts. The existing aocommon MultiArray suite passes all 9 cases / 116 assertions.

### In-memory time contract

After allocation was fixed, the actual native suite exposed malformed FITS dates. `InMemoryMs::start_time` and per-row metadata use MS/MJD **seconds**, while `MSProvider::StartTime()` supplies MJD **days** to imaging metadata. The in-memory provider now converts at that boundary only.

A linked regression failed before the fix and checks a fractional-day start time through the base-provider interface while verifying that row times remain seconds. The native interface test checks the expected FITS observation date, rather than accepting any parseable date. The provider unit test now asserts its documented days contract.

### Build/test provenance

`scripts/test.sh` rejects missing or mismatched CMake source mappings before combining `work/` headers with the selected build's libraries. It now includes the real-header allocation and linked-provider time gates. The guard was observed failing before implementation and passing afterward. Python harness/comparator/provenance coverage totals 56 tests.

## Final verification

### Tests and data integrity

| Gate | Final result |
|---|---|
| Native WSClean suite | **160 passed, 4 skipped, 0 failed; 869917 assertions** |
| Production-reader fixtures | **27 passed**, included in the native count above |
| Python harness/FITS/source-mapping tests | **56 passed** in each tested build |
| Standalone allocation gate | 59 assertions, six layouts, no failures |
| Existing aocommon MultiArray suite | 9 cases, 116 assertions, all passed |
| Other linked numerical/block/peak gates | Passed in `build-test` and `build-mx` |
| Independent review | Second review passed after the malformed-shape findings were fixed |
| Patch replay | All 16 exported patches reproduce the four clean developer HEAD trees |
| Protected real MS | All 65 files unchanged and read-only, checked again after profiling |

Every one of the original seven failing native cases is now in the passed-case
inventory. The four skips are **not passes**: `baseline_dependent_averaging/no_averaging`
and `non_zero_time` require an unavailable hard-coded external MS;
`average_correction/kronecker_square_benchmark_old` and `_new` are explicitly
disabled upstream. Linux, all dependency suites and every observing mode have
not been validated here.

### Incremental image equivalence

Both variants used the same read-only OVRO-LWA snapshot, `-j 1 -size 1024 1024
-scale 0.125 -weight briggs 0`, and the runner's model-update suppression.
All five configurations passed T0 for the **complete image-array inventories**:

| Configuration | Extra options | Products checked |
|---|---|---:|
| Dirty I | `-niter 0` | 2 |
| Högbom I | `-mgain 0.8 -niter 300` | 5 |
| Multiscale I | `-mgain 0.8 -multiscale -niter 300` | 5 |
| Dirty I/V | `-pol I,V -niter 0` | 4 |
| Joined-channel multiscale | `-channels-out 2 -join-channels -mgain 0.8 -multiscale -niter 300` | 15 |

That is **31 bitwise-equal product arrays**, not a claim that FITS headers or the
full optimized stack match upstream bitwise. The actual `build-mx/wsclean`
executable was also run directly through the `mx` variant: all five products
of its multiscale smoke match the frozen candidate at T0.

### Performance: an observed dirty-imaging slowdown remains open

Frozen variants: `continue-p12-baseline` versus `continue-cpu-fixes`. Runs were
sequential, counterbalanced AB/BA, four repeats per variant per batch, 15-second
cooldowns, `-j 8`, warm OS caches. No compilation or heavy tests overlapped.
Dirty used 4096² at 0.03125°, niter 0. Multiscale used 2048² at 0.0625°,
mgain 0.8, niter 3000; both used Briggs 0.

| Workload | Baseline median (s) | Candidate median (s) | Wall-time change |
|---|---:|---:|---:|
| 4096² dirty, initial (4/variant) | 2.740 | 3.085 | +12.6% |
| 4096² dirty, confirmation (4/variant) | 3.055 | 3.495 | +14.4% |
| 4096² dirty, pooled (8/variant) | 2.875 | 3.410 | +18.6% |
| 2048² multiscale (4/variant) | 15.125 | 14.480 | -4.3% |

Raw wall-time samples, seconds, in repetition order:

| Batch | Baseline | Candidate |
|---|---|---|
| Dirty, initial | 2.59, 3.10, 2.48, 2.89 | 2.73, 3.44, 2.49, 3.48 |
| Dirty, confirmation | 2.86, 2.65, 3.25, 4.17 | 3.38, 3.61, 3.13, 3.69 |
| Multiscale | 12.80, 14.76, 16.61, 15.49 | 14.37, 14.67, 14.55, 14.41 |

The initial dirty result crossed the predeclared 10% investigation threshold.
The confirmation also measured a slower candidate; both batches are retained.
Pooled dirty ranges are 2.48–4.17 s baseline and 2.49–3.69 s candidate. Multiscale
ranges are 12.80–16.61 s and 14.37–14.67 s. Pooling is descriptive, not a confidence
interval or a substitute for a quiet-host experiment.

The host was busy and swapping: the primary run recorded load averages around 6
and `vm.swapusage` used 11711–12465M. Initial dirty median retired instructions
rose only about 0.16%, while median user CPU time was 5.94 s baseline versus
5.77 s candidate. Diagnostic sample profiles did not identify a dominant new
shape-validation hotspot; IPosition inclusive samples were 33 and 28, and
reader-inclusive samples 524/2347 and 366/2031 main-thread samples. Main-thread
renames were combined by numeric thread ID. These are coarse, instrumented
profiles—not proof that the slowdown is harmless or environmental.

**Do not claim a new speedup or a cleared performance non-regression gate.**
Correctness fixes are retained, but the measured dirty slowdown needs isolation
on a quieter, low-swap host and a process-resident production-reader benchmark.
The observed multiscale median improvement is not attributed to these fixes.
First-batch peak RSS was 563.5/562.4 MiB baseline/candidate for dirty and
1533.8/1412.5 MiB for multiscale; these observations are not a demonstrated memory
saving under differing paging conditions.

### Source and executable provenance

| Component | Local developer HEAD used for build | Exported patches |
|---|---|---:|
| wsclean | `fc9a4205231d62de21ffc20550a60010ac14ed73` | 5 |
| aocommon | `dd2b059a885433c33f2e00f7ab3d01f8331f4697` | 2 |
| schaapcommon | `5a7bda9b894afcacc90de182cc79d061eaee3f4a` | 4 |
| radler | `c468d5cd6d14db04753b2d4dab95814e881adbd2` | 5 |

The rebuilt default executable reports `mx-base-5-gfc9a4205` (WSClean 3.7).
Its SHA-256 is `0528ff3c60e9b5a8716838b63fdbe122e37446b4592b83af7c58b27d53e7a18b`.
All source changes are distributed by the additive patch files in this report's
root-repository commit; the local developer HEADs are provenance, not public
upstream commits. Patch-tree equality was checked in isolated indexes; pristine
upstream stayed at `2d5c1ed8d7559e5178d243661b408baa288681e6` and remained clean.
Snapshots copy schaapthreading, but other installed dynamic libraries remain
unfrozen. This is not yet a clean-machine reproducibility guarantee.

Core repeat commands (after configuring the matching work-tree sources and
obtaining the supported native fixtures):

```bash
scripts/test.sh build-test
(cd build-test && ./unittest --report_level=detailed --log_level=message)
scripts/test.sh build-mx
# The 27 reader cases alone:
(cd build-test && ./unittest --run_test=column_block_selection --report_level=detailed)
```

Exact imaging commands, all run exit codes, binary/library metadata, patch
hashes and preserved red/green evidence are under `bench/out/continue-20261017/`.
The publication commit contains the report, tests, driver and exported patches;
no external issue state was changed in this continuation.

## Remaining work

1. Isolate the observed dirty-imaging slowdown on a quieter, low-swap host and with a process-resident production-reader benchmark. Preserve shape/selection validation; do not remove correctness checks to recover a noisy timing number.
2. Establish source-flux/position and scientifically meaningful acceptance gates for the full optimized FFT/deconvolution stack versus the fixed upstream reference. Earlier percent-level multiscale differences remain an open result.
3. Make the fix-only reference builder and complete source/patch/binary/library manifest reproducible from a clean checkout.
4. Validate larger multi-integration datasets and profile a justified target before Metal or additional kernel changes.
5. Investigate `ReadMsInMemory` before recommending the CLI in-memory mode broadly: source inspection finds the `antenna2_column` opened with `ANTENNA1`, and an unconditional `WEIGHT_SPECTRUM` requirement. These are separate, unmodified loader concerns, not claimed fixed by the time-boundary repair.
6. Bring the older `bench/profile.sh` under the immutable-output/argument-validation contract. It still deletes its output directory; this continuation deliberately used a separate bounded profiler with fresh, owned directories instead.

## Local evidence

`bench/out/continue-20261017/` contains red/green logs, the allocator investigation, independent review artifacts, the immutable verification protocol, native-unit logs, the input hash manifest, and real-run results. It is gitignored; this report preserves the conclusions and commands needed to reproduce them.
