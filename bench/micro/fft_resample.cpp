// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Microbenchmark of the two FFTs in schaapcommon::math::Resampler for the
// 4096 / padding 1.2 / small-inversion case: r2c on the inversion grid and
// c2r on the padded image grid. Compares FFTW (whichever libfftw3f this is
// linked against) with ducc0, single- and multi-threaded.
//
//   fft_resample <in_size> <out_size> <threads> [reps]

#include <fftw3.h>

#include <chrono>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"

using cf = std::complex<float>;

template <typename F>
double best_of(int reps, F&& f) {
  double best = 1e30;
  for (int r = 0; r < reps; ++r) {
    auto t0 = std::chrono::steady_clock::now();
    f();
    auto t1 = std::chrono::steady_clock::now();
    best = std::min(best, std::chrono::duration<double>(t1 - t0).count());
  }
  return best;
}

int main(int argc, char** argv) {
  const size_t n_in = std::atoi(argv[1]);
  const size_t n_out = std::atoi(argv[2]);
  const int threads = std::atoi(argv[3]);
  const int reps = argc > 4 ? std::atoi(argv[4]) : 3;

  std::vector<float> img_in(n_in * n_in), img_out(n_out * n_out);
  std::vector<cf> f_in(n_in * (n_in / 2 + 1)), f_out(n_out * (n_out / 2 + 1));
  std::mt19937 rng(1);
  std::normal_distribution<float> g;
  for (auto& v : img_in) v = g(rng);
  for (auto& v : f_out) v = cf(g(rng), g(rng));

  fftwf_init_threads();
  fftwf_plan_with_nthreads(threads);
  auto* fin = reinterpret_cast<fftwf_complex*>(f_in.data());
  auto* fout = reinterpret_cast<fftwf_complex*>(f_out.data());
  std::vector<cf> f_out_copy(f_out);
  fftwf_plan p_r2c = fftwf_plan_dft_r2c_2d(n_in, n_in, img_in.data(), fin, FFTW_ESTIMATE);
  fftwf_plan p_c2r = fftwf_plan_dft_c2r_2d(n_out, n_out, fout, img_out.data(), FFTW_ESTIMATE);

  double fftw_r2c = best_of(reps, [&] { fftwf_execute(p_r2c); });
  double fftw_c2r = best_of(reps, [&] {
    std::copy(f_out_copy.begin(), f_out_copy.end(), f_out.begin());  // c2r destroys input
    fftwf_execute(p_c2r);
  });

  ducc0::cmav<float, 2> d_in(img_in.data(), {n_in, n_in});
  ducc0::vmav<cf, 2> d_fin(f_in.data(), {n_in, n_in / 2 + 1});
  ducc0::cmav<cf, 2> d_fout(f_out_copy.data(), {n_out, n_out / 2 + 1});
  ducc0::vmav<float, 2> d_out(img_out.data(), {n_out, n_out});
  double ducc_r2c = best_of(reps, [&] {
    ducc0::r2c(ducc0::cfmav<float>(d_in), ducc0::vfmav<cf>(d_fin), {0, 1}, true, 1.f, threads);
  });
  double ducc_c2r = best_of(reps, [&] {
    ducc0::c2r(ducc0::cfmav<cf>(d_fout), ducc0::vfmav<float>(d_out), {0, 1}, false, 1.f, threads);
  });

  std::printf("%5zu->%5zu  threads=%d  fftw r2c %.3fs c2r %.3fs (sum %.3fs)  |  ducc0 r2c %.3fs c2r %.3fs (sum %.3fs)\n",
              n_in, n_out, threads, fftw_r2c, fftw_c2r, fftw_r2c + fftw_c2r, ducc_r2c, ducc_c2r,
              ducc_r2c + ducc_c2r);
  fftwf_destroy_plan(p_r2c);
  fftwf_destroy_plan(p_c2r);
  return 0;
}
