# NOTICE

wsclean-mx is a modified version of WSClean and of the libraries it builds
with. It is distributed under the GNU General Public License, version 3
(`LICENSE`), the license of WSClean. This file gives the attribution and the
modification notices required by section 5(a) of the GPLv3.

wsclean-mx: Copyright (C) 2026 Peijin Zhang <peijin@ustc.edu>

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for details.

## Upstream works

| Component | Copyright | License | Source, pinned commit |
|-----------|-----------|---------|-----------------------|
| WSClean | André Offringa and contributors | GPL-3.0 | <https://gitlab.com/aroffringa/wsclean> `2d5c1ed8d7559e5178d243661b408baa288681e6` (2026-09-07) |
| aocommon | ASTRON (Netherlands Institute for Radio Astronomy), André Offringa | GPL-3.0-or-later | <https://gitlab.com/aroffringa/aocommon> `e1b7980e02211ade95eef176a3ac7f9ba3dcc55c` |
| schaapcommon | ASTRON | GPL-3.0-or-later | <https://git.astron.nl/RD/schaapcommon> `b47f19dace28ad420c0a7c8ab1014b55b75205e9` |
| ducc0 (bundled in schaapcommon) | Max-Planck-Society | GPL-2.0-or-later | via schaapcommon |
| radler | ASTRON | LGPL-3.0-only (`LICENSE.LESSER` with `LICENSE`) | <https://git.astron.nl/RD/radler> `940e9617a4b3210228a849513752f0732df8104a` |

WSClean is included unmodified as the git submodule `upstream/wsclean/`.
aocommon, schaapcommon and radler are fetched at build time at the commits
above. casacore (LGPL-3.0, v3.8.2) and the Homebrew libraries are built or
installed separately and are not part of this repository.

## Licensing of this repository

- `patches/<kind>/<repo>/*.patch` are modifications of the upstream files
  they change, and are licensed under the license of those files: the radler
  patches under LGPL-3.0-only, the others under GPL-3.0 (aocommon,
  schaapcommon: GPL-3.0-or-later). `patches/mx/schaapcommon/0004` and `0009` change
  the ducc0 sources bundled in schaapcommon and are GPL-2.0-or-later, like
  ducc0.
- All other files (build scripts, benchmark tools, documentation, figures)
  are Copyright (C) 2026 Peijin Zhang, licensed under GPL-3.0-or-later.
  Exceptions are marked in the file headers: `bench/micro/subminor_loop.cpp`
  and `bench/micro/peak_simple.cpp` adapt radler code and are LGPL-3.0-only;
  `bench/micro/convolve_check.cpp`
  and `bench/micro/median_select.cpp` contain schaapcommon and aocommon code.
- A wsclean-mx binary combines all of the above and is distributed under
  GPL-3.0.

## Modification notices (GPLv3 section 5(a))

All modifications were made by Peijin Zhang. Each patch file also records
its author and date in its header.

