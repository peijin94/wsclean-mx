// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Exercises the linked production implementations, not copied mx algorithms.
#include <aocommon/image.h>
#include <schaapcommon/math/convolution.h>
#include <schaapcommon/math/resampler.h>
#include <schaapcommon/threading/threadpool.h>
#include "math/peak_finder.h"

#include <algorithm>
#include <cmath>
#include <complex>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
size_t checks = 0;
void Check(bool condition, const char* message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}

void ConvolutionChecks(size_t threads) {
  schaapcommon::ThreadPool::GetInstance().SetNThreads(threads);
  std::mt19937 random(42);
  std::uniform_real_distribution<float> distribution(-1.0f, 1.0f);
  for (auto [width, height] : {std::pair<size_t, size_t>{7, 5}, {8, 6}, {17, 10}, {32, 24}}) {
    const size_t count = width * height;
    std::vector<float> image(count), kernel(count);
    for (float& value : image) value = distribution(random);
    for (float& value : kernel) value = distribution(random) / count;
    const auto original_kernel = kernel;
    std::vector<double> expected(count, 0.0);
    // Independent O(N^2) double-precision circular convolution oracle.
    for (size_t y = 0; y != height; ++y)
      for (size_t x = 0; x != width; ++x)
        for (size_t ky = 0; ky != height; ++ky)
          for (size_t kx = 0; kx != width; ++kx)
            expected[y * width + x] +=
                double(kernel[ky * width + kx]) *
                image[((y + height - ky) % height) * width + (x + width - kx) % width];
    auto convolved = image;
    schaapcommon::math::Convolve(convolved.data(), kernel.data(), width, height);
    double error = 0.0, power = 0.0;
    for (size_t i = 0; i != count; ++i) {
      const double difference = convolved[i] - expected[i];
      error += difference * difference;
      power += expected[i] * expected[i];
      Check(std::isfinite(convolved[i]), "Convolve emitted non-finite pixel");
    }
    Check(std::sqrt(error / power) < 2e-6, "Convolve disagrees with spatial oracle");
    Check(kernel == original_kernel, "Convolve modified kernel input");

    const size_t fft_count = schaapcommon::math::ConvolutionFftSize(width, height);
    std::vector<std::complex<float>> image_fft(fft_count), kernel_fft(fft_count);
    schaapcommon::math::ConvolutionFft(image_fft.data(), image.data(), width, height);
    schaapcommon::math::ConvolutionFft(kernel_fft.data(), kernel.data(), width, height);
    const auto saved_image_fft = image_fft, saved_kernel_fft = kernel_fft;
    std::vector<float> cached(count);
    for (size_t repeat = 0; repeat != 3; ++repeat) {
      schaapcommon::math::ConvolveTransformed(cached.data(), image_fft.data(),
                                            kernel_fft.data(), width, height);
      Check(std::memcmp(cached.data(), convolved.data(), count * sizeof(float)) == 0,
            "cached convolution changed result");
      Check(image_fft == saved_image_fft && kernel_fft == saved_kernel_fft,
            "cached convolution mutated transform input");
    }
  }
}

void ResamplerChecks(size_t threads) {
  using schaapcommon::math::Resampler;
  std::vector<float> input(8 * 6, 2.0f), output(16 * 12);
  Resampler resampler(8, 6, 16, 12, threads);
  resampler.Resample(input.data(), output.data());
  for (float value : output)
    Check(std::isfinite(value) && std::fabs(value - 2.0f) < 1e-6f,
          "upsampling failed to preserve constant image");

  input[3] = std::numeric_limits<float>::quiet_NaN();
  input[8] = std::numeric_limits<float>::infinity();
  auto sanitized = input;
  sanitized[3] = sanitized[8] = 0.0f;
  std::vector<float> expected(output.size());
  resampler.Resample(sanitized.data(), expected.data());
  resampler.Resample(input.data(), output.data());
  Check(std::memcmp(output.data(), expected.data(), output.size() * sizeof(float)) == 0,
        "resampler non-finite sanitization differs from explicit zeros");

  std::vector<float> queued_input(8 * 6, 2.0f), queued(output.size());
  resampler.Start();
  resampler.AddTask(queued_input.data(), queued.data());
  resampler.Finish();
  for (float value : queued)
    Check(std::isfinite(value) && std::fabs(value - 2.0f) < 1e-6f,
          "queued resampler differs from direct path");
}

template <typename T>
void MedianChecks() {
  const T nan = std::numeric_limits<T>::quiet_NaN();
  const T infinity = std::numeric_limits<T>::infinity();
  const std::vector<std::vector<T>> cases = {
      {}, {1}, {1, 3}, {-3, -2, -1}, {0, -T(0), 0},
      {nan, 1, 3, infinity, -infinity}, {nan, infinity}, {7, 7, 7, 7}};
  for (const auto& values : cases) {
    std::vector<T> finite;
    for (T value : values) if (std::isfinite(value)) finite.push_back(value);
    auto median = [](std::vector<T> sorted) -> T {
      if (sorted.empty()) return T(0);
      std::sort(sorted.begin(), sorted.end());
      const size_t n = sorted.size();
      return n % 2 ? sorted[n / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) * T(0.5);
    };
    const T expected_median = median(finite);
    for (T& value : finite) value = std::fabs(value - expected_median);
    const auto actual = aocommon::detail::MadImplementation(values.data(), values.size());
    Check(actual.first == expected_median, "median edge case differs from sorted oracle");
    Check(actual.second == median(finite), "MAD edge case differs from sorted oracle");
  }
}

template <typename T>
void PeakChecks() {
  std::vector<T> image(17 * 5, T(0));
  image[19] = T(-4);
  image[25] = T(4);
  image[60] = T(4);
  image[30] = std::numeric_limits<T>::quiet_NaN();
  size_t x = 0, y = 0;
  auto peak = radler::math::peak_finder::Simple(
      image.data(), 17, 5, x, y, true, 0, 5, 0, 0);
  Check(peak && *peak == T(-4) && x == 2 && y == 1,
        "absolute peak tie did not choose first index");
  peak = radler::math::peak_finder::Simple(
      image.data(), 17, 5, x, y, false, 0, 5, 0, 0);
  Check(peak && *peak == T(4) && x == 8 && y == 1,
        "positive peak tie did not choose first index");
  std::fill(image.begin(), image.end(), std::numeric_limits<T>::quiet_NaN());
  peak = radler::math::peak_finder::Simple(
      image.data(), 17, 5, x, y, true, 0, 5, 0, 0);
  Check(!peak && x == 17 && y == 5, "all-NaN peak sentinel changed");
}
}  // namespace

int main() {
  try {
    for (size_t threads : {size_t(1), size_t(4)}) {
      ConvolutionChecks(threads);
      ResamplerChecks(threads);
    }
    MedianChecks<float>();
    MedianChecks<double>();
    PeakChecks<float>();
    PeakChecks<double>();
    std::cout << "PASS: " << checks << " linked numerical assertions\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL after " << checks << " assertions: " << error.what() << '\n';
    return 1;
  }
}
