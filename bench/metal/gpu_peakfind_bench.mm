// Feasibility probe for GPU deconvolution: the dominant cost in multiscale CLEAN
// is FindMultiScalePeak, i.e. an argmax scan over the scale stack (measured 78%
// of deconvolution time at 3k). This measures that scan on CPU vs GPU at the
// real shape: nscales images of n x n float32.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <chrono>
#include <cstdio>
#include <random>
#include <vector>

static NSString* kSrc = @R"(
#include <metal_stdlib>
using namespace metal;

// One threadgroup per image, strided scan, threadgroup tree reduction.
kernel void argmax_scan(device const float* img [[buffer(0)]],
                        device float2* out [[buffer(1)]],
                        constant uint& n [[buffer(2)]],
                        uint gid [[threadgroup_position_in_grid]],
                        uint tid [[thread_position_in_threadgroup]],
                        uint tcount [[threads_per_threadgroup]]) {
  const device float* base = img + (size_t)gid * n;
  float best = -INFINITY;
  uint besti = 0;
  for (uint i = tid; i < n; i += tcount) {
    const float v = base[i];
    if (v > best) { best = v; besti = i; }
  }
  threadgroup float sval[256];
  threadgroup uint sidx[256];
  sval[tid] = best;
  sidx[tid] = besti;
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint s = tcount / 2; s > 0; s >>= 1) {
    if (tid < s) {
      if (sval[tid + s] > sval[tid]) {
        sval[tid] = sval[tid + s];
        sidx[tid] = sidx[tid + s];
      }
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
  }
  if (tid == 0) out[gid] = float2(sval[0], float(sidx[0]));
}
)";

int main(int argc, char** argv) {
  const std::size_t n = argc > 1 ? std::stoul(argv[1]) : 3072;
  const std::size_t nscales = argc > 2 ? std::stoul(argv[2]) : 8;
  const std::size_t total = n * n * nscales;

  std::vector<float> img(total);
  std::mt19937 rng(7);
  std::uniform_real_distribution<float> d(0.0f, 1.0f);
  for (auto& v : img) v = d(rng);

  // ---- CPU: one pass per scale, 8 threads.
  std::vector<std::pair<float, std::size_t>> cpures(nscales);
  const auto t0 = std::chrono::steady_clock::now();
  for (std::size_t s = 0; s < nscales; ++s) {
    const float* p = img.data() + s * n * n;
    float best = -1e30f;
    std::size_t besti = 0;
    for (std::size_t i = 0; i < n * n; ++i) {
      if (p[i] > best) { best = p[i]; besti = i; }
    }
    cpures[s] = {best, besti};
  }
  const double cpu_ms =
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();

  // ---- GPU
  id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
  id<MTLCommandQueue> q = [dev newCommandQueue];
  NSError* err = nil;
  id<MTLLibrary> lib = [dev newLibraryWithSource:kSrc options:nil error:&err];
  if (lib == nil) { printf("compile failed: %s\n", err.localizedDescription.UTF8String); return 1; }
  id<MTLComputePipelineState> pipe =
      [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"argmax_scan"] error:&err];
  id<MTLBuffer> buf = [dev newBufferWithBytes:img.data()
                                      length:total * sizeof(float)
                                     options:MTLResourceStorageModeShared];
  id<MTLBuffer> res = [dev newBufferWithLength:nscales * sizeof(float) * 2
                                       options:MTLResourceStorageModeShared];
  uint32_t nn = static_cast<uint32_t>(n * n);

  auto run_gpu = [&]() {
    id<MTLCommandBuffer> cb = [q commandBuffer];
    id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
    [enc setComputePipelineState:pipe];
    [enc setBuffer:buf offset:0 atIndex:0];
    [enc setBuffer:res offset:0 atIndex:1];
    [enc setBytes:&nn length:sizeof(nn) atIndex:2];
    [enc dispatchThreadgroups:MTLSizeMake(nscales, 1, 1)
        threadsPerThreadgroup:MTLSizeMake(256, 1, 1)];
    [enc endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
  };
  run_gpu();  // warm
  double gpu_ms = 0.0;
  for (int r = 0; r < 3; ++r) {
    const auto t = std::chrono::steady_clock::now();
    run_gpu();
    gpu_ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
  }
  gpu_ms /= 3.0;

  const float* gr = static_cast<const float*>(res.contents);
  bool ok = true;
  for (std::size_t s = 0; s < nscales; ++s) {
    if (static_cast<std::size_t>(gr[2 * s + 1]) != cpures[s].second) ok = false;
  }
  printf("scales=%zu  image=%zux%zu  bytes=%.0fMB\n", nscales, n, n,
         total * sizeof(float) / 1e6);
  printf("cpu(1 thread/scale)=%.1fms  gpu=%.2fms  speedup=%.1fx  argmax_match=%s\n", cpu_ms,
         gpu_ms, cpu_ms / gpu_ms, ok ? "yes" : "NO");
  return 0;
}
