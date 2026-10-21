// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// Image-level check of the Metal gridding: grid on the GPU, push that grid
// through ducc0's own forward chain, and compare the dirty image with
// ducc0::ms2dirty_bda on identical data. This is what makes wiring the GPU
// gridder into wsclean's WGridder possible - the probe only ever compared
// grids, while an image needs the padded grid, the Hartley transform and
// ducc0's kernel correction.
//
// Reproduced exactly (ducc0's do_wgridding=false path):
//   grid -> complex2hartley -> hartley2_2D(vlim, uv_side_fast) -> extract the
//   inner nxdirty x nydirty cells with cfu/cfv = krn->corfunc(n/2+1, 1/nu)
// ducc0's functions do the work; only the four-line cell extraction is copied
// from grid2dirty_post. Note that x2dirty's non-wgridding branch does NOT call
// apply_global_corrections (that only runs for w-gridding), so the 2D chain
// needs no w-screen and no corfunc(0) factor.
//
// Three things had to be matched, each of which cost a debugging round:
//
//  1. DC-at-0 frame. ducc0's getpix uses frac(u*pixsize), so the origin sits at
//     index 0, and hartley2_2D's band logic (only [0,vlim) and [nv-vlim,nv) are
//     transformed) depends on it. The Metal kernels centre the origin, so the
//     grid is rolled by half a grid before the forward chain.
//  2. The kernel is chosen by ducc0's COST MODEL (getNuNv), not by smallest
//     support: picking the smallest support gives W=6 where ducc0 uses another
//     W, and since the grid correction comes from the same kernel, the whole
//     image then lands on a different scale (~11% - it looks like a missing
//     factor but is a different kernel).
//  3. The grid geometry follows the chosen kernel: nu = 2*good_size_complex(
//     nxdirty*ofactor*0.5+1) and pixsize = 1/nu give one wavelength per cell on
//     ducc0's side, so the Metal grid is nu cells of one wavelength too (rounded
//     up to the kernel's 32-cell tile).
//
// Build/run through scripts/metal_image_check.sh.

#include "metal/metaldevice.h"

#include "ducc0/wgridder/wgridder_impl.h"
#include "ducc0/fft/fftnd_impl.h"
#include "ducc0/math/gridding_kernel.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

#include "uvw_file.h"  // shared real-data reader (work/wsclean/metal)

