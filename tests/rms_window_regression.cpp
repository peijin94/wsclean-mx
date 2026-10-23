// SPDX-License-Identifier: GPL-3.0-or-later
// Standalone regression linked directly to production math/rms_image.cc.
#include "math/rms_image.h"

#include <schaapcommon/threading/threadpool.h>

#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>

using aocommon::Image;
namespace rms = radler::math::rms_image;

// Deliberately visit every source pixel for each output pixel. Membership is
// expressed as distances, independently of production's separable bounds.
Image Reference(const Image& input, size_t window, bool maximum) {
  Image expected(input);
  const size_t radius = window / 2;
  if (radius == 0) return expected;
  for (size_t y = 0; y < input.Height(); ++y) {
    for (size_t x = 0; x < input.Width(); ++x) {
      float best = std::numeric_limits<float>::quiet_NaN();
      for (size_t py = 0; py < input.Height(); ++py) {
        const bool in_y = py <= y ? y - py <= radius : py - y < radius;
        for (size_t px = 0; px < input.Width(); ++px) {
          const bool in_x = px <= x ? x - px <= radius : px - x < radius;
          const float value = input[py * input.Width() + px];
          if (in_x && in_y && !std::isnan(value) &&
              (std::isnan(best) || (maximum ? value > best : value < best)))
            best = value;
        }
      }
      expected[y * input.Width() + x] = best;
    }
  }
  return expected;
}

size_t checks = 0;

void CheckImage(const Image& actual, const Image& expected,
                const std::string& label) {
  ++checks;
  if (actual.Width() != expected.Width() ||
      actual.Height() != expected.Height())
    throw std::runtime_error(label + ": shape mismatch");
  for (size_t i = 0; i < expected.Size(); ++i) {
    if (std::isnan(actual[i]) && std::isnan(expected[i])) continue;
    if (actual[i] != expected[i] ||
        (actual[i] == 0.0f && std::signbit(actual[i]) != std::signbit(expected[i]))) {
      std::cerr << label << " pixel=" << i << " expected=" << expected[i]
                << " actual=" << actual[i] << '\n';
      throw std::runtime_error(label + ": value mismatch");
    }
  }
}

void Check(const Image& input, size_t window, bool alias = false) {
  const Image before(input);
  for (bool maximum : {false, true}) {
    const Image expected = Reference(before, window, maximum);
    const std::string label = std::string(maximum ? "maximum" : "minimum") +
        " " + std::to_string(input.Width()) + "x" +
        std::to_string(input.Height()) + " window=" + std::to_string(window) +
        (alias ? " alias" : " separate");
    Image output(input);
    const Image& source = alias ? output : input;
    if (maximum)
      rms::SlidingMaximum(output, source, window);
    else
      rms::SlidingMinimum(output, source, window);
    CheckImage(output, expected, label);
    ++checks;
    if (input.Size() &&
        std::memcmp(input.Data(), before.Data(), input.Size() * sizeof(float)))
      throw std::runtime_error(label + ": modified separate input");
  }
}

int main(int argc, char** argv) {
  const std::string mode = argc > 1 ? argv[1] : "all";
  try {
    const size_t threads = argc > 2 ? std::stoul(argv[2]) : 1;
    if (threads == 0) throw std::runtime_error("thread count must be positive");
    schaapcommon::ThreadPool::GetInstance().SetNThreads(threads);
    if (mode == "all" || mode == "ordinary") {
      Image input(7, 5);
      for (size_t i = 0; i < input.Size(); ++i)
        input[i] = static_cast<float>((i * 13) % 31) - 15.0f;
      for (size_t window : {2, 3, 4, 5, 6}) Check(input, window);
    }
    if (mode == "all" || mode == "zero") {
      Check(Image(3, 2, {6, -3, 4, 9, 2, -7}), 0);
      Check(Image(3, 2, {6, -3, 4, 9, 2, -7}), 1);
    }
    if (mode == "all" || mode == "bounds") {
      for (size_t width : {1, 2, 7}) {
        for (size_t height : {1, 2, 5}) {
          Image input(width, height);
          for (size_t i = 0; i < input.Size(); ++i)
            input[i] = static_cast<float>((i * 13) % 31) - 15.0f;
          for (size_t window : {size_t(2), size_t(3), size_t(4), size_t(11),
                                size_t(32), std::numeric_limits<size_t>::max()})
            Check(input, window);
        }
      }
    }
    if (mode == "all" || mode == "alias") {
      for (size_t window : {0, 1, 2, 3, 4, 11})
        Check(Image(3, 2, {6, -3, 4, 9, 2, -7}), window, true);
      // A separate non-owning input can also view the output's old storage.
      Image output(3, 2, {6, -3, 4, 9, 2, -7});
      const Image expected = Reference(output, 4, false);
      const Image view(output.Data(), output.Width(), output.Height());
      rms::SlidingMinimum(output, view, 4);
      CheckImage(output, expected, "minimum input view aliases output storage");
    }
    if (mode == "all" || mode == "nan") {
      const float nan = std::numeric_limits<float>::quiet_NaN();
      const float inf = std::numeric_limits<float>::infinity();
      // Exercise every NaN position, plus all-NaN intermediate rows/windows.
      for (size_t position = 0; position < 12; ++position) {
        Image input(4, 3, {8, 3, -2, 7, 5, -6, 9, 4, 1, -3, 2, 6});
        input[position] = nan;
        for (size_t window : {0, 1, 2, 4, 13}) Check(input, window);
      }
      for (size_t window : {0, 1, 2, 4, 13}) {
        Check(Image(4, 3, nan), window);
        Check(Image(4, 3, {nan, nan, nan, nan, nan, -inf, inf, nan,
                           nan, 0.0f, -0.0f, nan}), window);
      }
    }
    if (mode == "all" || mode == "empty") {
      for (size_t window : {0, 1, 2, 32}) {
        Check(Image(), window);
        Check(Image(nullptr, 0, 3), window);
        Check(Image(3, 0), window);
      }
    }
    if (mode == "all" || mode == "matrix") {
      std::mt19937 random(23022);
      const float special[] = {std::numeric_limits<float>::quiet_NaN(),
                               std::numeric_limits<float>::infinity(),
                               -std::numeric_limits<float>::infinity(),
                               0.0f, -0.0f, 1.0f, -1.0f};
      for (size_t width = 1; width <= 8; ++width) {
        for (size_t height = 1; height <= 6; ++height) {
          for (bool nonfinite : {false, true}) {
            Image input(width, height);
            for (float& value : input)
              value = nonfinite ? special[random() % 7]
                                : static_cast<float>(int(random() % 19) - 9);
            for (size_t window = 0; window <= 20; ++window) {
              Check(input, window);
              Check(input, window, true);
            }
            Check(input, std::numeric_limits<size_t>::max(), true);
          }
        }
      }
    }
    if (checks == 0) throw std::runtime_error("unknown test mode: " + mode);
    std::cout << "rms mode=" << mode << " threads=" << threads
              << " checks=" << checks << " failures=0\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL: " << error.what() << " checks=" << checks << '\n';
    return 1;
  }
}
