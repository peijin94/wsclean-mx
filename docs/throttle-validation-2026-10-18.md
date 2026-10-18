# Throttle validation — 2026-10-18

## Purpose and controlled comparison

Repeat the CPU correctness checks and baseline/candidate timings on throttle after the busy chia measurements. This is a **within-host comparison**, not a direct M2-versus-M4 speedup claim.

Throttle was updated to macOS 27.0.1 before execution. Live discovery found an Apple M4, 10 CPU cores, 16 GiB RAM, AC power and zero swap. Its earlier macOS 26.5.2 could not meet the executables' declared macOS 27 minimum; no deployment-target metadata was patched to bypass that requirement.

## Provenance and isolation

- Root source checkout: `20e94792bb66ca8dc08d3b32438d186eb7ae7978`.
- Baseline: exact `continue-p12-baseline` executable from the earlier audit, exposed remotely as `throttle-baseline`.
- Candidate: exact `continue-cpu-fixes` executable, exposed remotely as `throttle-candidate`.
- Native tests and standalone gates are the same precompiled arm64 programs exercised on chia. They were not rebuilt for M4, avoiding compiler/flag differences between these experiments.
- Each executable has an environment-only launcher. Non-system Mach-O dependencies are copied into the project; original executable and library bytes are unchanged and checksum-verified. The loaded-library trace confirms non-system dependencies resolve inside the project. OS frameworks come from throttle's macOS installation.
- No system Homebrew build packages were installed. Python comparator dependencies are isolated in the project's `.venv`.
- Test data and the casacore measures data were copied from chia. The real OVRO-LWA MS remains read-only and is checked against the same 65-file hash manifest.
- The initial native-test attempt had three missing source-tree facet fixtures. Transferring the pinned WSClean source tree fixed setup; the original failure log is retained. No test was disabled to hide those failures.
- All remote artifacts live under `/Users/peijinz/dev/wsclean-mx`; no credentials, unrelated workspaces or old benchmark output trees were copied.

## Protocol

1. Verify executable/runtime checksums and actual loaded-library paths.
2. Run the native unit suite, 56 Python tests, and eight standalone compiled gates.
3. Compare all image arrays at T0 for the same five `-j 1`, 1024² configurations used on chia: dirty I, Högbom I, multiscale I, dirty I/V and joined-channel multiscale.
4. Cool down for 45 seconds. Start timing only when one-minute load is below 3 and swap used is below 1024 MiB; save the observed state.
5. Run sequential, counterbalanced AB/BA at `-j 8`, with 15-second cooldowns: **eight repeats per variant** for 4096² dirty, **four per variant** for 2048² multiscale/niter 3000. No compilation or heavy tests overlap timing.
6. Preserve every timing sample, per-run stage/RSS records, host state and post-run input hashes. Do not replace the earlier chia measurements with the more favorable host's results.
7. Because the first timing results were bimodal, add interleaved follow-up sweeps that repeat **both** variants **and a byte-identical copy of the baseline**, recording retired instructions, cycles and host load per run.

## Results

### Correctness and input protection

| Gate | Result |
|---|---|
| Native WSClean suite | **160 passed, 4 skipped, 0 failed** after source-fixture setup |
| Python harness/comparator tests | **56 passed** |
| Standalone compiled gates | **8 passed** |
| Five 1024² imaging configurations | **31 product arrays bitwise equal** at `-j 1` |
| Additional 4096² dirty comparison | Both `img-dirty.fits` and `img-image.fits` arrays bitwise equal at `-j 1` |
| Runtime transfer | All 60 packaged files checksum-verified; actual library locations checked |
| Protected measurement set | All **65 files unchanged and read-only**, including after the diagnostic runs |

The four native skips are the same two unavailable external-BDA cases and two
upstream-disabled microbenchmarks recorded on chia. Passing these tests does not
close the separate full-stack scientific-acceptance question.

### First-pass timing results (superseded, kept for the record)

Sequential counterbalanced AB/BA at `-j 8` with 15-second cooldowns, wall-clock medians:

| Workload | Repeats per variant | Baseline | Candidate | Candidate change |
|---|---:|---:|---:|---:|
| 4096² dirty, `-j 8` | 8 | 1.160 s | 1.350 s | +16.4% |
| 2048² multiscale, `-j 8`, niter 3000 | 4 | 7.320 s | 7.350 s | +0.4% |

Raw samples, seconds, in repetition order:

| Workload | Baseline | Candidate |
|---|---|---|
| Dirty `-j 8` | 1.37, 1.16, 1.17, 1.16, 1.35, 1.15, 1.16, 1.16 | 1.37, 1.36, 1.16, 1.35, 1.15, 1.35, 1.16, 1.35 |
| Multiscale `-j 8` | 6.64, 7.00, 7.64, 7.67 | 6.73, 6.99, 7.75, 7.71 |

The timed phase began at one-minute load 2.945 with zero swap. Swap stayed zero;
load at the end was 7.241, which includes the benchmark's own work. This was
**not an otherwise-idle-host guarantee**.

Two further counterbalanced controls used the same 4096² dirty configuration:

| Control | First median | Second median | Difference |
|---|---:|---:|---:|
| Identical baseline executable versus byte-identical copy, `-j 8` | 1.160 s | 1.165 s | +0.4% |
| Baseline versus candidate, `-j 1` | 2.920 s | 4.410 s | +51.0% |

The `-j 1` pair looked like a large stable regression: baseline
**2.92, 2.92, 2.92, 2.92 s**, candidate **4.41, 4.41, 4.41, 4.42 s**. The first
version of this report treated that as a reproducible candidate regression.

