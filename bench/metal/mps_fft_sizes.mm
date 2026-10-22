// MPSGraph 1-D complex FFT across sizes with different factorisations, to find
// what actually makes it slow at 3968 = 2^7*31.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <MetalPerformanceShadersGraph/MetalPerformanceShadersGraph.h>

#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

static double bench_size(id<MTLDevice> device, size_t n, int reps) {
  MPSGraph* graph = [[MPSGraph alloc] init];
  MPSGraphTensor* in = [graph placeholderWithShape:@[ @(n) ]
                                          dataType:MPSDataTypeComplexFloat32
                                              name:@"in"];
  MPSGraphFFTDescriptor* desc = [MPSGraphFFTDescriptor descriptor];
  desc.inverse = NO;
  desc.scalingMode = MPSGraphFFTScalingModeNone;
  MPSGraphTensor* out = [graph fastFourierTransformWithTensor:in
                                                         axes:@[ @0 ]
                                                   descriptor:desc
                                                         name:@"fft"];

  const size_t floats = n * 2;
  id<MTLBuffer> buf = [device newBufferWithLength:floats * sizeof(float)
                                          options:MTLResourceStorageModeShared];
  std::vector<std::complex<float>> host(n);
  std::mt19937 rng(7);
  for (auto& v : host) v = {float(rng() % 1000) / 1000.0f, float(rng() % 1000) / 1000.0f};
  std::memcpy(buf.contents, host.data(), floats * sizeof(float));

  MPSGraphTensorData* inData = [[MPSGraphTensorData alloc] initWithMTLBuffer:buf
                                                                      shape:@[ @(n) ]
                                                                   dataType:MPSDataTypeComplexFloat32];
  @autoreleasepool {
    [graph runWithFeeds:@{in : inData} targetTensors:@[ out ] targetOperations:nil];
  }

  MPSGraphTensorData* result = nil;
  double ms = 0.0;
  for (int r = 0; r < reps; ++r) {
    const auto t0 = std::chrono::steady_clock::now();
    @autoreleasepool {
      NSDictionary<MPSGraphTensor*, MPSGraphTensorData*>* res =
          [graph runWithFeeds:@{in : inData} targetTensors:@[ out ] targetOperations:nil];
      result = res[out];
    }
    ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  }
  ms /= reps;

  // DC bin must equal the exact sum (validates the transform really ran).
  std::vector<float> got(floats);
  MPSNDArray* nd = [result mpsndarray];
  NSInteger strides[2] = {2 * (NSInteger)sizeof(float), (NSInteger)sizeof(float)};
  [nd readBytes:got.data() strideBytes:strides];
  double sr = 0, si = 0;
  for (auto& v : host) { sr += v.real(); si += v.imag(); }
  const double err = std::hypot(got[0] - sr, got[1] - si) / (std::hypot(sr, si) + 1e-30);
  return ms + (err > 1e-4 ? 1e6 : 0.0);  // flag wrong answers loudly
}

int main() {
  @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    struct Case { size_t n; const char* note; };
    const Case cases[] = {
        {4096, "2^12"},
        {3968, "2^7*31   <- our grid"},
        {3840, "2^8*15"},
        {4000, "2^5*5^3"},
        {3969, "3^4*7^2"},
        {4032, "2^6*3^2*7"},
        {4093, "prime"},
        {8192, "2^13 (what a pad-to-pow2 would cost)"},
    };
    for (const auto& c : cases) {
      const double ms = bench_size(device, c.n, 3);
      if (ms > 1e5) {
        printf("%6zu  %-42s  WRONG RESULT\n", c.n, c.note);
      } else {
        printf("%6zu  %-42s  %7.2f ms\n", c.n, c.note, ms);
      }
      fflush(stdout);
    }
  }
  return 0;
}