namespace {

constexpr double kSpeedOfLight = 299792458.0;

struct Data {
  std::vector<double> u_lambda, v_lambda;  // wavelengths
  std::vector<std::complex<float>> values;
  double v_max_lambda = 0.0;
  std::size_t rows() const { return values.size(); }
};

Data makeSynthetic(std::size_t nvis, double max_lambda) {
  std::mt19937_64 random(20261019);  // same seed as the w-layer harness
  std::uniform_real_distribution<double> uv(-max_lambda, max_lambda);
  std::normal_distribution<double> flux(1.0, 0.25);
  Data data;
  data.u_lambda.resize(nvis);
  data.v_lambda.resize(nvis);
  data.values.resize(nvis);
  for (std::size_t v = 0; v < nvis; ++v) {
    data.u_lambda[v] = uv(random);
    data.v_lambda[v] = uv(random);
    data.values[v] = std::complex<float>(static_cast<float>(flux(random)),
                                         static_cast<float>(flux(random) * 0.5));
    data.v_max_lambda = std::max({data.v_max_lambda, std::fabs(data.u_lambda[v]),
                                  std::fabs(data.v_lambda[v])});
  }
  return data;
}

Data loadReal(const std::string& path, double frequency) {
  const mxbench::RealVisibilitySet set = mxbench::LoadUvwFile(path);
  Data data;
  data.u_lambda.resize(set.rows.size());
  data.v_lambda.resize(set.rows.size());
  data.values.resize(set.rows.size());
  for (std::size_t v = 0; v < set.rows.size(); ++v) {
    const mxbench::RealVisibility& row = set.rows[v];
    data.u_lambda[v] = row.u_m * frequency / kSpeedOfLight;
    data.v_lambda[v] = row.v_m * frequency / kSpeedOfLight;
    data.values[v] = std::complex<float>(row.re, row.im);
    data.v_max_lambda = std::max({data.v_max_lambda, std::fabs(data.u_lambda[v]),
                                  std::fabs(data.v_lambda[v])});
  }
  return data;
}

// ducc0's getNuNv() cost model: minimise fftcost(nu,nv) + gridcost(nvis,supp).
double sigmoidScaling(double x, double m, double s) {
  const double x2 = x - 1.0, m2 = m - 1.0;
  return 1.0 + x2 / std::pow(1.0 + std::pow(x2 / m2, s), 1.0 / s);
}

std::size_t chooseKernel(const std::vector<std::size_t>& candidates, std::size_t image_size,
                         std::size_t rows, std::size_t nthreads, double& ofactor_out,
                         double& cost_out) {
  constexpr double kNrefFft = 2048.0, kCostRefFft = 0.0693;
  constexpr std::size_t kSimdWidth = 4;  // float, NEON
  const double log_term_ref = std::log(kNrefFft * kNrefFft);
  std::size_t best = candidates.front();
  double best_cost = 1e300, best_ofactor = 0.0;
  for (const std::size_t index : candidates) {
    const ducc0::KernelParams& params = ducc0::getKernel(index);
    const std::size_t supp = params.W;
    const std::size_t nvec = (supp + kSimdWidth - 1) / kSimdWidth;
    const std::size_t nu = 2 * ducc0::good_size_complex(
                                   static_cast<std::size_t>(image_size * params.ofactor * 0.5) + 1);
    double fft_cost = static_cast<double>(nu) / kNrefFft * static_cast<double>(nu) / kNrefFft *
                      (std::log(static_cast<double>(nu * nu)) / log_term_ref) * kCostRefFft;
    double grid_cost = 2.2e-10 * static_cast<double>(rows) *
                       static_cast<double>(supp * nvec * kSimdWidth +
                                           (2 * nvec + 1) * (supp + 3) * kSimdWidth);
    grid_cost /= static_cast<double>(nthreads);
    fft_cost /= sigmoidScaling(static_cast<double>(nthreads), 6.0, 2.0);
    const double cost = fft_cost + grid_cost;
    if (cost < best_cost) {
      best_cost = cost;
      best = index;
      best_ofactor = params.ofactor;
    }
  }
  ofactor_out = best_ofactor;
  cost_out = best_cost;
  return best;
}

}  // namespace

