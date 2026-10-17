// SPDX-License-Identifier: LGPL-3.0-only
// Copyright (C) 2026 Peijin Zhang
// Contains code from radler, Copyright (C) ASTRON (Netherlands Institute for
// Radio Astronomy), LGPL-3.0-only.
// Bitwise check and timing of radler's peak_finder::Simple (with the per-row
// maximum pre-pass) against the original scalar loop.
//
//   c++ -std=c++20 -O3 -I work/radler/cpp -I work/aocommon/include \
//       bench/micro/peak_simple.cpp work/radler/cpp/math/peak_finder.cc \
//       -o bench/micro/bin/peak_simple

#include "math/peak_finder.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <limits>
#include <random>
#include <vector>

namespace reference {

float Simple(const float* image, size_t width, size_t height, size_t& x, size_t& y,
             bool allow_negative_components, size_t start_y, size_t end_y,
             size_t horizontal_border, size_t vertical_border) {
  float peakMax = std::numeric_limits<float>::min();
  size_t peakIndex = width * height;
  size_t xiStart = horizontal_border, xiEnd = width - horizontal_border;
  size_t yiStart = std::max(start_y, vertical_border),
         yiEnd = std::min(end_y, height - vertical_border);
  if (xiEnd < xiStart) xiEnd = xiStart;
  if (yiEnd < yiStart) yiEnd = yiStart;
  for (size_t yi = yiStart; yi != yiEnd; ++yi) {
    size_t index = yi * width + xiStart;
    for (size_t xi = xiStart; xi != xiEnd; ++xi) {
      float value = image[index];
      if (allow_negative_components) value = std::fabs(value);
      if (value > peakMax) {
        peakIndex = index;
        peakMax = std::fabs(value);
      }
      ++index;
    }
  }
  if (peakIndex == width * height) {
    x = width;
    y = height;
    return std::numeric_limits<float>::quiet_NaN();
  }
  x = peakIndex % width;
  y = peakIndex / width;
  return image[x + y * width];
}

}  // namespace reference

int main() {
  std::mt19937 rng(42);
  std::normal_distribution<float> normal(0.0f, 1.0f);
  size_t checks = 0, failures = 0;
  for (size_t trial = 0; trial != 400; ++trial) {
    const size_t width = 1 + rng() % 300, height = 1 + rng() % 200;
    std::vector<float> image(width * height);
    for (float& v : image) v = normal(rng);
    if (trial % 4 == 1)
      for (size_t i = 0; i < image.size(); i += 7) image[i] = std::round(image[i]);
    if (trial % 4 == 2)
      for (size_t i = 0; i < image.size(); i += 13)
        image[i] = std::numeric_limits<float>::quiet_NaN();
    if (trial % 4 == 3)
      for (float& v : image) v = -std::fabs(v);
    for (bool allow_negative : {false, true}) {
      const size_t hb = rng() % (width / 2 + 1), vb = rng() % (height / 2 + 1);
      const size_t start_y = rng() % (height + 1), end_y = start_y + rng() % (height + 1);
      size_t rx, ry, nx, ny;
      const float r = reference::Simple(image.data(), width, height, rx, ry, allow_negative,
                                        start_y, end_y, hb, vb);
      const auto n = radler::math::peak_finder::Simple(image.data(), width, height, nx, ny,
                                                      allow_negative, start_y, end_y, hb, vb);
      const bool same = rx == nx && ry == ny && (std::isnan(r) ? !n : (n && *n == r));
      ++checks;
      if (!same) ++failures;
    }
  }
  std::printf("checks %zu failures %zu\n", checks, failures);

  const size_t size = 2048;
  std::vector<float> image(size * size);
  for (float& v : image) v = normal(rng);
  for (bool allow_negative : {true, false}) {
    size_t x, y;
    auto time = [&](auto&& f) {
      double best = 1e9;
      for (int rep = 0; rep != 20; ++rep) {
        const auto t0 = std::chrono::steady_clock::now();
        f();
        best = std::min(best, std::chrono::duration<double, std::milli>(
                                  std::chrono::steady_clock::now() - t0)
                                  .count());
      }
      return best;
    };
    const double t_ref = time([&] {
      reference::Simple(image.data(), size, size, x, y, allow_negative, 0, size, 0, 0);
    });
    const double t_new = time([&] {
      radler::math::peak_finder::Simple(image.data(), size, size, x, y, allow_negative, 0,
                                        size, 0, 0);
    });
    std::printf("2048^2 allow_negative=%d  reference %.3f ms  new %.3f ms  (%.1fx)\n",
                allow_negative, t_ref, t_new, t_ref / t_new);
  }
  return failures != 0;
}