| Date | Patch | Modified upstream files | Change |
|------|-------|-------------------------|--------|
| 2026-10-13 | `patches/build/wsclean/2d5c1ed8d755/0001-include-semaphore.patch` | wsclean `gridding/msgridder.h` | add a missing `#include <semaphore>` (build fix for libc++) |
| 2026-10-13 | `patches/build/schaapcommon/b47f19dace28/0001-skip-z-notext-on-apple.patch` | schaapcommon `src/threading/CMakeLists.txt` | skip the ELF-only `-Wl,-z,notext` linker flag on Apple |
| 2026-10-13 | `patches/mx/schaapcommon/0001-Resampler-...patch` | schaapcommon `include/schaapcommon/math/resampler.h`, `src/math/resampler.cc` | multithreaded ducc0 FFT instead of single-threaded FFTW |
| 2026-10-13 | `patches/mx/schaapcommon/0002-Convolve-...patch` | schaapcommon `src/math/convolution.cc` | multithreaded ducc0 FFT instead of FFTW |
| 2026-10-13 | `patches/mx/aocommon/0001-Median-MAD-...patch` | aocommon `include/aocommon/image.h` | radix-histogram select for Median/MAD |
| 2026-10-13 | `patches/mx/wsclean/0001-WGridder-RealImage-...patch` | wsclean `wgridder/wgridder_implementation.h` | pad with 0 instead of NaN (fixes uninitialized padding under `-ffast-math`) |
| 2026-10-13 | `patches/mx/radler/0001-SubMinorLoop-...patch` | radler `cpp/algorithms/subminor_loop.{h,cc}`, `cpp/image_set.{h,cc}` | multithreaded PSF subtraction and peak search |
| 2026-10-13 | `patches/mx/radler/0002-Multiscale-...patch` | radler `cpp/algorithms/multiscale/multiscale_transforms.{h,cc}`, `cpp/algorithms/multiscale_algorithm.{h,cc}`, `cpp/algorithms/threaded_deconvolution_tools.{h,cc}` | one residual FFT per peak search, cached scale-kernel FFTs |
| 2026-10-13 | `patches/mx/schaapcommon/0003-Convolve-...patch` | schaapcommon `include/schaapcommon/math/convolution.h`, `src/math/convolution.cc` | expose the forward transform and convolution with a transformed kernel |
| 2026-10-17 | `patches/mx/radler/0003-Multiscale-reuse-...patch` | radler `cpp/algorithms/subminor_loop.{h,cc}`, `cpp/algorithms/multiscale_algorithm.{h,cc}`, `cpp/algorithms/threaded_deconvolution_tools.{h,cc}` | reuse the scale-convolved residual from the peak search; cache per-scale PSF kernel transforms |
| 2026-10-17 | `patches/mx/schaapcommon/0004-ducc0-wgridder-...patch` | ducc0 (in schaapcommon) `external/ducc0/wgridder/wgridder_impl.h` | spin lock per grid row instead of `std::mutex` |
| 2026-10-17 | `patches/mx/wsclean/0002-ContiguousMSReader-...patch` | wsclean `msproviders/msreaders/contiguousmsreader.{h,cpp}` | read measurement set columns in blocks of rows |
| 2026-10-17 | `patches/mx/wsclean/0003-MSRowProvider-...patch` | wsclean `msproviders/columnblock.h` (new), `msproviders/msreaders/contiguousmsreader.{h,cpp}`, `msproviders/rowproviders/{msrowprovider,directmsrowprovider}.{h,cpp}` | read measurement set columns in blocks of rows during reordering |
| 2026-10-17 | `patches/mx/radler/0004-peak_finder-Simple-...patch` | radler `cpp/math/peak_finder.cc` | skip rows that cannot raise the peak (vectorizable row maximum) |
| 2026-10-17 | `patches/mx/radler/0005-Multiscale-...patch` | radler `cpp/algorithms/threaded_deconvolution_tools.cc` | allocate full-image peak-search scratch only when RMS weighting uses it |
| 2026-10-22 | `patches/mx/radler/0009-peak_finder-fuse-CPU-RMS-weighted-peak-scans.patch` | radler `cpp/math/peak_finder.{h,cc}`, `cpp/algorithms/threaded_deconvolution_tools.cc` | scan CPU float32 weighted products directly with ordered ties; retain AVX/GPU-hook paths and eliminate a weighted full-image temporary |
| 2026-10-17 | `patches/mx/wsclean/0004-ColumnBlock-...patch` | wsclean `msproviders/columnblock.h`, `msproviders/msreaders/contiguousmsreader.cpp`, `msproviders/rowproviders/msrowprovider.{h,cpp}`, `tests/CMakeLists.txt`, `tests/msproviders/tcolumnblockselection.cpp` (new) | selection-safe block fallback, complete selected-cell shape validation and production-reader regression fixtures |
| 2026-10-17 | `patches/mx/aocommon/0002-MultiArray-...patch` | aocommon `include/aocommon/multiarray.h` | use malloc for fundamental alignment and retain aligned_alloc for extended alignment |
| 2026-10-17 | `patches/mx/wsclean/0005-InMemoryProvider-...patch` | wsclean `msproviders/{inmemoryprovider,msprovider}.h`, `tests/msproviders/tinmemoryprovider.cpp`, `tests/interface/twsclean.cpp` | return MJD days at the provider boundary; assert provider units and FITS observation date |
| 2026-10-22 | `patches/mx/wsclean/0055-providers-...patch` | wsclean `gridding/msprovidercollection.cpp`, `io/readinmemory.{cpp,h}`, `msproviders/{contiguousms,operations}.{cpp,h}`, `msproviders/msreaders/reorderedmsreader.{cpp,h}`, `msproviders/rowproviders/{msrowprovider.cpp,msrowproviderbase.h}` | repair independent payload positions, vertical UV bounds, loader column/shape contracts and empty interval/epoch handling |
| 2026-10-22 | `patches/mx/radler/0010-math-...patch` | radler `cpp/math/{dijkstra_splitter,rms_image}.{cc,h}` and native tests | repair empty/padded masks and clipped/aliased/nonfinite RMS windows; preserve unspecified equal-cost shortest-path ties |
| 2026-10-22 | `patches/mx/schaapcommon/0009-ducc0-...patch` | bundled ducc0 `external/ducc0/wgridder/wgridder_impl.h`, `external/ducc0/infra/threading.cc` | canonical channel/tile grouping and bounded ordered partial merges; drain accepted workers on callback or submission failure |

A wsclean-mx binary still reports upstream's version string ("WSClean
version 3.7"); it is a modified version as described above.

## Distributing binaries

Anyone who conveys a wsclean-mx binary must also make the Corresponding
Source available to its recipients under the GPLv3 (section 6). That source
is this repository at the commit used for the build (patches and build
scripts) together with the upstream sources at the pinned commits listed
above.
