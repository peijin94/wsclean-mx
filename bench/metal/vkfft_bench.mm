// vkFFT (native Metal backend) complex64 2-D FFT benchmark, same interface as
// mps_fft_bench.mm so the numbers are directly comparable.
//
//   build: c++ -std=c++20 -O3 -fobjc-arc -DVKFFT_BACKEND=5 -I <vkFFT-src>/vkFFT \
//             mps-style includes... vkfft_bench.mm -framework Metal ...
#define VKFFT_BACKEND 5
#include "vkFFT.h"

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <chrono>
#include <complex>
#include <cstdio>
#include <cstdlib>
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
  @autoreleasepool {
    const size_t n = argc > 1 ? std::stoul(argv[1]) : 3968;
    const int reps = argc > 2 ? std::stoi(argv[2]) : 3;

    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> queue = [device newCommandQueue];

    const size_t bytes = n * n * 2 * sizeof(float);
    id<MTLBuffer> buf = [device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    id<MTLBuffer> bufOut = [device newBufferWithLength:bytes options:MTLResourceStorageModeShared];

    std::vector<std::complex<float>> host(n * n);
    std::mt19937 rng(7);
    for (auto& v : host) v = {float(rng() % 1000) / 1000.0f, float(rng() % 1000) / 1000.0f};
    std::memcpy(buf.contents, host.data(), bytes);

    VkFFTConfiguration config = {};
    config.MTLDevice = (void*)CFBridgingRetain((__bridge id)device);
    config.MTLCommandQueue = (void*)CFBridgingRetain((__bridge id)queue);
    config.numberOfQueues = 1;
    config.size[0] = n;
    config.size[1] = n;
    config.fftDimensionMask = 3;  // both axes
    config.buffer = (void*)CFBridgingRetain((__bridge id)buf);
    config.bufferSize[0] = bytes;
    config.isInputFormatted = 1;
    config.inputBuffer = (void*)CFBridgingRetain((__bridge id)buf);
    config.inputBufferSize = bytes;
    config.buffer = (void*)CFBridgingRetain((__bridge id)bufOut);
    config.bufferSize[0] = bytes;

    VkFFTApplication app = {};
    VkFFTResult res = initializeVkFFT(&app, config);
    if (res != VKFFT_SUCCESS) {
      printf("grid=%zu  vkFFT init failed: %d\n", n, (int)res);
      return 1;
    }

    VkFFTLaunchParams launch = {};
    launch.MTLCommandQueue = (void*)CFBridgingRetain((__bridge id)queue);
    launch.buffer = (void*)CFBridgingRetain((__bridge id)bufOut);
    launch.inputBuffer = (void*)CFBridgingRetain((__bridge id)buf);

    // warm-up
    VkFFTAppend(&app, -1, &launch);

    double gpu_ms = 0.0;
    for (int r = 0; r < reps; ++r) {
      const auto t0 = std::chrono::steady_clock::now();
      VkFFTAppend(&app, -1, &launch);
      gpu_ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0)
                    .count();
    }
    gpu_ms /= reps;

    const double cpu1 = cpu_fft_once(host, n, 1);
    const double cpu8 = cpu_fft_once(host, n, 8);

    // Correctness: DC bin of a 2-D forward transform must equal the input sum.
    const float* g = static_cast<const float*>(bufOut.contents);
    double sumr = 0.0, sumi = 0.0;
    for (const auto& v : host) { sumr += v.real(); sumi += v.imag(); }
    const double dc_err = std::hypot(g[0] - sumr, g[1] - sumi) / (std::hypot(sumr, sumi) + 1e-30);

    printf("grid=%zu  vkFFT(Metal)=%.1fms  cpu ducc0 1thr=%.1fms  8thr=%.1fms  "
           "speedup_vs_cpu8=%.2fx  dc_rel_err=%.3g\n",
           n, gpu_ms, cpu1, cpu8, cpu8 / gpu_ms, dc_err);

    deleteVkFFT(&app);
  }
  return 0;
}
