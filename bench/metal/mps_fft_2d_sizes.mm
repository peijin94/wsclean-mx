// MPSGraph 2-D complex FFT across sizes chosen so the *padded* size differs.
// If Bluestein pads to the next power of two, 3001 (prime -> 8192) should cost
// about the same as 3968 (-> 8192) and far more than 3000 (smooth) or 4096.
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

static void bench2d(id<MTLDevice> device, size_t n, int reps) {
  MPSGraph* graph = [[MPSGraph alloc] init];
  MPSGraphTensor* in = [graph placeholderWithShape:@[ @(n), @(n) ]
                                          dataType:MPSDataTypeComplexFloat32
                                              name:@"in"];
  MPSGraphFFTDescriptor* desc = [MPSGraphFFTDescriptor descriptor];
  desc.inverse = NO;
  desc.scalingMode = MPSGraphFFTScalingModeNone;
  MPSGraphTensor* out = [graph fastFourierTransformWithTensor:in
                                                         axes:@[ @0, @1 ]
                                                   descriptor:desc
                                                         name:@"fft"];

  const size_t floats = n * n * 2;
  id<MTLBuffer> buf = [device newBufferWithLength:floats * sizeof(float)
                                          options:MTLResourceStorageModeShared];
  std::vector<std::complex<float>> host(n * n);
  std::mt19937 rng(7);
  for (auto& v : host) v = {float(rng() % 1000) / 1000.0f, float(rng() % 1000) / 1000.0f};
  std::memcpy(buf.contents, host.data(), floats * sizeof(float));

  MPSGraphTensorData* inData = [[MPSGraphTensorData alloc] initWithMTLBuffer:buf
                                                                      shape:@[ @(n), @(n) ]
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

  std::vector<float> got(floats);
  MPSNDArray* nd = [result mpsndarray];
  NSInteger strides[3] = {2 * (NSInteger)sizeof(float) * (NSInteger)n,
                          2 * (NSInteger)sizeof(float), (NSInteger)sizeof(float)};
  [nd readBytes:got.data() strideBytes:strides];
  double sr = 0, si = 0;
  for (auto& v : host) { sr += v.real(); si += v.imag(); }
  const double err = std::hypot(got[0] - sr, got[1] - si) / (std::hypot(sr, si) + 1e-30);

  printf("%5zu^2  %8.1f ms   %6.2f ns/point   %s\n", n, ms, ms * 1e6 / (n * (double)n),
         err > 1e-3 ? "WRONG" : "ok");
  fflush(stdout);
}

int main() {
  @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    const size_t sizes[] = {3960, 3969, 4032, 3968, 4096};  // 3960=2^3*3^2*5*11, 3969=3^4*7^2, 4032=2^6*3^2*7
    for (size_t n : sizes) bench2d(device, n, 3);
  }
  return 0;
}
