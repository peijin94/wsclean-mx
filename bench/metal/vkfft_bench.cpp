// vkFFT (native Metal backend, via Apple's metal-cpp) complex64 2-D FFT
// benchmark, directly comparable to mps_fft_bench.mm.
//
//   c++ -std=c++20 -O3 -DVKFFT_BACKEND=5 -I <vkFFT>/vkFFT -I <vkFFT>/metal-cpp \
//       vkfft_bench.cpp ... -framework Metal -framework Foundation -framework QuartzCore
#define NS_PRIVATE_IMPLEMENTATION
#define MTL_PRIVATE_IMPLEMENTATION
#define CA_PRIVATE_IMPLEMENTATION
#include "Foundation/Foundation.hpp"
#include "Metal/Metal.hpp"
#include "QuartzCore/QuartzCore.hpp"

#define VKFFT_BACKEND 5
#include <iostream>
#include "/tmp/vk_v1.2.31.h"

#include <chrono>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"
#include "ducc0/infra/mav.h"

static double cpu_fft_once(const std::vector<std::complex<float>>& src, size_t n, size_t nthreads) {
  std::vector<std::complex<float>> buf = src;
  const auto t0 = std::chrono::steady_clock::now();
  ducc0::cfmav<std::complex<float>> in(buf.data(), {n, n});
  ducc0::vfmav<std::complex<float>> out(buf.data(), {n, n});
  ducc0::detail_fft::c2c(in, out, {0}, false, 1.0f, nthreads);
  ducc0::detail_fft::c2c(in, out, {1}, false, 1.0f, nthreads);
  return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  const size_t n = argc > 1 ? std::stoul(argv[1]) : 3968;
  const int reps = argc > 2 ? std::stoi(argv[2]) : 3;

  NS::AutoreleasePool* pool = NS::AutoreleasePool::alloc()->init();
  MTL::Device* device = MTL::CreateSystemDefaultDevice();
  MTL::CommandQueue* queue = device->newCommandQueue();

  const size_t bytes = n * n * 2 * sizeof(float);
  MTL::Buffer* bufIn = device->newBuffer(bytes, MTL::ResourceStorageModeShared);
  MTL::Buffer* bufOut = device->newBuffer(bytes, MTL::ResourceStorageModeShared);

  std::vector<std::complex<float>> host(n * n);
  std::mt19937 rng(7);
  for (auto& v : host) v = {float(rng() % 1000) / 1000.0f, float(rng() % 1000) / 1000.0f};
  std::memcpy(bufOut->contents(), host.data(), bytes);

  VkFFTConfiguration config = {};
  config.device = device;
  config.queue = queue;
  config.FFTdim = 2;
  config.size[0] = n;
  config.size[1] = n;
  MTL::Buffer* inPtr = bufIn;
  MTL::Buffer* outPtr = bufOut;
  uint64_t bsz = bytes;
  config.buffer = &outPtr;
  config.bufferSize = &bsz;

  VkFFTApplication app = {};
  const VkFFTResult res = initializeVkFFT(&app, config);
  if (res != VKFFT_SUCCESS) {
    printf("grid=%zu  vkFFT init failed: %d\n", n, (int)res);
    return 1;
  }

  VkFFTLaunchParams launch = {};

  auto run_once = [&]() {
    MTL::CommandBuffer* cb = queue->commandBuffer();
    MTL::ComputeCommandEncoder* enc = cb->computeCommandEncoder();
    launch.commandBuffer = cb;
    launch.commandEncoder = enc;
    VkFFTAppend(&app, -1, &launch);
    enc->endEncoding();
    cb->commit();
    cb->waitUntilCompleted();
    const double gpu = (cb->GPUEndTime() - cb->GPUStartTime()) * 1e3;
    enc->release();
    cb->release();
    return gpu;
  };
  run_once();  // warm-up

  double gpu_ms = 0.0, wall_ms = 0.0;
  for (int r = 0; r < reps; ++r) {
    // The plan is in-place, so refresh the input outside the timed region.
    std::memcpy(bufOut->contents(), host.data(), bytes);
    const auto t0 = std::chrono::steady_clock::now();
    gpu_ms += run_once();
    wall_ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0)
                   .count();
  }
  gpu_ms /= reps;
  wall_ms /= reps;

  const double cpu1 = cpu_fft_once(host, n, 1);
  const double cpu8 = cpu_fft_once(host, n, 8);

  std::memcpy(bufOut->contents(), host.data(), bytes);
  run_once();
  const float* g = static_cast<const float*>(bufOut->contents());
  double sumr = 0.0, sumi = 0.0;
  for (const auto& v : host) { sumr += v.real(); sumi += v.imag(); }
  const double dc_err = std::hypot(g[0] - sumr, g[1] - sumi) / (std::hypot(sumr, sumi) + 1e-30);

  printf("grid=%zu  vkFFT(Metal)=%.1fms gpu %.1fms wall  cpu ducc0 1thr=%.1fms  8thr=%.1fms  "
         "speedup_vs_cpu8=%.2fx  dc_rel_err=%.3g\n",
         n, gpu_ms, wall_ms, cpu1, cpu8, cpu8 / gpu_ms, dc_err);

  // Teardown of the 1.2.31 Metal backend segfaults under this metal-cpp build;
  // the process is about to exit, so the leak is harmless.
  if (getenv("MX_VKFFT_CLEANUP")) deleteVkFFT(&app);
  pool->release();
  return 0;
}
