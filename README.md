# wsclean-mx

WSClean optimized for macOS on Apple Silicon.

wsclean-mx is a small patch set on top of upstream
[WSClean](https://gitlab.com/aroffringa/wsclean), pinned to the exact commit
that ships in the LINC 5.2.1 container (`2d5c1ed8`, WSClean 3.7). It builds
natively for arm64, moves serial FFT and deconvolution work onto all cores,
and removes I/O and locking bottlenecks.
It also fixes an upstream bug that corrupts 2048² images on macOS. Images
agree with upstream and LINC to within upstream's own run-to-run variation.

On a fanless MacBook Air M2 (16 GB), a full-sky 2048² multiscale clean
(niter 3000) of one OVRO-LWA snapshot takes:

| Build | Wall time |
|-------|-----------|
| **wsclean-mx** (native arm64, patches 1–11) | **11.4 s** |
| upstream WSClean (native arm64, with the padding fix) | 23.7 s |
| LINC 5.2.1 container (Apple `container`, Rosetta)\* | 43.4 s |
| LINC 5.2.1 on Linux, 2× Xeon Silver 4214, `-j 8`\* | 49.3 s |

\*Measured 2026-10-13, when wsclean-mx (patches 1–6) took 12.4 s and
upstream 20.6 s; the Mac is memory-tight, so sessions differ by ~15%.
A 4096² dirty image takes 1.9 s with wsclean-mx vs 4.2 s with upstream.

![patches 7-11](docs/bench/p11.png)
![2048² multiscale on M2 and Xeon](docs/bench/platforms_ms2k.png)

Full results, plots and methodology: [benchmark.md](benchmark.md). Progress
log: [issue #1](https://github.com/peijin94/wsclean-mx/issues/1).

## The patches

The patch set lives in `patches/mx/<repo>/`, one directory per library:

| Patch | What it does | Effect |
|-------|--------------|--------|
| schaapcommon/0001 | Resampler: multithreaded ducc0 FFT instead of single-threaded FFTW | inversion 1.5×, prediction 1.8× at 4096² |
| schaapcommon/0002 | Convolve: multithreaded ducc0 FFT instead of FFTW | multiscale deconvolution ~2× |
| aocommon/0001 | Median/MAD: radix-histogram select instead of a full `nth_element` | MAD of 4096² image 300 → 65 ms |
| wsclean/0001 | `WGridder::RealImage` pads with 0 instead of NaN | fixes corrupt images under Apple clang `-ffast-math` |
| radler/0001 | SubMinorLoop: multithreaded PSF subtraction and peak search | Högbom deconvolution 6.2 → 2.4 s at 4096² |
| radler/0002, schaapcommon/0003 | Multiscale: one residual FFT per peak search, cached scale-kernel FFTs | fewer FFTs per multiscale iteration |
| radler/0003 | Multiscale: reuse the scale-convolved residual, cache per-scale PSF transforms | deconvolution 4.18 → 3.64 s at 2048² |
| schaapcommon/0004 | ducc0 gridder: spin lock per grid row instead of `std::mutex` | lock time ~5× lower |
| wsclean/0002 | Read measurement set columns in blocks of rows (direct reads) | 4096² dirty image 1.70× |
| wsclean/0003 | Same, during reordering (cleaning runs) | reordering 2.3× |
| radler/0004 | Peak finder: vectorized row maximum skips rows | peak search 8×, deconvolution 1.12× |

The upstream padding bug: `WGridder::RealImage()` fills image padding with
NaN, but its source file is compiled with `-ffast-math`, and Apple clang
drops the fill. The padding is then uninitialized memory, so with the default
small inversion many 2048² dirty images are garbage. GCC builds (LINC) are
not affected. Details are in [benchmark.md](benchmark.md).

## Building

Requirements: Apple Silicon Mac, Xcode command line tools, and
[Homebrew](https://brew.sh).

```bash
brew install cmake ninja gcc fftw cfitsio hdf5 gsl boost openblas wcslib \
    pybind11 open-mpi uv
brew tap ska-sa/tap && brew install ska-sa/tap/casacore-data

git clone --recursive git@github.com:peijin94/wsclean-mx.git
cd wsclean-mx
scripts/build_deps.sh       # casacore 3.8.2 -> deps/install
scripts/build_mx.sh         # wsclean-mx      -> build-mx/wsclean
scripts/build_upstream.sh   # (optional) unpatched reference -> build-upstream/wsclean
```

`build-mx/wsclean` is a drop-in WSClean binary with the usual command line:

```bash
build-mx/wsclean -size 2048 2048 -scale 0.0625 -weight briggs 0 \
    -mgain 0.8 -multiscale -niter 3000 -name out/img my.ms
```

Build notes:

- casacore is built locally because the Homebrew and `/usr/local` versions are
  too old; system packages are left untouched.
- If `ROOT` is set in your shell, `unset ROOT` before building; the scripts
  use it to locate `deps/`.
- `scripts/check_headers.sh` (run by the build) fails if headers from another
  casacore were picked up.

## Repository layout

```
upstream/wsclean/      git submodule, pristine upstream at 2d5c1ed8 (never edited)
patches/mx/<repo>/     the wsclean-mx patch set (source of truth)
patches/build/         macOS build fixes, applied to both reference and mx builds
scripts/               dependency, reference and mx builds; dev-tree tools
bench/                 benchmark and comparison harness
docs/bench/            benchmark figures
benchmark.md           benchmark results
mem.md, notes.md       project notes and design plan
```

Development happens in `work/<repo>` git trees (branch `mx`), created from
the patch set by `scripts/mx_tree.sh init`. After committing there,
`scripts/mx_tree.sh export <repo>` writes the patches back to `patches/mx/`.

## Benchmarking

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r bench/requirements.txt
container system start
container image pull --platform linux/amd64 docker.io/astronrd/linc:5.2.1

bench/run.sh mx mytag <wsclean args>              # one run -> bench/out/mytag/mx/
REPS=2 COOL=30 bench/ab.sh mytag mx,upstream,linc <wsclean args>   # alternating A/B
.venv/bin/python bench/compare_fits.py bench/out/mytag-r1/linc bench/out/mytag-r1/mx
.venv/bin/python bench/plot_report.py             # regenerate docs/bench/*.png
```

Variants are `mx`, `upstream`, `linc` (the LINC container under Rosetta), or
any frozen build in `bench/bin/<name>/` (`bench/snapshot.sh`). `run.sh`
always adds `-no-update-model-required` so the measurement set is never
written.

Comparisons follow three tiers: bitwise (at `-j 1`, against the native
upstream build), ULP, and scientific (rms difference relative to the
reference). Multithreaded cleaning is not deterministic, so cleaned images
are judged against upstream's own rerun spread.

## Roadmap

The current patches are CPU-only. Planned next steps, described in
`notes.md`: a Metal GPU gridding backend and benchmarks on larger
measurement sets where gridding dominates. Accelerate's vDSP 2D FFT was
measured and is slower than ducc0's multithreaded FFT, so it is not used.

## License

wsclean-mx is a modified version of WSClean and is distributed under the
[GNU General Public License v3](LICENSE), like WSClean itself. Each patch
keeps the license of the upstream file it changes: the radler patches are
LGPL-3.0-only ([LICENSE.LESSER](LICENSE.LESSER) together with
[LICENSE](LICENSE)), the others GPL-3.0. Original files in this repository
are GPL-3.0-or-later.

[NOTICE.md](NOTICE.md) has the upstream copyrights and pinned sources, a
dated list of every modification (GPLv3 section 5), and what to include when
distributing a binary (section 6: the Corresponding Source is this repository
at the build commit plus the pinned upstream sources).

Copyright (C) 2026 Peijin Zhang. WSClean is Copyright (C) André Offringa and
contributors; aocommon, schaapcommon and radler are Copyright (C) ASTRON.
This program comes with ABSOLUTELY NO WARRANTY.
