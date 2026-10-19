// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// CPU baseline for the Metal kernels: grids and degrids synthetic visibilities
// with ducc0's own w-gridder, on the same machine, so the Metal kernels can be
// compared against the code they would replace rather than against a scalar
// twin of themselves.
//
// The call mirrors wsclean's WGridder<NumT>::AddInversionMsImplementation()
// (BDA entry points, one band, flat visibility array, empty weight and mask
// views, flip_v, centered). Three things cost a lot of debugging and are
// recorded here:
//
//  * ducc0's grid coordinate is frac(u_lambda * pixsize) * nu, where u_lambda
//    is already scaled by frequency/c (getpix() in wgridder_impl.h). So
//    pixsize = 1/nxdirty puts one grid cell at one wavelength. A pixsize off by
//    orders of magnitude makes the data land outside the grid, and since the
//    scatter writes unconditionally this is a bus error, not a wrong image.
//  * sigma_min/sigma_max are NOT the uv extents: wsclean passes ducc0's
//    defaults (1.1, 2.0). Passing the uv extent makes the w-plane count explode
//    and the allocation die.
//  * The plain ms2dirty/dirty2ms entry points crash on this input even with
//    correct parameters; wsclean only exercises the _bda ones, so this tool
//    does the same.
//
// The data are planar (w = 0) and the run uses do_wgridding=false,
// allow_nshift=false: a pure 2D gridding, which is what the Metal kernels
// implement. ducc0's FFT and kernel correction are inside the measured call;
// they are noted in the report rather than subtracted here.

#include "ducc0/wgridder/wgridder_impl.h"
#include "ducc0/fft/fftnd_impl.h"  // r2r_separable_fht, which the gridder calls

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

namespace {

std::vector<float> makeVisibilities(std::size_t nvis, std::size_t grid, std::size_t ties = 64) {
  std::mt19937_64 random(20261018);  // same seed and distributions as the probe
  std::uniform_real_distribution<float> uv(-0.45f * static_cast<float>(grid),
                                           0.45f * static_cast<float>(grid));
  std::normal_distribution<float> flux(1.0f, 0.25f);
  std::vector<float> visibilities(4 * nvis);
  for (std::size_t v = 0; v < nvis; ++v) {
    visibilities[4 * v + 0] = uv(random);
    visibilities[4 * v + 1] = uv(random);
    visibilities[4 * v + 2] = flux(random);
    visibilities[4 * v + 3] = flux(random) * 0.5f;
  }
  visibilities.resize(4 * (nvis + ties), 0.0f);
  for (std::size_t k = 0; k < ties; ++k) {
    const float magnitude = 0.5f + static_cast<float>(k);
    visibilities[4 * (nvis + k) + 0] = (k % 2 == 0) ? magnitude : -magnitude;
    visibilities[4 * (nvis + k) + 1] = (k % 4 < 2) ? magnitude : -magnitude;
    visibilities[4 * (nvis + k) + 2] = 1.0f;
    visibilities[4 * (nvis + k) + 3] = -0.5f;
  }
  return visibilities;
}

}  // namespace

