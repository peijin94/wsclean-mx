// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// CPU baseline for the Metal round-trip benchmark: grids and degrids the SAME
// synthetic visibilities with ducc0's own ms2dirty/dirty2ms (the code the
// w-gridder path runs), on the same machine, so the Metal kernels can be
// compared against the thing they would replace rather than against a scalar
// twin of themselves.
//
// The visibility generator, seeding and distribution replicate
// mx-metal-probe's grid-test data exactly; the uv coordinates are in units of
// one gridding cell, and 1 cell is declared to be 1 lambda by choosing
// pixsize = 1/nx.
//
// STATUS (2026-10-19): PARKED. It compiles against ducc0's own gridder but
// segfaults with the parameters tried so far - the uv/pixel-size mapping is not
// wsclean's (see docs/metal-plan.md, "Parked"). Kept because the plumbing
// (includes, flags, 2D views) is the hard part and is already resolved here.
// The stage-level CPU comparison in docs/metal-plan.md stands on its own.

#include "ducc0/wgridder/wgridder.h"       // ms2dirty / dirty2ms definitions
#include "ducc0/wgridder/wgridder_impl.h"  // the gridder internals they use
#include "ducc0/fft/fftnd_impl.h"        // r2r_separable_fht (wsclean includes this too)

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <cstring>
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

  // uv in wavelengths: one gridding cell equals 1 lambda, so the image pixel
  // size is 1/nx and the uv extents are the data's own.
  const double pixel_size = 1.0 / static_cast<double>(grid);
  const double frequency = 1.0;
  std::vector<double> uvw(3 * count, 0.0);
  double sigma_max = 0.0;
  for (std::size_t v = 0; v < count; ++v) {
    uvw[3 * v + 0] = visibilities[4 * v + 0];
    uvw[3 * v + 1] = visibilities[4 * v + 1];
    uvw[3 * v + 2] = 0.0;
    sigma_max = std::max({sigma_max, std::fabs(uvw[3 * v + 0]), std::fabs(uvw[3 * v + 1])});
  }
  const double sigma_min = 1.0;
  std::vector<double> frequencies(count, frequency);
  // ducc0's gridder indexes ms(row, channel): the visibility array is 2D
  // (nrows x nchan), exactly as wsclean passes it.
  ducc0::vmav<std::complex<float>, 2> ms({count, 1});
  for (std::size_t v = 0; v < count; ++v) {
    ms(v, 0) = std::complex<float>(visibilities[4 * v + 2], visibilities[4 * v + 3]);
  }

  ducc0::cmav<double, 2> uvw_ma(uvw.data(), {count, 3});
  ducc0::cmav<double, 1> freq_ma(frequencies.data(), {count});
  const ducc0::cmav<std::complex<float>, 2> ms_ma = ms;
  // Real weights and mask: ducc0's gridder indexes them per (row, channel) and
  // an empty view segfaults.
  ducc0::vmav<float, 2> weights({count, 1});
  ducc0::vmav<std::uint8_t, 2> mask({count, 1});
  for (std::size_t v = 0; v < count; ++v) {
    weights(v, 0) = 1.0f;
    mask(v, 0) = 1;
  }
  const ducc0::cmav<float, 2> weight_ma = weights;
  const ducc0::cmav<std::uint8_t, 2> mask_ma = mask;
  ducc0::vmav<float, 2> dirty({grid, grid});
  ducc0::vmav<std::complex<float>, 2> predicted({count, 1});

  auto grid_once = [&]() {
    ducc0::detail_gridder::ms2dirty<float, float>(
        uvw_ma, freq_ma, ms_ma, weight_ma, mask_ma, pixel_size, pixel_size, epsilon,
        /*do_wgridding=*/true, nthreads, dirty, /*verbosity=*/0, /*flip_u=*/false,
        /*flip_v=*/false, /*flip_w=*/false, /*divide_by_n=*/false, sigma_min, sigma_max,
        /*center_x=*/0.0, /*center_y=*/0.0, /*allow_nshift=*/true);
  };
  auto degrid_once = [&]() {
    ducc0::detail_gridder::dirty2ms<float, float>(
        uvw_ma, freq_ma, dirty, weight_ma, mask_ma, pixel_size, pixel_size, epsilon,
        /*do_wgridding=*/true, nthreads, predicted, /*verbosity=*/0, /*flip_u=*/false,
        /*flip_v=*/false, /*flip_w=*/false, /*divide_by_n=*/false, sigma_min, sigma_max,
        /*center_x=*/0.0, /*center_y=*/0.0, /*allow_nshift=*/true);
  };

  grid_once();     // warm up: threads, allocators, kernel tables
  degrid_once();

  double best_grid = 1e30, best_degrid = 1e30;
  for (int r = 0; r < repeat; ++r) {
    const auto begin_grid = std::chrono::steady_clock::now();
    grid_once();
    const auto end_grid = std::chrono::steady_clock::now();
    const double grid_seconds = std::chrono::duration<double>(end_grid - begin_grid).count();
    best_grid = std::min(best_grid, grid_seconds);

    const auto begin_degrid = std::chrono::steady_clock::now();
    degrid_once();
    const auto end_degrid = std::chrono::steady_clock::now();
    const double degrid_seconds = std::chrono::duration<double>(end_degrid - begin_degrid).count();
    best_degrid = std::min(best_degrid, degrid_seconds);
  }

  double dirty_sum = 0.0;
  for (std::size_t i = 0; i < static_cast<std::size_t>(grid) * grid; ++i) dirty_sum += dirty.raw(i);
  double ms_sum = 0.0;
  for (std::size_t v = 0; v < count; ++v) ms_sum += std::real(predicted(v, 0));

  std::printf("ducc0_cpu nvis=%zu grid=%zu threads=%zu epsilon=%.3g sigma_max=%.4g\n", count,
              grid, nthreads, epsilon, sigma_max);
  std::printf("ducc0_cpu grid_ms=%.2f degrid_ms=%.2f total_ms=%.2f throughput_Mvis_s=%.1f "
              "(min of %d, after warm-up)\n",
              best_grid * 1e3, best_degrid * 1e3, (best_grid + best_degrid) * 1e3,
              static_cast<double>(count) / (best_grid + best_degrid) / 1e6, repeat);
  // Sanity: the data must actually land inside the grid, or the timing would be
  // measuring an empty transform.
  std::printf("ducc0_cpu dirty_sum=%.6g predicted_sum=%.6g ratio=%.4g\n", dirty_sum, ms_sum,
              ms_sum != 0.0 ? dirty_sum / ms_sum : 0.0);
  return (dirty_sum != 0.0 && std::isfinite(dirty_sum)) ? 0 : 1;
}
