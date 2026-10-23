// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Linked production-boundary regression for accidental image adapter copies.
#include <atomic>
#include <complex>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <new>
#include <stdexcept>
#include <utility>
#include <vector>

#include <ducc0/fft/fft.h>
#include <ducc0/fft/fftnd_impl.h>
#include <schaapcommon/math/convolution.h>
#include <schaapcommon/threading/threadpool.h>

#include "algorithms/multiscale/multiscale_transforms.h"

namespace {
using aocommon::Image;
using radler::algorithms::multiscale::KernelFftCache;
using radler::algorithms::multiscale::MultiScaleTransforms;
using Shape = MultiScaleTransforms::Shape;

std::atomic<bool> counting{false};
std::atomic<size_t> image_bytes{0};
std::atomic<size_t> image_allocations{0};
size_t checks = 0, failures = 0, scenarios = 0;

void Check(bool condition, const char* message) {
  ++checks;
  if (!condition) {
    ++failures;
    std::cerr << "FAIL: " << message << '\n';
  }
}

bool Same(const Image& a, const Image& b) {
  return a.Width() == b.Width() && a.Height() == b.Height() &&
         std::memcmp(a.Data(), b.Data(), a.Size() * sizeof(float)) == 0;
}

bool SameTail(const Image& actual, const Image& input, size_t prefix) {
  return actual.Width() == input.Width() && actual.Height() == input.Height() &&
         std::memcmp(actual.Data() + prefix, input.Data() + prefix,
                     (input.Size() - prefix) * sizeof(float)) == 0;
}

Image Input(size_t width, size_t height, bool padded, size_t index) {
  Image image(width + (padded ? 3 : 0), height + (padded ? 2 : 0));
  const size_t prefix = width * height;
  for (size_t i = 0; i != prefix; ++i)
    image[i] = float(int((i * 13 + index * 19) % 71) - 35) / 16.0f;
  image[0] = index % 2 ? -0.0f : 0.0f;
  // Tail is opaque storage, including signed zero, infinities and NaN payloads.
  constexpr std::uint32_t bits[] = {0x80000000, 0x7fc01234, 0xff800000,
                                    0x7f800000, 0x3f923456};
  for (size_t i = prefix; i != image.Size(); ++i)
    std::memcpy(&image[i], &bits[i % 5], sizeof(float));
  return image;
}

struct Oracle {
  std::vector<Image> images;
  std::vector<std::vector<std::complex<float>>> products;
};

Oracle FftOracle(MultiScaleTransforms& transforms,
                 const std::vector<Image>& inputs, float scale) {
  const size_t width = transforms.Width(), height = transforms.Height();
  const size_t n = schaapcommon::math::ConvolutionFftSize(width, height);
  Image kernel(width, height);
  // Use production kernel preparation plus the documented FFT convolution API,
  // independently of either Transform adapter and its new borrowed range.
  transforms.PrepareTransform(kernel.Data(), scale);
  std::vector<std::complex<float>> kernel_fft(n), image_fft(n);
  schaapcommon::math::ConvolutionFft(kernel_fft.data(), kernel.Data(), width,
                                     height);
  Oracle result;
  for (const Image& input : inputs) {
    result.images.emplace_back(input);
    schaapcommon::math::ConvolutionFft(image_fft.data(), input.Data(), width,
                                       height);
    schaapcommon::math::ConvolveTransformed(result.images.back().Data(),
                                            image_fft.data(), kernel_fft.data(),
                                            width, height);
    auto& product = result.products.emplace_back(image_fft);
    const float factor = 1.0 / (width * height);
    for (size_t i = 0; i != n; ++i) product[i] *= factor * kernel_fft[i];
  }
  return result;
}

enum class HookMode { kAbsent, kRefuse, kSuccess, kThrow };
struct HookException {};
HookMode hook_mode = HookMode::kAbsent;
const Oracle* hook_oracle = nullptr;
std::vector<float*> hook_destinations;
size_t hook_calls = 0, hook_offset = 0, throw_on_call = 0;
size_t hook_width = 0, hook_height = 0;
bool hook_inputs_valid = true;

int C2RHook(float* image, const std::complex<float>* product, size_t width,
            size_t height) {
  const size_t index = hook_offset + hook_calls++;
  const size_t n = schaapcommon::math::ConvolutionFftSize(width, height);
  hook_inputs_valid &= width == hook_width && height == hook_height &&
                       index < hook_oracle->products.size() &&
                       index < hook_destinations.size();
  if (index < hook_oracle->products.size() &&
      index < hook_destinations.size()) {
    hook_inputs_valid &=
        image == hook_destinations[index] &&
        std::memcmp(product, hook_oracle->products[index].data(),
                    n * sizeof(*product)) == 0;
  }
  if (hook_mode == HookMode::kRefuse) return 0;
  if (hook_mode == HookMode::kThrow && hook_calls == throw_on_call) {
    image[0] =
        12345.0f;  // In-place API: ownership survives, rollback not promised.
    throw HookException{};
  }
  // A real successful inverse hook: match the production CPU c2r arithmetic
  // while respecting the hook's const product contract. Returning 1 skips the
  // library inverse; a duplicate inverse or wrong product fails bitwise checks.
  std::vector<std::complex<float>> copy(product, product + n);
  const ducc0::vfmav<std::complex<float>> in(copy.data(),
                                             {height, width / 2 + 1});
  const ducc0::vfmav<float> out(image, {height, width});
  ducc0::c2r_mut(in, out, {0, 1}, false, 1.0f,
                 schaapcommon::ThreadPool::GetInstance().NThreads());
  return 1;
}

void ConfigureHook(HookMode mode, const Oracle& oracle, size_t width,
                   size_t height, const std::vector<float*>& destinations,
                   size_t offset = 0, size_t throw_on = 0) {
  hook_mode = mode;
  hook_oracle = &oracle;
  hook_destinations = destinations;
  hook_calls = 0;
  hook_offset = offset;
  hook_width = width;
  hook_height = height;
  throw_on_call = throw_on;
  hook_inputs_valid = true;
  schaapcommon::math::SetConvolveC2RHook(mode == HookMode::kAbsent ? nullptr
                                                                   : C2RHook);
}

struct ResetHook {
  ~ResetHook() {
    counting = false;
    schaapcommon::math::SetConvolveC2RHook(nullptr);
  }
};

std::shared_ptr<const KernelFftCache::Fft> CachedKernel(KernelFftCache& cache,
                                                        size_t width,
                                                        size_t height,
                                                        Shape shape,
                                                        float scale) {
  return cache.Get(width, height, shape, scale, []() -> KernelFftCache::Fft {
    throw std::runtime_error("warm kernel unexpectedly rebuilt");
  });
}

void ResourceCheck() {
  constexpr size_t width = 64, height = 48;
  Image input = Input(width, height, false, 0);
  Image scratch;
  MultiScaleTransforms transforms(width, height, Shape::kTaperedQuadraticShape,
                                  std::make_shared<KernelFftCache>());
  // This tracer ran FIRST against unchanged production: vector bitwise match,
  // one full-image allocation, exit 1. Retain transform-red.log and red binary.
  std::vector<Image> expected;
  expected.emplace_back(input);
  transforms.Transform(expected, scratch, 4.0f);
  Image actual(input);
  image_bytes = input.Size() * sizeof(float);
  image_allocations = 0;
  counting = true;
  transforms.Transform(actual, scratch, 4.0f);
  counting = false;
  const bool same = Same(actual, expected[0]);
  Check(same, "tracer scalar/vector bitwise mismatch");
  Check(image_allocations == 0, "warmed scalar copied a full image");
  std::cout << "warmed_scalar image_allocations=" << image_allocations
            << " expected=0 vector_bitwise=" << same << '\n';
}

void TransformChecks(size_t width, size_t height, Shape shape, bool padded,
                     float scale) {
  ResetHook reset;
  auto cache = std::make_shared<KernelFftCache>();
  MultiScaleTransforms transforms(width, height, shape, cache);
  std::vector<Image> inputs;
  for (size_t i = 0; i != 3; ++i)
    inputs.emplace_back(Input(width, height, padded, i));
  const Oracle oracle = FftOracle(transforms, inputs, scale);
  Image scratch(5, 3, -37.25f);
  const Image saved_scratch(scratch);
  float* const scratch_data = scratch.Data();
  std::vector<Image> warm(inputs);
  transforms.Transform(warm, scratch, scale);
  for (size_t i = 0; i != inputs.size(); ++i)
    Check(Same(warm[i], oracle.images[i]),
          "warm vector differs from FFT oracle");
  const auto owner = CachedKernel(*cache, width, height, shape, scale);
  const auto generation = owner->Generation();
  const auto kernel_bytes =
      std::vector<std::complex<float>>(owner->begin(), owner->end());
  Check(generation != 0, "cached kernel has no publication generation");
  for (HookMode mode :
       {HookMode::kAbsent, HookMode::kRefuse, HookMode::kSuccess}) {
    for (size_t repeat = 0; repeat != 2; ++repeat) {
      const size_t before = failures;
      std::vector<Image> scalar(inputs), multiple(inputs);
      std::vector<float*> scalar_data, vector_data;
      for (size_t i = 0; i != inputs.size(); ++i) {
        scalar_data.push_back(scalar[i].Data());
        vector_data.push_back(multiple[i].Data());
      }
      image_bytes = inputs[0].Size() * sizeof(float);
      size_t scalar_allocations = 0;
      for (size_t i = 0; i != inputs.size(); ++i) {
        ConfigureHook(mode, oracle, width, height, scalar_data, i);
        image_allocations = 0;
        counting = true;
        transforms.Transform(scalar[i], scratch, scale);
        counting = false;
        scalar_allocations += image_allocations.load();
        Check(hook_calls == (mode == HookMode::kAbsent ? 0u : 1u) &&
                  hook_inputs_valid,
              "scalar hook sequence/product/destination differs");
      }
      ConfigureHook(mode, oracle, width, height, vector_data);
      image_allocations = 0;
      counting = true;
      transforms.Transform(multiple, scratch, scale);
      counting = false;
      const size_t vector_allocations = image_allocations.load();
      Check(scalar_allocations == 0, "scalar allocated full-image copy");
      Check(vector_allocations == 0, "vector allocated full-image copy");
      Check(hook_calls == (mode == HookMode::kAbsent ? 0u : inputs.size()) &&
                hook_inputs_valid,
            "vector hook sequence/product/destination differs");
      schaapcommon::math::SetConvolveC2RHook(nullptr);
      for (size_t i = 0; i != inputs.size(); ++i) {
        Check(Same(scalar[i], oracle.images[i]),
              "scalar differs from FFT oracle");
        Check(Same(multiple[i], oracle.images[i]),
              "vector differs from FFT oracle");
        Check(SameTail(scalar[i], inputs[i], width * height) &&
                  SameTail(multiple[i], inputs[i], width * height),
              "transform changed padded dimensions/tail bytes");
        Check(scalar[i].Data() == scalar_data[i] &&
                  multiple[i].Data() == vector_data[i],
              "transform replaced owning image storage");
      }
      const auto reused = CachedKernel(*cache, width, height, shape, scale);
      Check(reused == owner && reused->Generation() == generation &&
                std::memcmp(reused->data(), kernel_bytes.data(),
                            kernel_bytes.size() * sizeof(kernel_bytes[0])) == 0,
            "warm transform replaced/mutated published kernel");
      Check(scratch.Data() == scratch_data && Same(scratch, saved_scratch),
            "formerly unused scratch changed");
      ++scenarios;
      std::cout << "threads="
                << schaapcommon::ThreadPool::GetInstance().NThreads()
                << " shape=" << int(shape) << " size=" << width << 'x' << height
                << " padded=" << padded << " scale=" << scale
                << " hook=" << int(mode) << " repeat=" << repeat
                << " scalar_allocations=" << scalar_allocations
                << " vector_allocations=" << vector_allocations << ' '
                << (before == failures ? "PASS" : "FAIL") << '\n';
    }
  }
  // No-cache calls must retain the same result and publication behavior.
  MultiScaleTransforms uncached(width, height, shape);
  Image cold(inputs[0]);
  uncached.Transform(cold, scratch, scale);
  Check(Same(cold, oracle.images[0]),
        "uncached scalar differs from FFT oracle");
  // Scratch remains unused even when it aliases the transformed image.
  cold = inputs[0];
  transforms.Transform(cold, cold, scale);
  Check(Same(cold, oracle.images[0]), "aliased unused scratch changed result");
  std::vector<Image> empty;
  ConfigureHook(HookMode::kRefuse, oracle, width, height, {});
  transforms.Transform(empty, scratch, scale);
  Check(empty.empty() && hook_calls == 0 && Same(scratch, saved_scratch),
        "empty vector processed an image or touched scratch");
}

void ExceptionChecks(Shape shape, bool multiple) {
  ResetHook reset;
  constexpr size_t width = 17, height = 10;
  MultiScaleTransforms transforms(width, height, shape,
                                  std::make_shared<KernelFftCache>());
  std::vector<Image> inputs;
  for (size_t i = 0; i != 3; ++i)
    inputs.emplace_back(Input(width, height, true, i));
  const Oracle oracle = FftOracle(transforms, inputs, 4.0f);
  std::vector<Image> actual(inputs);
  std::vector<float*> pointers;
  for (Image& image : actual) pointers.push_back(image.Data());
  Image scratch(3, 2, 9.0f);
  const Image saved_scratch(scratch);
  const size_t throw_on = multiple ? 2 : 1;
  ConfigureHook(HookMode::kThrow, oracle, width, height, pointers, 0, throw_on);
  bool caught = false;
  try {
    if (multiple)
      transforms.Transform(actual, scratch, 4.0f);
    else
      transforms.Transform(actual[0], scratch, 4.0f);
  } catch (const HookException&) {
    caught = true;
  }
  Check(caught && hook_calls == throw_on && hook_inputs_valid,
        "expected inverse hook exception/sequence missing");
  schaapcommon::math::SetConvolveC2RHook(nullptr);
  for (size_t i = 0; i != actual.size(); ++i) {
    Check(actual[i].Data() == pointers[i] &&
              SameTail(actual[i], inputs[i], width * height),
          "exception invalidated Image ownership/dimensions/tail");
    if (i + 1 < throw_on)
      Check(Same(actual[i], oracle.images[i]),
            "exception changed already completed image");
    else if (i + 1 == throw_on)
      Check(actual[i][0] == 12345.0f,
            "exception lost the owning image's in-place write");
    else
      Check(Same(actual[i], inputs[i]), "exception changed unprocessed image");
    actual[i].Assign(inputs[i].begin(), inputs[i].end());
  }
  Check(Same(scratch, saved_scratch), "hook exception touched unused scratch");
  transforms.Transform(actual, scratch, 4.0f);
  for (size_t i = 0; i != actual.size(); ++i)
    Check(Same(actual[i], oracle.images[i]),
          "owning image cannot be reused after exception");
  std::cout << "exception shape=" << int(shape) << " multiple=" << multiple
            << " caught=" << caught << '\n';
}

void KernelExceptionCheck() {
  constexpr size_t width = 7, height = 5;
  MultiScaleTransforms transforms(width, height, Shape::kTaperedQuadraticShape);
  Image image = Input(width, height, true, 0);
  const Image saved(image);
  float* const pointer = image.Data();
  Image scratch;
  bool caught = false;
  try {
    transforms.Transform(image, scratch, 20.0f);
  } catch (const std::runtime_error&) {
    caught = true;
  }
  Check(caught && pointer == image.Data() && Same(image, saved),
        "kernel preparation exception invalidated image");
}
}  // namespace