int main(int argc, char** argv) {
  std::size_t nvis = 200000;
  std::size_t grid = 1024;
  std::size_t nthreads = 8;
  double epsilon = 1.0e-4;
  int repeat = 3;
  for (int i = 1; i < argc; ++i) {
    const std::string argument = argv[i];
    auto value = [&](const char* name) -> const char* {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "%s needs a value\n", name);
        std::exit(2);
      }
      return argv[++i];
    };
    if (argument == "--nvis") {
      nvis = std::strtoull(value("--nvis"), nullptr, 10);
    } else if (argument == "--grid") {
      grid = std::strtoull(value("--grid"), nullptr, 10);
    } else if (argument == "--threads") {
      nthreads = std::strtoull(value("--threads"), nullptr, 10);
    } else if (argument == "--epsilon") {
      epsilon = std::strtod(value("--epsilon"), nullptr);
    } else if (argument == "--repeat") {
      repeat = std::atoi(value("--repeat"));
    } else {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 2;
    }
  }

  const std::vector<float> visibilities = makeVisibilities(nvis, grid);
  const std::size_t count = visibilities.size() / 4;

  // One grid cell per wavelength, as explained in the header.
  const double pixel_size = 1.0 / static_cast<double>(grid);
  constexpr double kSigmaMin = 1.1;  // ducc0's defaults, which wsclean passes
  constexpr double kSigmaMax = 2.0;

  std::vector<double> uvw(3 * count, 0.0);
  std::vector<std::complex<float>> ms(count);
  for (std::size_t v = 0; v < count; ++v) {
    uvw[3 * v + 0] = visibilities[4 * v + 0];
    uvw[3 * v + 1] = visibilities[4 * v + 1];
    uvw[3 * v + 2] = 0.0;
    ms[v] = std::complex<float>(visibilities[4 * v + 2], visibilities[4 * v + 3]);
  }

  const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {count, 3});
  const size_t n_freq_entries = 1;
  const std::vector<double> frequencies(n_freq_entries, 1.0);
  const ducc0::cmav<size_t, 1> freqlist_id = ducc0::cmav<size_t, 1>::build_uniform({count}, 0);
  const ducc0::cmav<size_t, 1> freqlist_nfreqs =
      ducc0::cmav<size_t, 1>::build_uniform({1}, n_freq_entries);
  const ducc0::cmav<double, 1> freqlist_freqs(frequencies.data(), {n_freq_entries});
  const ducc0::cmav<std::complex<float>, 1> ms_ma(ms.data(), {count});
  const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
  const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
  ducc0::vmav<float, 2> dirty({grid, grid});
  ducc0::vmav<std::complex<float>, 1> predicted({count});

  constexpr bool kDoWgridding = false;
  constexpr bool kFlipU = false;
  constexpr bool kFlipV = true;
  constexpr bool kFlipW = false;
  constexpr bool kDivideByN = false;
  constexpr bool kAllowNShift = false;
  constexpr size_t kVerbosity = 0;

  auto grid_once = [&]() {
    ducc0::detail_gridder::ms2dirty_bda<float, float>(
        uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, ms_ma, weight_ma, mask_ma, pixel_size,
        pixel_size, epsilon, kDoWgridding, nthreads, dirty, kVerbosity, kFlipU, kFlipV, kFlipW,
        kDivideByN, kSigmaMin, kSigmaMax, 0.0, 0.0, kAllowNShift);
  };
  auto degrid_once = [&]() {
    ducc0::detail_gridder::dirty2ms_bda<float, float, float>(
        uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, dirty, weight_ma, mask_ma, pixel_size,
        pixel_size, epsilon, kDoWgridding, nthreads, predicted, kVerbosity, kFlipU, kFlipV, kFlipW,
        kDivideByN, kSigmaMin, kSigmaMax, 0.0, 0.0, kAllowNShift);
  };

  std::fprintf(stderr, "[stage] %zu rows, calling ms2dirty_bda\n", count);
  grid_once();  // warm up: threads, allocators, kernel tables
  std::fprintf(stderr, "[stage] gridding ok, calling dirty2ms_bda\n");
  degrid_once();
  std::fprintf(stderr, "[stage] degridding ok, timing\n");

  double best_grid = 1e30, best_degrid = 1e30;
  for (int r = 0; r < repeat; ++r) {
    const auto begin_grid = std::chrono::steady_clock::now();
    grid_once();
    const auto end_grid = std::chrono::steady_clock::now();
    best_grid = std::min(best_grid, std::chrono::duration<double>(end_grid - begin_grid).count());

    const auto begin_degrid = std::chrono::steady_clock::now();
    degrid_once();
    const auto end_degrid = std::chrono::steady_clock::now();
    best_degrid =
        std::min(best_degrid, std::chrono::duration<double>(end_degrid - begin_degrid).count());
  }

  double dirty_sum = 0.0;
  for (std::size_t i = 0; i < static_cast<std::size_t>(grid) * grid; ++i) dirty_sum += dirty.raw(i);
  double ms_sum = 0.0;
  for (std::size_t v = 0; v < count; ++v) ms_sum += std::real(predicted(v));

  std::printf("ducc0_cpu nvis=%zu grid=%zu threads=%zu epsilon=%.3g\n", count, grid, nthreads,
              epsilon);
  std::printf("ducc0_cpu grid_ms=%.2f degrid_ms=%.2f total_ms=%.2f throughput_Mvis_s=%.1f "
              "(min of %d, after warm-up)\n",
              best_grid * 1e3, best_degrid * 1e3, (best_grid + best_degrid) * 1e3,
              static_cast<double>(count) / (best_grid + best_degrid) / 1e6, repeat);
  // Sanity: the data must actually land inside the grid, or the timing would be
  // measuring an empty transform.
  std::printf("ducc0_cpu dirty_sum=%.6g predicted_sum=%.6g\n", dirty_sum, ms_sum);
  return (dirty_sum != 0.0 && std::isfinite(dirty_sum)) ? 0 : 1;
}
