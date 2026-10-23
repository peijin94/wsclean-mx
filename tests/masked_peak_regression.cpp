// SPDX-License-Identifier: GPL-3.0-or-later
// Independent sequential oracle for masked and weighted binary32 peak scans.
#include "math/peak_finder.h"

#include <aocommon/uvector.h>

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace pf = radler::math::peak_finder;
using Number = aocommon::OptionalNumber<float>;

namespace {
struct Peak {
  Number value;
  size_t x;
  size_t y;
};
size_t checks = 0;
size_t failures = 0;
volatile float benchmark_sink = 0.0f;

void Check(bool condition, const char* label) {
  ++checks;
  if (!condition) {
    ++failures;
    if (failures < 12) std::cerr << "FAIL: " << label << '\n';
  }
}

// Deliberately retain a simple scalar traversal, independent of the optimized
// row/lane reduction. The empty-region guards define the boundary contract.
[[gnu::noinline]] Peak Sequential(const float* image, const bool* mask,
                                  size_t width, size_t height, bool negative,
                                  size_t start_y, size_t end_y, size_t x_border,
                                  size_t y_border) {
  Peak result{{}, width, height};
  if (x_border >= width || y_border >= height) return result;
  const size_t x_end = width - x_border;
  const size_t y_begin = std::max(start_y, y_border);
  const size_t y_end = std::min(end_y, height - y_border);
  if (x_border >= x_end || y_begin >= y_end) return result;
  float best = std::numeric_limits<float>::min();
  for (size_t y = y_begin; y != y_end; ++y) {
    for (size_t x = x_border; x != x_end; ++x) {
      const size_t index = y * width + x;
      const float value = negative ? std::fabs(image[index]) : image[index];
      if (value > best && (!mask || mask[index])) {
        best = std::fabs(value);
        result.x = x;
        result.y = y;
      }
    }
  }
  if (result.y != height) result.value = image[result.y * width + result.x];
  return result;
}

[[gnu::noinline]] Peak Masked(const float* image, const bool* mask,
                              size_t width, size_t height, bool negative,
                              size_t start_y, size_t end_y, size_t x_border,
                              size_t y_border) {
  Peak result;
  result.value =
      pf::FindWithMask(image, width, height, result.x, result.y, negative,
                       start_y, end_y, mask, x_border, y_border);
  return result;
}

bool Same(const Peak& lhs, const Peak& rhs) {
  return bool(lhs.value) == bool(rhs.value) && lhs.x == rhs.x &&
         lhs.y == rhs.y &&
         (!lhs.value || std::bit_cast<uint32_t>(*lhs.value) ==
                            std::bit_cast<uint32_t>(*rhs.value));
}

void ValidCases() {
  std::mt19937 random(93854);
  std::uniform_real_distribution<float> noise(-8.0f, 8.0f);
  const float special[] = {0.0f,
                           -0.0f,
                           std::numeric_limits<float>::denorm_min(),
                           std::numeric_limits<float>::min(),
                           -std::numeric_limits<float>::min(),
                           std::numeric_limits<float>::infinity(),
                           -std::numeric_limits<float>::infinity(),
                           std::numeric_limits<float>::quiet_NaN(),
                           1.0f,
                           -1.0f};
  for (size_t width : {0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 64, 65}) {
    for (size_t height : {0, 1, 3, 17}) {
      const size_t count = width * height;
      std::vector<float> image(std::max(count, size_t{1}));
      std::vector<float> weights(image.size()), products(image.size());
      aocommon::UVector<bool> mask(image.size());
      for (size_t data_case = 0; data_case != 14; ++data_case) {
        for (size_t i = 0; i != count; ++i) {
          image[i] = data_case < 10 ? special[data_case] : noise(random);
          if (data_case == 12) image[i] = float(i);
          if (data_case == 13) image[i] = float(count - i);
          weights[i] = data_case == 10 ? special[i % 10] : noise(random);
          products[i] = image[i] * weights[i];
        }
        const std::vector<float> image_before = image, weights_before = weights;
        for (size_t mask_kind = 0; mask_kind != 4; ++mask_kind) {
          for (size_t i = 0; i != count; ++i) {
            mask[i] = mask_kind == 0 || (mask_kind == 2 && i % 3 != 0) ||
                      (mask_kind == 3 && (i == 0 || i + 1 == count));
          }
          const aocommon::UVector<bool> mask_before = mask;
          for (bool negative : {false, true}) {
            for (size_t border : {size_t{0}, size_t{1}, width / 2, width}) {
              const size_t xb = std::min(border, width);
              const size_t yb = std::min(border, height);
              for (size_t start : {size_t{0}, height / 2, height}) {
                const Peak expected =
                    Sequential(image.data(), mask.data(), width, height,
                               negative, start, height, xb, yb);
                Check(Same(expected,
                           Masked(image.data(), mask.data(), width, height,
                                  negative, start, height, xb, yb)),
                      "masked differential values, position and sentinel");
                for (const bool* selected_mask :
                     {static_cast<const bool*>(nullptr),
                      static_cast<const bool*>(mask.data())}) {
                  const Peak weighted_expected =
                      Sequential(products.data(), selected_mask, width, height,
                                 negative, start, height, xb, yb);
                  Peak weighted;
                  weighted.value = pf::SimpleWeighted(
                      image.data(), weights.data(), width, height, weighted.x,
                      weighted.y, negative, start, height, selected_mask, xb,
                      yb);
                  Check(Same(weighted_expected, weighted),
                        "weighted scan against independent scalar oracle");
                }
              }
            }
          }
          Check(std::memcmp(mask.data(), mask_before.data(),
                            count * sizeof(bool)) == 0,
                "mask immutable");
        }
        Check(std::memcmp(image.data(), image_before.data(),
                          count * sizeof(float)) == 0 &&
                  std::memcmp(weights.data(), weights_before.data(),
                              count * sizeof(float)) == 0,
              "images and weights immutable");
      }
    }
  }
  // Signed ties cross both lane and row boundaries. Strict comparison chooses
  // the first allowed pixel; normal-floor equality is not a candidate.
  std::vector<float> image(66, 0.0f);
  aocommon::UVector<bool> mask(66, true);
  image[7] = -8.0f;
  image[8] = 8.0f;
  image[33] = -8.0f;
  Peak peak = Masked(image.data(), mask.data(), 33, 2, true, 0, 2, 0, 0);
  Check(peak.value && *peak.value == -8.0f && peak.x == 7 && peak.y == 0,
        "first signed tie across lanes");
  mask[7] = false;
  peak = Masked(image.data(), mask.data(), 33, 2, true, 0, 2, 0, 0);
  Check(peak.value && *peak.value == 8.0f && peak.x == 8 && peak.y == 0,
        "masked-out first tie");
  std::fill(image.begin(), image.end(), std::numeric_limits<float>::min());
  peak = Masked(image.data(), mask.data(), 33, 2, true, 0, 2, 0, 0);
  Check(!peak.value && peak.x == 33 && peak.y == 2, "exact normal floor");
  image[32] = std::nextafter(std::numeric_limits<float>::min(), 1.0f);
  image[33] = -image[32];
  peak = Masked(image.data(), mask.data(), 33, 2, true, 0, 2, 0, 0);
  Check(peak.value && *peak.value == image[32] && peak.x == 32 && peak.y == 0,
        "first row-major tie above normal floor");

  // OptionalNumber uses lowest() as its empty sentinel. Preserve that existing
  // collision without losing the selected coordinates or changing signed ties.
  std::fill(image.begin(), image.end(), 0.0f);
  std::fill(mask.begin(), mask.end(), true);
  image[7] = std::numeric_limits<float>::lowest();
  image[8] = std::numeric_limits<float>::max();
  const std::vector<float> weights(image.size(), 1.0f);
  for (bool negative : {false, true}) {
    const size_t expected_x = negative ? 7 : 8;
    Peak expected{{}, expected_x, 0};
    if (!negative) expected.value = std::numeric_limits<float>::max();
    Check(Same(expected,
               Masked(image.data(), mask.data(), 33, 2, negative, 0, 2, 0, 0)),
          "masked extreme signed tie and optional sentinel");
    for (const bool* selected_mask : {static_cast<const bool*>(nullptr),
                                      static_cast<const bool*>(mask.data())}) {
      Peak weighted;
      weighted.value =
          pf::SimpleWeighted(image.data(), weights.data(), 33, 2, weighted.x,
                             weighted.y, negative, 0, 2, selected_mask, 0, 0);
      Check(Same(expected, weighted),
            "weighted extreme signed tie and optional sentinel");
    }
  }
  // Improving rows with their maximum at the left edge exercise ordered
  // position recovery, including a masked-out first occurrence.
  image.assign(33 * 17, 0.0f);
  mask.assign(image.size(), true);
  for (size_t row = 0; row != 17; ++row) {
    image[row * 33] = float(row + 1);
    image[row * 33 + 1] = -float(row + 1);
  }
  peak = Masked(image.data(), mask.data(), 33, 17, true, 0, 17, 0, 0);
  Check(peak.value && *peak.value == 17.0f && peak.x == 0 && peak.y == 16,
        "improving first-column maxima");
  mask[16 * 33] = false;
  peak = Masked(image.data(), mask.data(), 33, 17, true, 0, 17, 0, 0);
  Check(peak.value && *peak.value == -17.0f && peak.x == 1 && peak.y == 16,
        "improving row maximum after masked first occurrence");
}

void BorderCases() {
  const std::vector<float> image(4, 1.0f);
  const aocommon::UVector<bool> mask(4, true);
  for (const auto [xb, yb] : {std::pair<size_t, size_t>{3, 0},
                              {0, 3},
                              {3, 3},
                              {std::numeric_limits<size_t>::max(), 0},
                              {0, std::numeric_limits<size_t>::max()}}) {
    std::cout << "border case " << xb << ',' << yb << std::endl;
    const Peak peak =
        Masked(image.data(), mask.data(), 2, 2, true, 0, 2, xb, yb);
    Check(!peak.value && peak.x == 2 && peak.y == 2,
          "oversized border is an empty region, never a wrapped read");
  }
}

void Benchmark(size_t width) {
  const size_t height = width, count = width * height;
  std::mt19937 random(97873);
  std::uniform_real_distribution<float> noise(-8.0f, 8.0f);
  std::vector<float> image(count);
  aocommon::UVector<bool> mask(count);
  for (float& value : image) value = noise(random);
  std::cout << std::setprecision(9);
  for (size_t stride : {1, 3, 16}) {
    for (size_t i = 0; i != count; ++i)
      mask[i] = stride == 1 || (stride == 3 ? i % 3 != 0 : i % 16 == 0);
    for (bool negative : {false, true}) {
      Check(Same(Sequential(image.data(), mask.data(), width, height, negative,
                            0, height, 8, 8),
                 Masked(image.data(), mask.data(), width, height, negative, 0,
                        height, 8, 8)),
            "benchmark result agreement");
      for (size_t repeat = 0; repeat != 9; ++repeat) {
        for (size_t order = 0; order != 2; ++order) {
          const bool candidate = (order == 0) != (repeat % 2 == 0);
          const auto start = std::chrono::steady_clock::now();
          const Peak peak = candidate
                                ? Masked(image.data(), mask.data(), width,
                                         height, negative, 0, height, 8, 8)
                                : Sequential(image.data(), mask.data(), width,
                                             height, negative, 0, height, 8, 8);
          const double milliseconds =
              std::chrono::duration<double, std::milli>(
                  std::chrono::steady_clock::now() - start)
                  .count();
          benchmark_sink = peak.value.ValueOr(0.0f);
          std::cout << "timing," << width << ',' << stride << ',' << negative
                    << ',' << repeat << ',' << candidate << ',' << milliseconds
                    << '\n';
        }
      }
    }
  }
}
}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--borders") {
    BorderCases();
  } else if (argc == 2 && std::string(argv[1]) == "--valid") {
    ValidCases();
  } else if (argc == 3 && std::string(argv[1]) == "--benchmark") {
    const size_t width = std::stoul(argv[2]);
    if (width != 3072 && width != 4096) return 2;
    Benchmark(width);
  } else if (argc == 1) {
    ValidCases();
    BorderCases();
  } else {
    return 2;
  }
  std::cout << "masked peak checks=" << checks << " failures=" << failures
            << '\n';
  return failures ? 1 : 0;
}
