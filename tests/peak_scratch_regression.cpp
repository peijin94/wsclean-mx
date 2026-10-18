// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Regression for needless full-image scratch allocation in multiscale search.
// Calls the public production API; array allocation counting is test-only.
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <new>
#include <vector>
#include <schaapcommon/threading/threadpool.h>
#include "algorithms/threaded_deconvolution_tools.h"

namespace {
std::atomic<bool> counting{false};
std::atomic<size_t> image_allocations{0};
constexpr size_t kWidth = 64, kHeight = 48;
constexpr size_t kImageBytes = kWidth * kHeight * sizeof(float);
}
void* operator new[](std::size_t bytes) {
  if (void* memory = std::malloc(bytes ? bytes : 1)) {
    if (counting.load() && bytes == kImageBytes) ++image_allocations;
    return memory;
  }
  throw std::bad_alloc();
}
void operator delete[](void* memory) noexcept { std::free(memory); }
void operator delete[](void* memory, std::size_t) noexcept { std::free(memory); }

int main() {
  using radler::algorithms::ThreadedDeconvolutionTools;
  using radler::algorithms::multiscale::MultiScaleTransforms;
  schaapcommon::ThreadPool::GetInstance().SetNThreads(1);
  aocommon::Image image(kWidth, kHeight, 0.0f);
  image[10 + 10 * kWidth] = 4.0f;
  image[20 + 20 * kWidth] = -6.0f;
  aocommon::Image empty;
  aocommon::Image rms(kWidth, kHeight, 1.0f);
  rms[10 + 10 * kWidth] = 2.0f;
  aocommon::UVector<float> scales{0.0f};
  std::vector<aocommon::UVector<bool>> scale_masks;
  aocommon::UVector<bool> mask(kWidth * kHeight, true);
  mask[20 + 20 * kWidth] = false;
  MultiScaleTransforms transforms(kWidth, kHeight, radler::MultiscaleShape::kTaperedQuadraticShape,
                                  std::make_shared<radler::algorithms::multiscale::KernelFftCache>());
  ThreadedDeconvolutionTools tools;
  std::vector<ThreadedDeconvolutionTools::PeakData> results;
  size_t failures = 0, scenarios = 0;
  for (bool weighted : {false, true}) {
    for (bool masked : {false, true}) {
      for (bool calculate_rms : {false, true}) {
        const auto search = [&] {
          tools.FindMultiScalePeak(&transforms, image, scales, results, true,
                                   masked ? mask.data() : nullptr, scale_masks,
                                   0.0f, weighted ? rms : empty, calculate_rms);
        };
        search();  // Warm FFT/cache and result storage outside measurement.
        image_allocations = 0;
        counting = true;
        search();
        counting = false;
        const size_t allocations = image_allocations.load();
        // One transformed image, plus scratch only for RMS-weighted searches.
        const size_t expected_allocations = weighted ? 2 : 1;
        const size_t expected_x = weighted || masked ? 10 : 20;
        const float expected_raw = weighted ? 8.0f : (masked ? 4.0f : -6.0f);
        const float expected_normalized = weighted || masked ? 4.0f : -6.0f;
        const bool good = allocations == expected_allocations && results.size() == 1 &&
            results[0].x == expected_x && results[0].y == expected_x &&
            results[0].unnormalized_value && results[0].normalized_value &&
            std::fabs(*results[0].unnormalized_value - expected_raw) < 1e-5f &&
            std::fabs(*results[0].normalized_value - expected_normalized) < 1e-5f &&
            (calculate_rms ? results[0].rms > 0.0f : results[0].rms == -1.0f);
        ++scenarios;
        failures += !good;
        std::cout << "weighted=" << weighted << " mask=" << masked
                  << " rms=" << calculate_rms << " image_allocations=" << allocations
                  << " expected=" << expected_allocations << ' ' << (good ? "PASS" : "FAIL") << '\n';
      }
    }
  }
  std::cout << scenarios << " scenarios, " << failures << " failures\n";
  return failures ? 1 : 0;
}
