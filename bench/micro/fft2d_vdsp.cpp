// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Forward + inverse 2D real FFT of an n x n image (the transforms used by
// schaapcommon Convolve): ducc0 r2c/c2r against vDSP_fft2d_zrip, including
// vDSP's conversion to and from its split-complex layout.
//
//   c++ -std=c++20 -O3 -march=native -I work/schaapcommon/external \
//       bench/micro/fft2d_vdsp.cpp work/schaapcommon/external/ducc0/infra/threading.cc \
//       work/schaapcommon/external/ducc0/infra/string_utils.cc \
//       -framework Accelerate -o bench/micro/bin/fft2d_vdsp
//   bench/micro/bin/fft2d_vdsp <n> [threads=8] [reps=5]

#include <vecLib/vDSP.h>

#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"

template <typename F>
double BestOf(int reps, F&& f) {
  double best = 1e30;
  for (int r = 0; r < reps; ++r) {
    const auto t0 = std::chrono::steady_clock::now();
    f();
    const auto t1 = std::chrono::steady_clock::now();
    best = std::min(best, std::chrono::duration<double>(t1 - t0).count());
  }
  return best;
}

int main(int argc, char** argv) {
  const size_t n = std::atoi(argv[1]);
  const size_t threads = argc > 2 ? std::atoi(argv[2]) : 8;
  const int reps = argc > 3 ? std::atoi(argv[3]) : 5;
  const size_t cw = n / 2 + 1;

  std::vector<float> image(n * n), out(n * n);
  std::mt19937 rng(1);
  std::normal_distribution<float> normal;
  for (float& v : image) v = normal(rng);
  std::vector<std::complex<float>> spectrum(cw * n);

  auto ducc = [&](size_t nthreads) {
    const ducc0::cfmav<float> in(image.data(), {n, n});
    const ducc0::vfmav<std::complex<float>> spec(spectrum.data(), {n, cw});
    ducc0::r2c(in, spec, {0, 1}, true, 1.0f, nthreads);
    const ducc0::vfmav<float> o(out.data(), {n, n});
    ducc0::c2r_mut(spec, o, {0, 1}, false, 1.0f / (n * n), nthreads);
  };
  for (size_t t : {size_t{1}, threads}) {
    const double s = BestOf(reps, [&] { ducc(t); });
    std::printf("n=%zu ducc0 %zu thr: %.2f ms (r2c + c2r)\n", n, t, s * 1e3);
  }

  const vDSP_Length log2n = std::lround(std::log2(double(n)));
  if ((size_t{1} << log2n) != n) {
    std::printf("vDSP needs a power of 2\n");
    return 0;
  }
  FFTSetup setup = vDSP_create_fftsetup(log2n, kFFTRadix2);
  std::vector<float> re(n * n / 2), im(n * n / 2);
  DSPSplitComplex split{re.data(), im.data()};
  const double s = BestOf(reps, [&] {
    vDSP_ctoz(reinterpret_cast<const DSPComplex*>(image.data()), 2, &split, 1,
              n * n / 2);
    vDSP_fft2d_zrip(setup, &split, 1, 0, log2n, log2n, kFFTDirection_Forward);
    vDSP_fft2d_zrip(setup, &split, 1, 0, log2n, log2n, kFFTDirection_Inverse);
    vDSP_ztoc(&split, 1, reinterpret_cast<DSPComplex*>(out.data()), 2,
              n * n / 2);
  });
  const float scale = 1.0f / (4.0f * n * n);
  double err = 0.0, ref = 0.0;
  for (size_t i = 0; i != n * n; ++i) {
    const double d = out[i] * scale - image[i];
    err += d * d;
    ref += double(image[i]) * image[i];
  }
  std::printf("n=%zu vDSP 1 thr:  %.2f ms (fft2d_zrip fwd + inv), roundtrip rel err %.1e\n",
              n, s * 1e3, std::sqrt(err / ref));
  vDSP_destroy_fftsetup(setup);
}
