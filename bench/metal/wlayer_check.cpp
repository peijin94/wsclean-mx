// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// Fast check of the Metal w-layer inversion against ducc0's own w-gridded
// inversion (ms2dirty_bda with do_wgridding=true) on identical synthetic data.
// Smaller and quicker than ducc0_image_check.cpp: its job is to bisect the
// w-path, so it also reports the plain ratio of the two images and can run the
// 2-D path on the same data for comparison.
//
// Build/run: scripts/metal_wlayer_check.sh [--nvis N] [--size N] [--w-max LAMBDA]

#include "metal/metalinversion.h"

#include "ducc0/math/gridding_kernel.h"
#include "ducc0/wgridder/wgridder_impl.h"

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

constexpr double kSpeedOfLight = 299792458.0;

struct Data {
  std::vector<double> uvw;                  // metres, 3 per row
  std::vector<std::complex<float>> values;  // one channel
  double w_max_lambda = 0.0;
  std::size_t rows() const { return values.size(); }
};

Data makeSynthetic(std::size_t nvis, double max_lambda, double w_max_lambda, bool w_positive) {
  std::mt19937_64 random(20261019);
  std::uniform_real_distribution<double> uv(-max_lambda, max_lambda);
  std::uniform_real_distribution<double> w(-w_max_lambda, w_max_lambda);
  std::normal_distribution<double> flux(1.0, 0.25);
  Data data;
  data.uvw.resize(3 * nvis);
  data.values.resize(nvis);
  for (std::size_t v = 0; v < nvis; ++v) {
    const double u = uv(random), vv = uv(random);
    const double ww = w_positive ? std::fabs(w(random)) : w(random);
    data.uvw[3 * v + 0] = u * kSpeedOfLight;  // f = 1 Hz, so u_m = u_lambda * c
    data.uvw[3 * v + 1] = vv * kSpeedOfLight;
    data.uvw[3 * v + 2] = ww * kSpeedOfLight;
    data.values[v] = std::complex<float>(static_cast<float>(flux(random)),
                                         static_cast<float>(flux(random) * 0.5));
    data.w_max_lambda = std::max(data.w_max_lambda, std::fabs(ww));
  }
  return data;
}

void compare(const std::vector<float>& mine, const std::vector<float>& reference,
             const char* label) {
  double max_ref = 0.0, max_mine = 0.0, max_diff = 0.0, sum_sq = 0.0, sum_ref = 0.0;
  for (std::size_t i = 0; i < mine.size(); ++i) {
    max_ref = std::max(max_ref, std::fabs(static_cast<double>(reference[i])));
    max_mine = std::max(max_mine, std::fabs(static_cast<double>(mine[i])));
    sum_ref += static_cast<double>(reference[i]);
    const double diff = static_cast<double>(mine[i]) - static_cast<double>(reference[i]);
    max_diff = std::max(max_diff, std::fabs(diff));
    sum_sq += diff * diff;
  }
  const double rms = std::sqrt(sum_sq / static_cast<double>(mine.size()));
  double sum_mine = 0.0;
  for (const float value : mine) sum_mine += value;
  std::printf("%s peak mine=%.6g ref=%.6g ratio=%.6f | sum mine=%.6g ref=%.6g ratio=%.6f | "
              "diff max=%.4g rms=%.4g | rel_max=%.4g rel_rms=%.4g\n",
              label, max_mine, max_ref, max_ref != 0.0 ? max_mine / max_ref : 0.0, sum_mine,
              sum_ref, sum_ref != 0.0 ? sum_mine / sum_ref : 0.0, max_diff, rms,
              max_ref != 0.0 ? max_diff / max_ref : 0.0,
              max_ref != 0.0 ? rms / max_ref : 0.0);
}

}  // namespace

