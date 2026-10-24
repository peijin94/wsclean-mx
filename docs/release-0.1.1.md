# wsclean-mx 0.1.1 release validation

**Status: release candidate; package build and publication pending.** This is a
CPU-only packaging release from `release/0.1.1`. It is not a promotion of the
experimental Metal backend or a waiver of earlier scientific gate failures.

## User-visible contract

- Primary executable: `wsclean-mx`; no installed `wsclean` compatibility alias.
- MX release identity: `wsclean-mx version 0.1.1`.
- Upstream identity and FITS upstream-version metadata remain WSClean 3.7.
- Internal CMake target: `wsclean`. Optional MPI executable: `wsclean-mp`, not
  included in the Homebrew bottle and not runtime-tested in this release pass.
- CMake's `wsclean-mx` install component includes its threading runtime and uses
  a relative runtime search path. Tests read dyld's actual loaded-library path
  before and after relocating the installed component.
- Active MX runners reject a stale `build-mx/wsclean`; unmodified upstream and
  explicitly named historical snapshots keep their original filenames.

## Source and review

| Item | Evidence |
|---|---|
| Source base | Root `b81ae3d`; current verified CPU stack |
| Identity/install source commit | WSClean `e4bc27619f5e27ae74169f1454c497b7184c00b1` |
| Distributed identity patch | `patches/mx/wsclean/0056-Name-the-MX-executable-and-install-its-threading-run.patch` |
| Patch replay | All 78 patches reproduce the four expected component trees |
| Independent review | Initial rejection retained; corrected review passed with no security or logic findings |
| Python/linked regression driver | 258 Python tests plus production numerical/provider/resource gates passed |
| Native WSClean | 160 passed, 4 existing skips, 869,917 assertions passed |
| Native Radler | Four executable suites and four build entries passed |

The initial review found an incomplete installed threading component and an
argparse collision for leading-dash snapshot names. Both received independent
RED/GREEN fixes. The parent also corrected the generated Python integration-test
executable path. The Homebrew name test and temporary-build-rpath test both
failed against the installed 0.1.0 package, as expected; their final package
checks remain required before publication.

## Numerical acceptance

Frozen pre-rename CPU reference: `bench/bin/v011-baseline/wsclean`, SHA-256
`9c92740f73bc85ef9c72da1d7339795fd07d7382696a01608660e6e920270aaa`.

Each release-binary phase uses the protected 15-slot MS, **explicit
`-data-column CORRECTED_DATA`**, eight threads, a 150,000 iteration cap,
multiscale bias 0.8, gain 0.95, auto-threshold 0.5, auto-mask 3, local RMS,
Briggs 0 and a 10-degree horizon mask. Cases are 3072² at 2.7 arcmin/pixel and
4096² at 2 arcmin/pixel. Inputs are hashed before/after each phase. Every phase
must produce exactly the six expected FITS products and pass their data-array
T0 checks against the frozen baseline. Header history/version strings can differ.

This pass measures **release reproducibility**, not new performance gains.
The renamed native executable passes all 12 product comparisons (six at each
size) at T0, with unchanged protected-input contents and modes. Compact receipts
are in [validation.json](bench/release-0.1.1/validation.json). Installed-from-source
and clean bottle-pour results remain required before completion.
Raw receipts, logs and immutable case outputs live under
`bench/out/release-0.1.1-20261023-221629/`.

## Packaging and publication acceptance

Pending: immutable source URL/SHA, source-built installed binary validation,
bottle SHA/platform/cellar metadata, clean pour verification, remote release and
tap readback. The source commit and packaging/tag commit may differ only in
release metadata and evidence; the executable patch set must be identical.
A HEAD-only bootstrap formula avoids a circular archive self-checksum; the
published stable formula will pin the verified immutable source archive.

## Limits retained

The previous strict 4K old/new T2 image checks and one-thread legacy T0 comparison
remain failed under their unchanged thresholds. These are separate from
incremental repeatability against the repaired current baseline. Four native
skips remain. No new claim is made for GPU hardware, MPI execution, every MS
layout, every observing mode, Linux packaging or all macOS versions. See the
[CPU correctness report](cpu-correctness-repairs-2026-10-22.md) and
[copy/masked-peak report](cpu-copy-and-masked-peak-2026-10-23.md).
