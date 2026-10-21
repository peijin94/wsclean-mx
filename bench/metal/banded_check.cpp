// Standalone check: bandedFFT vs full c2c pair on random sparse data.
#include <chrono>
#include <complex>
#include <cstdio>
#include <random>
#include <vector>
#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"
#include "ducc0/infra/mav.h"
int main() {
  const std::size_t grid = 256, W2 = 160, H2 = 160;
  std::vector<std::complex<float>> full(grid * grid), band(grid * grid);
  std::mt19937 rng(42);
  for (std::size_t k = 0; k < 2000; ++k) {
    std::size_t i = rng() % grid, j = rng() % grid;
    full[i * grid + j] = band[i * grid + j] = {(float)(rng() % 100) / 100.f, 0.f};
  }
  // occupancy
  std::vector<unsigned char> orows(grid, 0), ocols(grid, 0);
  for (std::size_t i = 0; i < grid; ++i)
    for (std::size_t j = 0; j < grid; ++j)
      if (full[i * grid + j] != std::complex<float>(0, 0)) { orows[i] = 1; ocols[j] = 1; }
  // full pair
  {
    ducc0::cfmav<std::complex<float>> in(full.data(), {grid, grid});
    ducc0::vfmav<std::complex<float>> out(full.data(), {grid, grid});
    ducc0::detail_fft::c2c(in, out, {0}, false, 1.0f, 1);
    ducc0::detail_fft::c2c(in, out, {1}, false, 1.0f, 1);
  }
  // banded (inline copy of the ufirst/vfirst logic)
  {
    ducc0::vfmav<std::complex<float>> inout(band.data(), {grid, grid});
    const std::size_t halfW = W2 / 2, halfH = H2 / 2;
    // force ufirst: axis0 on occupied cols, axis1 on dirty rows
    for (std::size_t c = 0; c < grid; ++c) {
      if (!ocols[c]) continue;
      auto sub = inout.subarray({{},{c, c + 1}});
      ducc0::detail_fft::c2c(sub, sub, {0}, false, 1.0f, 1);
    }
    {
      auto sub = inout.subarray({{0, halfW},{}});
      ducc0::detail_fft::c2c(sub, sub, {1}, false, 1.0f, 1);
    }
    {
      auto sub = inout.subarray({{grid - halfW, grid},{}});
      ducc0::detail_fft::c2c(sub, sub, {1}, false, 1.0f, 1);
    }
  }
  double maxd = 0, maxd_out = 0;
  for (std::size_t i = 0; i < grid; ++i)
    for (std::size_t j = 0; j < grid; ++j) {
      const bool dirty_row = (i < W2 / 2) || (i >= grid - W2 / 2);
      double d = (double)std::abs(full[i * grid + j] - band[i * grid + j]);
      if (dirty_row && ocols[j])
        maxd = std::max(maxd, d);
      else
        maxd_out = std::max(maxd_out, d);
    }
  printf("max diff inside (dirty-rows x occ-cols) = %.3g (outside = %.3g)\n", maxd, maxd_out);
  return 0;
}