int main(int argc, char** argv) {
  std::size_t nvis = 20000;
  std::size_t image_size = 256;
  double w_max_lambda = 50.0;
  bool two_d = false;
  double pixel_scale = 1.0;
  double uv_frac = 0.45;
  bool w_positive = false;
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
    } else if (argument == "--w-max") {
      w_max_lambda = std::strtod(value("--w-max"), nullptr);
    } else if (argument == "--w-positive") {
      w_positive = true;
    } else if (argument == "--uv-frac") {
      uv_frac = std::strtod(value("--uv-frac"), nullptr);
    } else if (argument == "--pixel-scale") {
      pixel_scale = std::strtod(value("--pixel-scale"), nullptr);
    } else if (argument == "--2d") {
      two_d = true;
    } else {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 2;
    }
  }

  // pixel_scale > 1 narrows the field (finer pixels), which is needed to sample
  // the fringes properly: with pixsize = 1/N and |u| up to 0.45N the fringe
  // period is ~2 pixels, so a 0.5% grid-cell difference alone destroys the
  // pattern and the comparison measures sampling, not the w algebra.
  const double pixel_size = pixel_scale / static_cast<double>(image_size);
  // uv range must respect the uv extent of the chosen pixel size (1/pixsize),
  // otherwise the visibilities fall outside the grid.
  const double max_lambda = uv_frac / pixel_size;
  const Data data = makeSynthetic(nvis, max_lambda, w_max_lambda, w_positive);
  // pixsize = 1/image_size: one wavelength per pixel, which makes the uv cell
  // exactly one wavelength and keeps the comparison free of scale choices.

  mx::metal::InversionInput input;
  input.n_rows = data.rows();
  input.uvws = data.uvw.data();
  const double frequency = 1.0;
  input.frequencies = &frequency;
  input.n_channels = 1;
  input.ms = data.values.data();
  input.pixel_size_x = pixel_size;
  input.pixel_size_y = pixel_size;
  input.epsilon = 1.0e-4;
  input.n_threads = 8;
  input.flip_v = false;  // ducc0's default; the wsclean call site uses true
  input.image_width = image_size;
  input.image_height = image_size;
  input.w_gridding = !two_d;

  std::vector<float> mine(image_size * image_size);
  const bool ok = mx::metal::inversion(input, mine.data());
  std::printf("wlayer_check rows=%zu size=%zu w_max=%.3g lambda w_gridding=%d image=%s\n",
              data.rows(), image_size, data.w_max_lambda, input.w_gridding ? 1 : 0,
              ok ? "computed" : "REFUSED");

  std::vector<float> reference(image_size * image_size);
  {
    std::vector<double> uvw(data.uvw);
    const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {data.rows(), 3});
    const ducc0::cmav<size_t, 1> freqlist_id =
        ducc0::cmav<size_t, 1>::build_uniform({data.rows()}, 0);
    const ducc0::cmav<size_t, 1> freqlist_nfreqs = ducc0::cmav<size_t, 1>::build_uniform({1}, 1);
    const std::vector<double> freqs(1, frequency);
    const ducc0::cmav<double, 1> freqlist_freqs(freqs.data(), {1});
    const ducc0::cmav<std::complex<float>, 1> ms_ma(data.values.data(), {data.rows()});
    const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
    const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
    ducc0::vmav<float, 2> dirty({image_size, image_size});
    ducc0::ms2dirty_bda<float, float>(uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, ms_ma,
                                      weight_ma, mask_ma, pixel_size, pixel_size, 1.0e-4,
                                      /*do_wgridding=*/!two_d, 8, dirty, 0, false, false, false,
                                      false, 1.1, 2.0, 0.0, 0.0, /*allow_nshift=*/true);
    for (std::size_t i = 0; i < image_size * image_size; ++i) reference[i] = dirty.raw(i);
  }
  if (!ok) return 1;
  compare(mine, reference, "vs ducc0 w-gridded:");

  // Sanity: what does ducc0's own w-gridded path give against its 2-D path on
  // the same data? (At w = 0 they must agree; at w != 0 they must not.)
  {
    std::vector<double> uvw(data.uvw);
    const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {data.rows(), 3});
    const ducc0::cmav<size_t, 1> freqlist_id =
        ducc0::cmav<size_t, 1>::build_uniform({data.rows()}, 0);
    const ducc0::cmav<size_t, 1> freqlist_nfreqs = ducc0::cmav<size_t, 1>::build_uniform({1}, 1);
    const std::vector<double> freqs(1, frequency);
    const ducc0::cmav<double, 1> freqlist_freqs(freqs.data(), {1});
    const ducc0::cmav<std::complex<float>, 1> ms_ma(data.values.data(), {data.rows()});
    const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
    const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
    ducc0::vmav<float, 2> dirty({image_size, image_size});
    ducc0::ms2dirty_bda<float, float>(uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs, ms_ma,
                                      weight_ma, mask_ma, pixel_size, pixel_size, 1.0e-4,
                                      /*do_wgridding=*/!input.w_gridding, 8, dirty, 0, false,
                                      false, false, false, 1.1, 2.0, 0.0, 0.0, /*allow_nshift=*/true);
    std::vector<float> other(image_size * image_size);
    for (std::size_t i = 0; i < image_size * image_size; ++i) other[i] = dirty.raw(i);
    compare(other, reference, "ducc0 other path vs this reference:");
  }
  return 0;
}