int main(int argc, char** argv) {
  std::size_t nvis = 100000;
  std::size_t image_size = 1024;
  std::string uvw_file;
  double frequency = 0.0;
  int repeat = 3;
  std::size_t nthreads = 8;
  double epsilon = 1.0e-4;
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
    } else if (argument == "--size") {
      image_size = std::strtoull(value("--size"), nullptr, 10);
    } else if (argument == "--uvw-file") {
      uvw_file = value("--uvw-file");
    } else if (argument == "--freq") {
      frequency = std::strtod(value("--freq"), nullptr);
    } else if (argument == "--repeat") {
      repeat = std::max(1, std::atoi(value("--repeat")));
    } else if (argument == "--epsilon") {
      epsilon = std::strtod(value("--epsilon"), nullptr);
    } else if (argument == "--threads") {
      nthreads = std::strtoull(value("--threads"), nullptr, 10);
    } else {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 2;
    }
  }

  // Data first (the kernel choice depends on the row count), uv in wavelengths.
  const Data data = uvw_file.empty() ? makeSynthetic(nvis, 0.45 * static_cast<double>(image_size))
                                     : loadReal(uvw_file, frequency);
  if (data.rows() == 0) {
    std::fprintf(stderr, "no usable rows\n");
    return 2;
  }

  // ---- ducc0's kernel choice and the grid geometry that follows from it ----
  const std::vector<std::size_t> candidates = ducc0::getAvailableKernels<float>(epsilon, 2, 1.1, 2.0);
  if (candidates.empty()) {
    std::fprintf(stderr, "ducc0 returned no kernel candidates\n");
    return 2;
  }
  double ofactor = 0.0, cost = 0.0;
  const std::size_t index = chooseKernel(candidates, image_size, data.rows(), nthreads, ofactor, cost);
  const ducc0::KernelParams& params = ducc0::getKernel(index);
  const std::shared_ptr<ducc0::PolynomialKernel> kernel = ducc0::selectKernel(index);
  const std::size_t nu = 2 * ducc0::good_size_complex(
                                 static_cast<std::size_t>(image_size * ofactor * 0.5) + 1);
  const std::size_t nu_metal = ((nu + 31) / 32) * 32;
  const double pixel_size = 1.0 / static_cast<double>(nu);  // one wavelength per cell
  std::printf("kernel index=%zu W=%zu ofactor=%.3f cost=%.4g nu=%zu nu_metal=%zu image=%zu\n", index,
              params.W, ofactor, cost, nu, nu_metal, image_size);
  std::printf("rows=%zu v_max=%.1f lambda\n", data.rows(), data.v_max_lambda);

  // ---- Metal gridding: one wavelength per cell, centred frame ----
  mx::metal::GridAccumInput input;
  input.grid_size = nu_metal;
  input.support = kernel->support();
  input.beta = static_cast<float>(params.beta);
  input.e0 = static_cast<float>(params.e0);
  input.kernel_degree = kernel->degree();
  input.kernel_coefficients.assign(kernel->Coeff().begin(), kernel->Coeff().end());
  input.variant = mx::metal::Variant::kPoly;
  // The Metal grid is nu_metal cells wide, so scale the uv coordinates by
  // nu/nu_metal: the grid then covers exactly nu wavelengths like ducc0's, and
  // both images get the same pixel scale (1/nu). Without this the two images
  // differ by nu_metal/nu in scale - a ~1.6% error that grows towards the field
  // edge and reads as a ~0.8% rms kernel mismatch.
  const double cell_scale = static_cast<double>(nu_metal) / static_cast<double>(nu);
  input.visibilities.resize(6 * data.rows());
  for (std::size_t v = 0; v < data.rows(); ++v) {
    const double cell_u = data.u_lambda[v] * cell_scale;
    const double cell_v = data.v_lambda[v] * cell_scale;
    const double base_u = std::floor(cell_u);
    const double base_v = std::floor(cell_v);
    input.visibilities[6 * v + 0] = static_cast<float>(base_u);
    input.visibilities[6 * v + 1] = static_cast<float>(cell_u - base_u);
    input.visibilities[6 * v + 2] = static_cast<float>(base_v);
    input.visibilities[6 * v + 3] = static_cast<float>(cell_v - base_v);
    input.visibilities[6 * v + 4] = data.values[v].real();
    input.visibilities[6 * v + 5] = data.values[v].imag();
  }
  const mx::metal::DeviceInfo info = mx::metal::deviceInfo();
  if (!info.available) {
    std::printf("metal_image status=SKIP reason=no-metal-device\n");
    return 0;
  }
  double best_metal = 1e30;
  std::vector<float> gpu_grid;
  for (int r = 0; r < repeat; ++r) {
    const mx::metal::GridAccumResult result = mx::metal::gridAccumulate(input);
    best_metal = std::min(best_metal, result.gpu_seconds);
    gpu_grid = result.grid;
  }

  // ---- roll to ducc0's DC-at-0 frame ----
  std::vector<float> rolled(gpu_grid.size());
  for (std::size_t i = 0; i < nu_metal; ++i) {
    const std::size_t si = (i + nu_metal / 2) % nu_metal;
    for (std::size_t j = 0; j < nu_metal; ++j) {
      const std::size_t sj = (j + nu_metal / 2) % nu_metal;
      rolled[2 * (i * nu_metal + j) + 0] = gpu_grid[2 * (si * nu_metal + sj) + 0];
      rolled[2 * (i * nu_metal + j) + 1] = gpu_grid[2 * (si * nu_metal + sj) + 1];
    }
  }

  // ---- ducc0's forward chain on that grid ----
  const std::size_t nv = nu_metal;
  // vlim is a band on the METAL grid, so the cutoff must be in metal cells.
  // ducc0's formula gives ducc0-cells; the metal grid has nu_metal/nu times
  // more cells per wavelength, and using ducc0's count here cuts the outermost
  // kernel tails (they reach ~0.4 cells past vlim).
  const double vmax_metal_cells =
      data.v_max_lambda * (static_cast<double>(nv) / static_cast<double>(nu));
  std::size_t vlim = std::min(
      nv / 2, static_cast<std::size_t>(vmax_metal_cells +
                                       0.5 * static_cast<double>(kernel->support()) + 1.0));
  bool uv_side_fast = true;
  const std::size_t vlim2 = (image_size + 1) / 2 + (kernel->support() + 1) / 2;
  if (vlim2 < vlim) {
    vlim = vlim2;
    uv_side_fast = false;
  }
  if (const char* full = std::getenv("MX_METAL_DEBUG_FULLFFT")) {
    if (full[0] != '\0' && full[0] != '0') vlim = nv / 2;
  }
  const ducc0::cmav<std::complex<float>, 2> grid_cmav(
      reinterpret_cast<const std::complex<float>*>(rolled.data()), {nu_metal, nv});
  ducc0::vmav<float, 2> hartley({nu_metal, nv});
  ducc0::detail_gridder::complex2hartley(grid_cmav, hartley, nthreads);
  ducc0::detail_gridder::hartley2_2D(hartley, vlim, uv_side_fast, nthreads);

  // ducc0 samples its correction at 1/nu (its own grid); the Metal grid is a
  // padded container for the same discretisation, so use 1/nu here as well.
  // 1/nu_metal puts a ~0.6% scale error into the correction that reads as a
  // few-% edge-dominated image mismatch with an exact peak.
  const std::vector<double> cfu = kernel->corfunc(image_size / 2 + 1, 1.0 / static_cast<double>(nu), 1);
  const std::vector<double> cfv = kernel->corfunc(image_size / 2 + 1, 1.0 / static_cast<double>(nu), 1);
  std::vector<float> image_mine(image_size * image_size);
  for (std::size_t i = 0; i < image_size; ++i) {
    const int icfu = std::abs(static_cast<int>(image_size / 2) - static_cast<int>(i));
    std::size_t i2 = nu_metal - image_size / 2 + i;
    if (i2 >= nu_metal) i2 -= nu_metal;
    for (std::size_t j = 0; j < image_size; ++j) {
      const int icfv = std::abs(static_cast<int>(image_size / 2) - static_cast<int>(j));
      std::size_t j2 = nv - image_size / 2 + j;
      if (j2 >= nv) j2 -= nv;
      image_mine[i * image_size + j] =
          static_cast<float>(hartley(i2, j2) * cfu[icfu] * cfv[icfv]);
    }
  }

  // ---- reference: ducc0's own 2D inversion ----
  std::vector<float> reference_image(image_size * image_size);
  double best_reference = 1e30;
  {
    std::vector<double> uvw(3 * data.rows(), 0.0);
    for (std::size_t v = 0; v < data.rows(); ++v) {
      // ducc0 scales uvws by frequency/c itself; with f = 1 Hz, u_m = u_lambda*c.
      uvw[3 * v + 0] = data.u_lambda[v] * kSpeedOfLight;
      uvw[3 * v + 1] = data.v_lambda[v] * kSpeedOfLight;
      uvw[3 * v + 2] = 0.0;
    }
    const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {data.rows(), 3});
    const ducc0::cmav<std::complex<float>, 1> ms_ma(data.values.data(), {data.rows()});
    // Use ms2dirty_bda, not ms2dirty: the plain entry point bus-errors on this
    // shape here (it dereferences 2-D weight/mask views we do not have), and with
    // one frequency per row the bda path cannot average anything - freqlist_id is
    // uniform and each row names its own single frequency - so it is the same
    // transform.
    const ducc0::cmav<size_t, 1> freqlist_id = ducc0::cmav<size_t, 1>::build_uniform({data.rows()}, 0);
    const ducc0::cmav<size_t, 1> freqlist_nfreqs = ducc0::cmav<size_t, 1>::build_uniform({1}, 1);
    const std::vector<double> single_frequency(1, 1.0);
    const ducc0::cmav<double, 1> freqlist_freqs(single_frequency.data(), {1});
    const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
    const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
    ducc0::vmav<float, 2> dirty({image_size, image_size});
    for (int r = 0; r < repeat; ++r) {
      const auto begin = std::chrono::steady_clock::now();
      ducc0::detail_gridder::ms2dirty_bda<float, float>(
          uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, ms_ma, weight_ma, mask_ma,
          pixel_size, pixel_size, epsilon, /*do_wgridding=*/false, nthreads, dirty, 0, false,
          false, false, false, 1.1, 2.0, 0.0, 0.0, false);
      const auto end = std::chrono::steady_clock::now();
      best_reference =
          std::min(best_reference, std::chrono::duration<double>(end - begin).count());
    }
    for (std::size_t i = 0; i < image_size * image_size; ++i) reference_image[i] = dirty.raw(i);
  }

  // ---- compare ----
  double max_ref = 0.0, max_mine = 0.0, max_diff = 0.0, sum_sq = 0.0;
  std::size_t argmax_idx = 0;
  for (std::size_t i = 0; i < image_mine.size(); ++i) {
    max_ref = std::max(max_ref, std::fabs(static_cast<double>(reference_image[i])));
    max_mine = std::max(max_mine, std::fabs(static_cast<double>(image_mine[i])));
    const double diff = static_cast<double>(image_mine[i]) - static_cast<double>(reference_image[i]);
    if (std::fabs(diff) > max_diff) {
      max_diff = std::fabs(diff);
      argmax_idx = i;
    }
    sum_sq += diff * diff;
  }
  std::fprintf(stderr, "[probe] argmax idx=%zu (i=%zu j=%zu) mine=%.6g ref=%.6g\n", argmax_idx,
               argmax_idx / image_size, argmax_idx % image_size, image_mine[argmax_idx],
               reference_image[argmax_idx]);
  {
    // A whole-cell error in the grid frame rolls shows up as a one-pixel shift
    // of the image: peak unchanged, differences tracking the gradient. Try the
    // neighbours before believing the residual is a kernel problem.
    for (int di = -1; di <= 1; ++di) {
      for (int dj = -1; dj <= 1; ++dj) {
        double m = 0.0;
        std::size_t n = 0;
        for (std::size_t i = 0; i < image_size; ++i) {
          const long si = static_cast<long>(i) + di;
          if (si < 0 || si >= static_cast<long>(image_size)) continue;
          for (std::size_t j = 0; j < image_size; ++j) {
            const long sj = static_cast<long>(j) + dj;
            if (sj < 0 || sj >= static_cast<long>(image_size)) continue;
            m = std::max(m, std::fabs(static_cast<double>(image_mine[i * image_size + j]) -
                                     static_cast<double>(reference_image[si * image_size + sj])));
            ++n;
          }
        }
        std::printf("shift di=%d dj=%d rel_max=%.4g\n", di, dj, max_ref > 0 ? m / max_ref : 0.0);
      }
    }
  }
  const double rel = max_ref > 0 ? max_diff / max_ref : 0.0;
  const double rms =
      max_ref > 0 ? std::sqrt(sum_sq / static_cast<double>(image_mine.size())) / max_ref : 0.0;
  // The two grids differ in padding (nu vs nu_metal) and in placement rounding in
  // the last bits, so this is a float32-level agreement test, not bit equality.
  constexpr double kTolerance = 1.0e-3;
  std::printf("metal_image rows=%zu image=%zu vlim=%zu metal_ms=%.2f ducc0_ms=%.1f peak mine=%.6g "
              "ref=%.6g rel_max=%.3g rel_rms=%.3g tolerance=%.0e status=%s\n",
              data.rows(), image_size, vlim, best_metal * 1e3, best_reference * 1e3, max_mine,
              max_ref, rel, rms, kTolerance, rel <= kTolerance ? "PASS" : "FAIL");
  return rel <= kTolerance ? 0 : 1;
}
