// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// Image-level check of the Metal gridding: grid on the GPU, then push that grid
// through ducc0's own forward chain, and compare the resulting dirty image with
// ducc0::ms2dirty_bda on identical data. This is the piece that makes wiring
// the GPU gridder into wsclean's WGridder possible: the probe only ever
// compared grids, and an image needs the padded grid, the Hartley transform and
// ducc0's kernel correction.
//
// The chain reproduced here is exactly ducc0's do_wgridding=false path:
//
//   grid (nu x nv, padded)  ->  complex2hartley  ->  hartley2_2D  ->  extract
//   the inner nxdirty x nydirty cells with cfu/cfv = krn->corfunc(n/2+1, 1/nu)
//
// ducc0's functions are called directly (complex2hartley, hartley2_2D,
// PolynomialKernel::corfunc); nothing about the kernel or the correction is
// reimplemented except the cell extraction, which is four lines of their
// grid2dirty_post. Note that x2dirty's non-wgridding branch does NOT call
// apply_global_corrections - that only runs for w-gridding - so the 2D chain
// needs no w-screen and no corfunc(0) factor.
//
// Grid geometry: one wavelength per cell on both sides (pixsize = 1/nu_ref), so
// the only difference is the padding (ducc0 picks nu_ref from its own size
// heuristic; the Metal kernel needs a multiple of the 32-cell tile, so it uses
// the next multiple up). The extraction takes the same inner window, so both
// images cover the same patch of sky.
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
#include <fstream>
#include <random>
#include <string>
#include <vector>

#include "uvw_file.h"  // shared real-data reader (work/wsclean/metal)

namespace {

constexpr double kSpeedOfLight = 299792458.0;

// The kernel coefficients written by scripts/metal_kernel_coeffs.sh.
struct KernelCoefficients {
  std::size_t support = 0;
  std::size_t degree = 0;
  std::vector<float> values;
};

KernelCoefficients loadKernel(const std::string& path) {
  std::ifstream in(path);
  if (!in) {
    std::fprintf(stderr, "cannot open %s\n", path.c_str());
    std::exit(2);
  }
  KernelCoefficients kernel;
  std::string line;
  while (std::getline(in, line)) {
    if (line.rfind("support", 0) == 0) kernel.support = std::strtoul(line.c_str() + 8, nullptr, 10);
    if (line.rfind("degree", 0) == 0) kernel.degree = std::strtoul(line.c_str() + 7, nullptr, 10);
    if (line.rfind("interval", 0) == 0) {
      const char* p = line.c_str() + 9;
      char* end = nullptr;
      std::strtol(p, &end, 10);  // interval index, in order
      p = end;
      for (std::size_t i = 0; i <= kernel.degree; ++i) {
        const double value = std::strtod(p, &end);
        if (end == p) break;
        kernel.values.push_back(static_cast<float>(value));
        p = end;
      }
    }
  }
  if (kernel.support == 0 || kernel.degree == 0 || kernel.values.empty()) {
    std::fprintf(stderr, "kernel file %s is incomplete\n", path.c_str());
    std::exit(2);
  }
  return kernel;
}

struct Data {
  std::vector<float> visibilities;  // u, v, re, im per row, uv in CELLS
  std::size_t rows = 0;
  double v_max_lambda = 0.0;
};

Data makeSynthetic(std::size_t nvis, std::size_t cells) {
  std::mt19937_64 random(20261018);  // same generator as the probe and the CPU tool
  std::uniform_real_distribution<float> uv(-0.45f * static_cast<float>(cells),
                                           0.45f * static_cast<float>(cells));
  std::normal_distribution<float> flux(1.0f, 0.25f);
  Data data;
  data.visibilities.resize(4 * nvis);
  for (std::size_t v = 0; v < nvis; ++v) {
    data.visibilities[4 * v + 0] = uv(random);
    data.visibilities[4 * v + 1] = uv(random);
    data.visibilities[4 * v + 2] = flux(random);
    data.visibilities[4 * v + 3] = flux(random) * 0.5f;
    data.v_max_lambda = std::max(
        {data.v_max_lambda, std::fabs(static_cast<double>(data.visibilities[4 * v + 0])),
         std::fabs(static_cast<double>(data.visibilities[4 * v + 1]))});
  }
  data.rows = nvis;
  return data;
}

Data loadReal(const std::string& path, double frequency, double lambda_per_cell) {
  const mxbench::RealVisibilitySet set = mxbench::LoadUvwFile(path);
  Data data;
  data.visibilities.resize(4 * set.rows.size());
  const double to_cells = frequency / kSpeedOfLight / lambda_per_cell;
  for (std::size_t v = 0; v < set.rows.size(); ++v) {
    const mxbench::RealVisibility& row = set.rows[v];
    data.visibilities[4 * v + 0] = static_cast<float>(row.u_m * to_cells);
    data.visibilities[4 * v + 1] = static_cast<float>(row.v_m * to_cells);
    data.visibilities[4 * v + 2] = row.re;
    data.visibilities[4 * v + 3] = row.im;
    data.v_max_lambda = std::max(
        {data.v_max_lambda, std::fabs(static_cast<double>(data.visibilities[4 * v + 0])),
         std::fabs(static_cast<double>(data.visibilities[4 * v + 1]))});
  }
  data.rows = set.rows.size();
  return data;
}

}  // namespace

