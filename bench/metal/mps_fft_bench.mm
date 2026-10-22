// Benchmark GPU (MPSGraph) vs CPU (ducc0) 2-D complex FFT at the grid sizes the
// wsclean Metal path actually uses. MPSGraph represents a complex tensor as a
// real tensor with a trailing interleaved dim of 2 that is NOT counted in the
// shape, so an N x N complex grid is N*N*2 floats.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <MetalPerformanceShadersGraph/MetalPerformanceShadersGraph.h>

#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"
#include "ducc0/infra/mav.h"

static double cpu_fft(std::vector<std::complex<float>>& buf, size_t n, size_t nthreads) {
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
    const size_t batch = argc > 3 ? std::stoul(argv[3]) : 1;

    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    MPSGraphDevice* gdev = [MPSGraphDevice deviceWithMTLDevice:device];
    MPSGraph* graph = [[MPSGraph alloc] init];

    MPSGraphTensor* in = [graph placeholderWithShape:@[ @(batch), @(n), @(n) ]
                                            dataType:MPSDataTypeComplexFloat32
                                                name:@"in"];
    MPSGraphFFTDescriptor* desc = [MPSGraphFFTDescriptor descriptor];
    desc.inverse = NO;
    desc.scalingMode = MPSGraphFFTScalingModeNone;
    MPSGraphTensor* out = [graph fastFourierTransformWithTensor:in
                                                           axes:@[ @1, @2 ]
                                                     descriptor:desc
                                                           name:@"fft"];

    const size_t floats = batch * n * n * 2;
    id<MTLBuffer> inbuf =
        [device newBufferWithLength:floats * sizeof(float) options:MTLResourceStorageModeShared];
    id<MTLBuffer> outbuf =
        [device newBufferWithLength:floats * sizeof(float) options:MTLResourceStorageModeShared];

    std::vector<std::complex<float>> host(batch * n * n), cpu_copy(n * n);
    std::mt19937 rng(7);
    for (auto& v : host) v = {float(rng() % 1000) / 1000.0f, float(rng() % 1000) / 1000.0f};
    std::copy(host.begin(), host.begin() + n * n, cpu_copy.begin());
    std::memcpy(inbuf.contents, host.data(), floats * sizeof(float));
    cpu_copy = host;

    MPSGraphTensorData* inData = [[MPSGraphTensorData alloc] initWithMTLBuffer:inbuf
                                                                        shape:@[ @(batch), @(n), @(n) ]
                                                                     dataType:MPSDataTypeComplexFloat32];
    MPSGraphTensorData* outData = [[MPSGraphTensorData alloc] initWithMTLBuffer:outbuf
                                                                         shape:@[ @(batch), @(n), @(n) ]
                                                                      dataType:MPSDataTypeComplexFloat32];

    // Warm-up (compiles the graph, allocates intermediate buffers).
    @autoreleasepool {
      NSDictionary<MPSGraphTensor*, MPSGraphTensorData*>* res =
          [graph runWithFeeds:@{in : inData} targetTensors:@[ out ] targetOperations:nil];
      (void)res;
    }

    MPSGraphTensorData* result = nil;
    double gpu_ms = 0.0;
    for (int r = 0; r < reps; ++r) {
      const auto t0 = std::chrono::steady_clock::now();
      @autoreleasepool {
        NSDictionary<MPSGraphTensor*, MPSGraphTensorData*>* res =
            [graph runWithFeeds:@{in : inData} targetTensors:@[ out ] targetOperations:nil];
        result = res[out];
      }
      gpu_ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0)
                    .count();
    }
    gpu_ms /= reps;

    const double cpu1 = cpu_fft(cpu_copy, n, 1);
    const double cpu8 = cpu_fft(cpu_copy, n, 8);

    // Agreement: compare the GPU output with ducc0 (different scaling/order, so
    // report a relative RMS on the transform we can compare directly).
    std::vector<float> got(floats);
    if (result != nil) {
      MPSNDArray* nd = [result mpsndarray];
      // Interleaved complex is exposed as (N, N, 2) float32.
      NSInteger strides[4] = {2 * (NSInteger)sizeof(float) * (NSInteger)n * (NSInteger)n,
                              2 * (NSInteger)sizeof(float) * (NSInteger)n,
                              2 * (NSInteger)sizeof(float), (NSInteger)sizeof(float)};
      [nd readBytes:got.data() strideBytes:strides];
      if (getenv("MX_BENCH_DUMP")) {
        fprintf(stderr, "[bench] got[0..3] = %.4f %.4f %.4f %.4f | cpu %.4f %.4f\n",
                got[0], got[1], got[2], got[3], cpu_copy[0].real(), cpu_copy[0].imag());
      }
    }
    const float* g = got.data();
    double num = 0.0, den = 0.0;
    for (size_t i = 0; i < n * n; i += 97) {
      const std::complex<float> a(g[2 * i], g[2 * i + 1]);
      const std::complex<float> b = cpu_copy[i];
      num += std::norm(a - b);
      den += std::norm(b);
    }

    printf("grid=%zu batch=%zu  gpu(MPSGraph)=%.1fms  cpu ducc0 1thr=%.1fms  8thr=%.1fms  "
           "speedup_vs_cpu8=%.2fx  rel_rms=%.3g\n",
           n, batch, gpu_ms, cpu1, cpu8, cpu8 / gpu_ms, std::sqrt(num / (den + 1e-30)));
  }
  return 0;
}
