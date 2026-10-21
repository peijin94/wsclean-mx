// Microbench: ducc0 c2c pair (as used in metalinversion) vs thread count.
#include <chrono>
#include <complex>
#include <cstdio>
#include <vector>
#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"
#include "ducc0/infra/mav.h"
int main(int argc, char** argv) {
  const std::size_t grid = argc > 1 ? std::stoul(argv[1]) : 6248;
  for (int nt : {1, 2, 4, 8}) {
    std::vector<std::complex<float>> buf(grid * grid);
    for (std::size_t i = 0; i < grid * grid; ++i)
      buf[i] = {float(i % 97) / 97.f, float(i % 53) / 53.f};
    const auto t0 = std::chrono::steady_clock::now();
    const int reps = 3;
    for (int r = 0; r < reps; ++r) {
      const ducc0::cfmav<std::complex<float>> in(buf.data(), {grid, grid});
      ducc0::vfmav<std::complex<float>> out(buf.data(), {grid, grid});
      ducc0::detail_fft::c2c(in, out, {0}, false, 1.0f, (std::size_t)nt);
      ducc0::detail_fft::c2c(in, out, {1}, false, 1.0f, (std::size_t)nt);
    }
    const auto t1 = std::chrono::steady_clock::now();
    using ms = std::chrono::duration<double, std::milli>;
    // one axis-{0} + one axis-{1} c2c per rep = one pair; report per pair
    printf("grid=%zu threads=%d pair_ms=%.1f checksum=%.6f\n", grid, nt,
           ms(t1 - t0).count() / reps, double(buf[grid + 1].real()));
  }
  return 0;
}