void* operator new[](std::size_t bytes) {
  if (void* memory = std::malloc(bytes ? bytes : 1)) {
    if (counting.load() && bytes == image_bytes.load()) ++image_allocations;
    return memory;
  }
  throw std::bad_alloc();
}
void operator delete[](void* memory) noexcept { std::free(memory); }
void operator delete[](void* memory, std::size_t) noexcept {
  std::free(memory);
}

int main() {
  ResetHook reset;
  try {
    schaapcommon::ThreadPool::GetInstance().SetNThreads(1);
    ResourceCheck();
    for (size_t threads : {size_t(1), size_t(4)}) {
      schaapcommon::ThreadPool::GetInstance().SetNThreads(threads);
      for (Shape shape :
           {Shape::kTaperedQuadraticShape, Shape::kGaussianShape}) {
        for (auto [width, height] : {std::pair<size_t, size_t>{7, 5},
                                     {8, 6},
                                     {17, 10},
                                     {16, 11},
                                     {64, 48}})
          for (bool padded : {false, true})
            for (float scale : {0.0f, 2.0f, 4.0f})
              TransformChecks(width, height, shape, padded, scale);
        ExceptionChecks(shape, false);
        ExceptionChecks(shape, true);
      }
      KernelExceptionCheck();
    }
  } catch (const std::exception& error) {
    counting = false;
    ++failures;
    std::cerr << "unexpected exception: " << error.what() << '\n';
  } catch (...) {
    counting = false;
    ++failures;
    std::cerr << "unexpected non-standard exception\n";
  }
  std::cout << scenarios << " matrix scenarios, " << checks << " checks, "
            << failures << " failures\n";
  return failures ? 1 : 0;
}