### Host timing modes — why those numbers were misleading

Per-run counters from `/usr/bin/time -lp` show the two groups did essentially
identical work:

| Session | Executable | Wall | User CPU | Instructions | Cycles |
|---|---|---:|---:|---:|---:|
| `-j 1` dirty 4096² | baseline | 2.92 s | 2.72–2.73 s | 51.22–51.25 G | 12.22–12.30 G |
| `-j 1` dirty 4096² | candidate | 4.41 s | 4.21–4.23 s | 51.29–51.31 G | **19.15–19.19 G** |

The candidate executed about **0.1% more instructions** but burned **56% more
cycles** — a stall/scheduling signature, not a code-path cost.

The same two levels appear within a single session and across executables. In the
`-j 8` primary session the fast level is ~15.3 G cycles / ~4.3 s user CPU and the
stalled level ~20.9 G cycles / ~5.8 s user CPU, with the same retired instruction
count (~51.5 G) in both levels: the baseline sat in the stalled level 2 of 8 runs,
the candidate 5 of 8, while **within** each level the two executables agreed to
~0.01 s (fast: 1.15–1.17 s both; stalled: 1.35–1.37 s both).

The chia batches recorded earlier show the same effect from the other side: all
16 runs — both variants — sat in the high-cycle level (~18.2–20.1 G cycles,
52.3–52.8 G instructions), and wall times (2.48–4.17 s) scattered with host
contention rather than tracking the variant. Chia's pooled medians
(2.875 → 3.410 s) are therefore not evidence of a per-run code cost either.

The trigger for the stalled level is **not identified**; plausible causes are host
scheduling/QoS placement (efficiency versus performance cores) or contention from
other processes. It is not a property of either binary: a byte-identical copy of
the baseline showed the same level behaviour.

### Interleaved sweeps at both thread counts

Two sweeps repeated both variants **and a byte-identical copy of the baseline**,
interleaved AB/BA, so a host level affects all three equally. Every run below
landed in the fast level (0 of 6 stalled per executable at each thread count).

`-j 1`, 4096² dirty, 6 repeats per executable:

| Executable | Wall median | Cycles median | Instructions median |
|---|---:|---:|---:|
| `throttle-baseline` | 2.99 s | 12.30 G | 51.25 G |
| byte-identical copy | 2.98 s | 12.30 G | 51.24 G |
| `throttle-candidate` | **3.00 s** | **12.32 G** | 51.35 G |

`-j 8`, 4096² dirty, 6 repeats per executable:

| Executable | Wall median | Cycles median | Instructions median |
|---|---:|---:|---:|
| `throttle-baseline` | 1.200 s | 15.32 G | 51.59 G |
| byte-identical copy | 1.200 s | 15.32 G | 51.58 G |
| `throttle-candidate` | **1.205 s** | **15.35 G** | 51.64 G |

A `-j 1` size sweep (medians of 3 per variant) shows the same indifference to
image size, so the earlier gap was not a hidden reader cost:

| Size | 128² | 512² | 1024² | 2048² | 4096² |
|---|---:|---:|---:|---:|---:|
| Baseline | 1.130 s | 1.570 s | 2.140 s | 2.720 s | 3.010 s |
| Candidate | 1.120 s | 1.590 s | 2.130 s | 2.720 s | 2.990 s |
| Ratio | 0.99× | 1.01× | 1.00× | 1.00× | 0.99× |

### Corrected conclusion

**The earlier dirty-imaging regression claim is retracted.** With interleaved
measurement that controls the host timing level, the candidate is within
**0.3–0.5%** of the baseline — and equally close to a byte-identical baseline
copy — on 4096² dirty at both `-j 1` and `-j 8`, and within 0.4% on 2048²
multiscale. Retired instructions differ by ≤0.2%. The large earlier figures came
from a shared host-level stalled mode that hit both binaries.

This is limited to the measured workloads: one OVRO-LWA snapshot, 1024²–4096²
dirty images and one multiscale configuration, `-j 1`/`-j 8`, macOS 27 on M4. It
is not a whole-stack scientific-acceptance result and not a general performance
guarantee for other sizes, thread counts or MS layouts. The sweeps ran at load
1.6–3.1, not on a dedicated idle machine.

Two process lessons worth keeping:

1. A wall-clock difference is not attributable until retired instructions and
   cycles are compared. Equal instructions with ~1.5× cycles is a host artefact.
2. An A/A control built from a byte-identical copy of one variant is a cheap,
   decisive guard against host timing modes, and should accompany any regression
   verdict.

### Evidence and publication state

Remote evidence on throttle: `bench/out/throttle-20261018/` (drivers and logs),
`bench/out/diag-j1-20261018/`, `bench/out/diag-modes-20261018/` and
`bench/out/diag-j8-20261018/` (per-run `time.txt`, `record.json`, `summary.json`),
plus the primary immutable run directories and `*-ab.tsv` files.
Analysis on chia: `bench/out/throttle-20261018/remote/`, `compare_sessions.py`,
`analyze_chia_modes.py`, `summary.json`, `controls-summary.json`.

This revision supersedes the regression conclusion of the earlier local draft of
this document. No code change was involved, and no external issue state was altered.

## Interpretation boundary

These results compare the two mx executables on one M4 host; they are not a direct
M2-versus-M4 speed comparison and not a claim about other workloads. The stalled
host mode remains unexplained and can still inflate wall-clock measurements, so
timing records should keep per-run instructions/cycles until its trigger is
understood. Whole-stack scientific equivalence to upstream remains a separate open
question in the development plan.