int main(int argc, char** argv) {
  std::size_t nvis = 200000;
  std::size_t image_size = 1024;
  std::string coefficients_path;
  std::string uvw_file;
  double frequency = 0.0;
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
    } else if (argument == "--size") {
      image_size = std::strtoull(value("--size"), nullptr, 10);
    } else if (argument == "--kernel-coeffs") {
      coefficients_path = value("--kernel-coeffs");
    } else if (argument == "--uvw-file") {
      uvw_file = value("--uvw-file");
    } else if (argument == "--freq") {
      frequency = std::strtod(value("--freq"), nullptr);
    } else if (argument == "--repeat") {
      repeat = std::max(1, std::atoi(value("--repeat")));
    } else {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 2;
    }
  }
  if (coefficients_path.empty()) {
    std::fprintf(stderr, "need --kernel-coeffs (scripts/metal_kernel_coeffs.sh)\n");
    return 2;
  }
  const KernelCoefficients coefficients = loadKernel(coefficients_path);

  // ducc0's own grid size for this image, and one wavelength per cell.
  constexpr double kOfactor = 2.0;
  const std::size_t nu_ref =
      2 * ducc0::good_size_complex(static_cast<std::size_t>(image_size * kOfactor * 0.5) + 1);
  const double pixel_size = 1.0 / static_cast<double>(nu_ref);
  // The Metal kernel works on whole 32-cell tiles, so its padded grid is the
  // next multiple of 32 at or above ducc0's.
  const std::size_t nu_metal = ((nu_ref + 31) / 32) * 32;
  std::printf("image=%zu nu_ref=%zu nu_metal=%zu support=%zu degree=%zu\n", image_size, nu_ref,
              nu_metal, coefficients.support, coefficients.degree);

  const Data data = uvw_file.empty() ? makeSynthetic(nvis, nu_ref / 2)
                                     : loadReal(uvw_file, frequency, 1.0);
  std::printf("rows=%zu v_max=%.1f lambda rows\n", data.rows, data.v_max_lambda);

  const auto candidates =
      ducc0::getAvailableKernels<float>(1.0e-4, 2, 1.1, 2.0);
  if (candidates.empty()) {
    std::fprintf(stderr, "ducc0 returned no kernel candidates\n");
    return 2;
  }
  // ducc0 does not pick the smallest support: getNuNv() minimises
  // fftcost(nu,nv) + gridcost(nvis,supp), so reproduce that cost model here.
  // Picking by support alone selects a different kernel (W=6 instead of W=8 for
  // this size), and since the grid correction comes from the same kernel the
  // whole image then lands on a different scale - a ~11% uniform offset that
  // looks like a missing factor but is a different kernel.
  constexpr double kNrefFft = 2048.0, kCostRefFft = 0.0693;
  constexpr std::size_t kSimdWidth = 4;  // float, NEON
  const double log_term_ref = std::log(kNrefFft * kNrefFft);
  std::size_t best = candidates.front();
  double best_cost = 1e300;
  for (const std::size_t index : candidates) {
    const ducc0::KernelParams &params = ducc0::getKernel(index);
    // Only ofactor ~2: that is the grid size the reference actually works with
    // here (nu traces back to the ofactor-2 formula), and mixing ofactors would
    // put the two grids on different cell sizes.
    if (std::fabs(params.ofactor - 2.0) > 0.05) continue;
    const std::size_t supp = params.W;
    const std::size_t nvec = (supp + kSimdWidth - 1) / kSimdWidth;
    const std::size_t nu_c = 2 * ducc0::good_size_complex(
                                     static_cast<std::size_t>(image_size * params.ofactor * 0.5) + 1);
    const std::size_t nv_c = nu_c;
    double fft_cost = static_cast<double>(nu_c) / kNrefFft * static_cast<double>(nv_c) / kNrefFft *
                      (std::log(static_cast<double>(nu_c * nv_c)) / log_term_ref) * kCostRefFft;
    double grid_cost = 2.2e-10 * static_cast<double>(data.rows) *
                       static_cast<double>(supp * nvec * kSimdWidth +
                                           (2 * nvec + 1) * (supp + 3) * kSimdWidth);
    grid_cost /= 8.0;  // nthreads
    const double cost = fft_cost + grid_cost;
    if (cost < best_cost) {
      best_cost = cost;
      best = index;
    }
  }
  const ducc0::KernelParams &chosen = ducc0::getKernel(best);
  std::printf("cost_model chose index=%zu W=%zu ofactor=%.3f (cost=%.4g)\n", best, chosen.W,
              chosen.ofactor, best_cost);
  const std::shared_ptr<ducc0::PolynomialKernel> kernel = ducc0::selectKernel(best);
  // Take the coefficients from the selected kernel itself: any W is then fine
  // (the generic poly variant evaluates the support dynamically), and the grid,
  // the correction and the reference all come from one kernel.
  std::vector<float> kernel_values;
  for (const double value : kernel->Coeff()) kernel_values.push_back(static_cast<float>(value));
  std::printf("kernel_coefficients values=%zu support=%zu degree=%zu\n", kernel_values.size(),
              kernel->support(), kernel->degree());

  // ---------------- GPU gridding ----------------
  mx::metal::GridAccumInput input;
  input.grid_size = nu_metal;
  input.support = 6;              // replaced below, once ducc0's kernel is known
  input.kernel_degree = 9;
  input.variant = mx::metal::Variant::kPoly;
  input.visibilities = data.visibilities;
  const mx::metal::DeviceInfo info = mx::metal::deviceInfo();
  if (!info.available) {
    std::printf("metal_image status=SKIP reason=no-metal-device\n");
    return 0;
  }

  double best_metal = 1e30, best_reference = 1e30;
  std::vector<float> gpu_grid, reference_image;
  for (int r = 0; r < repeat; ++r) {
    const mx::metal::GridAccumResult result = mx::metal::gridAccumulate(input);
    best_metal = std::min(best_metal, result.gpu_seconds);
    gpu_grid = result.grid;
  }

  // ---------------- ducc0's forward chain on that grid ----------------
  const std::size_t nu = nu_metal, nv = nu_metal;
  const std::size_t vlim = std::min(
      nv / 2, static_cast<std::size_t>(static_cast<double>(nv) * data.v_max_lambda * pixel_size +
                                       0.5 * static_cast<double>(coefficients.support) + 1.0));
  std::size_t vlim_used = vlim;
  bool uv_side_fast = true;
  const std::size_t vlim2 = (image_size + 1) / 2 + (coefficients.support + 1) / 2;
  if (vlim2 < vlim_used) {
    vlim_used = vlim2;
    uv_side_fast = false;
  }
  std::printf("vlim=%zu uv_side_fast=%s\n", vlim_used, uv_side_fast ? "true" : "false");

  {
    double grid_sum = 0.0;
    for (float value : gpu_grid) grid_sum += value;
    std::printf("metal_grid cells=%zu sum=%.6g\n", gpu_grid.size() / 2, grid_sum);
  }
  // Frame convention: the Metal kernels place the origin (u = 0) at the centre
  // of the grid, while ducc0's getpix() uses frac(u*pixsize)*nu, i.e. DC at
  // index 0 - and hartley2_2D's band logic (only [0,vlim) and [nv-vlim,nv) are
  // transformed) depends on that. Roll the Metal grid by half a grid so both
  // sides use ducc0's frame.
  std::vector<float> rolled(gpu_grid.size());
  for (std::size_t i = 0; i < nu; ++i) {
    const std::size_t si = (i + nu / 2) % nu;
    for (std::size_t j = 0; j < nv; ++j) {
      const std::size_t sj = (j + nv / 2) % nv;
      rolled[2 * (i * nv + j) + 0] = gpu_grid[2 * (si * nv + sj) + 0];
      rolled[2 * (i * nv + j) + 1] = gpu_grid[2 * (si * nv + sj) + 1];
    }
  }
  ducc0::cmav<std::complex<float>, 2> grid_cmav(
      reinterpret_cast<const std::complex<float>*>(rolled.data()), {nu, nv});
  ducc0::vmav<float, 2> hartley({nu, nv});
  ducc0::detail_gridder::complex2hartley(grid_cmav, hartley, 1);
  ducc0::detail_gridder::hartley2_2D(hartley, vlim_used, uv_side_fast, 8);
  {
    double hartley_sum = 0.0, hartley_abs = 0.0;
    for (std::size_t i = 0; i < nu * nv; ++i) {
      hartley_sum += hartley.raw(i);
      hartley_abs += std::fabs(hartley.raw(i));
    }
    std::printf("hartley sum=%.6g abs_sum=%.6g\n", hartley_sum, hartley_abs);
  }

  // The kernel ducc0 would have used for this accuracy (its own selection), then
  // its correction function on our grid.
  input.support = kernel->support();
  input.kernel_degree = kernel->degree();
  input.kernel_coefficients = kernel_values;
  input.variant = mx::metal::Variant::kPoly;
  const std::size_t supp = kernel->support();
  const std::vector<double> cfu = kernel->corfunc(image_size / 2 + 1, 1.0 / static_cast<double>(nu), 1);
  const std::vector<double> cfv = kernel->corfunc(image_size / 2 + 1, 1.0 / static_cast<double>(nv), 1);
  std::printf("ducc0_kernel support=%zu ofactor=%.1f\n", supp,
              static_cast<double>(nu) / static_cast<double>(image_size));

  std::printf("probe hartley(1568,1568)=%.6g hartley(0,0)=%.6g hartley(1000,1000)=%.6g "
              "cfu[0]=%.6g cfu[1]=%.6g cfu[512]=%.6g\n",
              hartley(1568, 1568), hartley(0, 0), hartley(1000, 1000), cfu[0], cfu[1],
              cfu[image_size / 2]);
  std::vector<float> image_mine(image_size * image_size);
  double sum = 0.0;
  for (std::size_t i = 0; i < image_size; ++i) {
    const int icfu = std::abs(static_cast<int>(image_size / 2) - static_cast<int>(i));
    std::size_t i2 = nu - image_size / 2 + i;
    if (i2 >= nu) i2 -= nu;
    for (std::size_t j = 0; j < image_size; ++j) {
      const int icfv = std::abs(static_cast<int>(image_size / 2) - static_cast<int>(j));
      std::size_t j2 = nv - image_size / 2 + j;
      if (j2 >= nv) j2 -= nv;
      const float value = static_cast<float>(hartley(i2, j2) * cfu[icfu] * cfv[icfv]);
      image_mine[i * image_size + j] = value;
      sum += value;
    }
  }

  // ---------------- reference: ducc0's own 2D inversion ----------------
  {
    std::vector<double> uvw(3 * data.rows, 0.0);
    std::vector<std::complex<float>> ms(data.rows);
    for (std::size_t v = 0; v < data.rows; ++v) {
      // uvws are metres on ducc0's side; the data are stored in cells of one
      // wavelength, so metres = cells * c / f with f chosen as 1 Hz here.
      uvw[3 * v + 0] = data.visibilities[4 * v + 0];
      uvw[3 * v + 1] = data.visibilities[4 * v + 1];
      uvw[3 * v + 2] = 0.0;
      ms[v] = std::complex<float>(data.visibilities[4 * v + 2], data.visibilities[4 * v + 3]);
    }
    const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {data.rows, 3});
    const ducc0::cmav<size_t, 1> freqlist_id =
        ducc0::cmav<size_t, 1>::build_uniform({data.rows}, 0);
    const std::vector<double> frequencies(1, kSpeedOfLight);  // 1 Hz * c => u_lambda = u
    const ducc0::cmav<size_t, 1> freqlist_nfreqs = ducc0::cmav<size_t, 1>::build_uniform({1}, 1);
    const ducc0::cmav<double, 1> freqlist_freqs(frequencies.data(), {1});
    const ducc0::cmav<std::complex<float>, 1> ms_ma(ms.data(), {data.rows});
    const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
    const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
    ducc0::vmav<float, 2> dirty({image_size, image_size});
    for (int r = 0; r < repeat; ++r) {
      const auto begin = std::chrono::steady_clock::now();
      ducc0::detail_gridder::ms2dirty_bda<float, float>(
          uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, ms_ma, weight_ma, mask_ma,
          pixel_size, pixel_size, 1.0e-4, /*do_wgridding=*/false, 8, dirty, 0, false, true, false,
          false, 1.1, 2.0, 0.0, 0.0, false);
      const auto end = std::chrono::steady_clock::now();
      best_reference = std::min(best_reference, std::chrono::duration<double>(end - begin).count());
    }
    reference_image.resize(image_size * image_size);
    for (std::size_t i = 0; i < image_size * image_size; ++i) reference_image[i] = dirty.raw(i);
  }

  // ---------------- compare ----------------
  double max_ref = 0.0, max_diff = 0.0, sum_abs_diff = 0.0;
  for (std::size_t i = 0; i < image_mine.size(); ++i) {
    max_ref = std::max(max_ref, std::fabs(static_cast<double>(reference_image[i])));
  }
  for (std::size_t i = 0; i < image_mine.size(); ++i) {
    const double diff = std::fabs(static_cast<double>(image_mine[i]) -
                                  static_cast<double>(reference_image[i]));
    max_diff = std::max(max_diff, diff);
    sum_abs_diff += diff;
  }
  double max_mine = 0.0;
  for (float value : image_mine) max_mine = std::max(max_mine, std::fabs(static_cast<double>(value)));
  std::printf("peak mine=%.6g reference=%.6g\n", max_mine, max_ref);
  {
    // Is the difference a pure scale (a missing factor) or a shape difference
    // (a different kernel/correction)? Report ratios at the strongest pixels.
    double sum_mine = 0.0, sum_ref = 0.0;
    std::vector<std::pair<double, std::size_t>> strongest;
    for (std::size_t i = 0; i < image_mine.size(); ++i) {
      sum_mine += image_mine[i];
      sum_ref += reference_image[i];
      if (std::fabs(reference_image[i]) > 0.2 * max_ref) strongest.emplace_back(
          std::fabs(reference_image[i]), i);
    }
    std::sort(strongest.rbegin(), strongest.rend());
    std::printf("ratio sum=%.5f  strongest-pixel ratios:", sum_ref != 0 ? sum_mine / sum_ref : 0.0);
    for (std::size_t k = 0; k < std::min<std::size_t>(6, strongest.size()); ++k) {
      const std::size_t i = strongest[k].second;
      std::printf(" %.5f", reference_image[i] != 0 ? image_mine[i] / reference_image[i] : 0.0);
    }
    std::printf("\n");
  }
  const double rel = max_ref > 0 ? max_diff / max_ref : 0.0;
  const double rms = max_ref > 0
                         ? std::sqrt(sum_abs_diff / static_cast<double>(image_mine.size())) / max_ref
                         : 0.0;
  constexpr double kTolerance = 1.0e-4;  // padding differs by 22 cells; placement/weights must agree
  std::printf("metal_image rows=%zu image=%zu metal_ms=%.2f ducc0_ms=%.1f rel_max=%.3g "
              "rel_rms=%.3g tolerance=%.0e sum=%.6g status=%s\n",
              data.rows, image_size, best_metal * 1e3, best_reference * 1e3, rel, rms,
              kTolerance, sum, rel <= kTolerance ? "PASS" : "FAIL");
  return rel <= kTolerance ? 0 : 1;
}
