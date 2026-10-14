// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Contains code from schaapcommon, Copyright (C) 2022 ASTRON (Netherlands
// Institute for Radio Astronomy), GPL-3.0-or-later.
// Compare schaapcommon Convolve: upstream FFTW row/column composite vs the mx
// ducc0 version, both against a double-precision ducc0 reference.
//
// Build:
//   S=deps/src/schaapcommon
//   c++ -std=c++20 -O3 -march=native -I$S/include -I$S/src -I$S/external \
//     -I$S/include/schaapcommon -Iwork/aocommon/include -I/opt/homebrew/include \
//     bench/micro/convolve_check.cpp $S/src/math/compositefft.cc \
//     $S/src/threading/threadpool.cc -L/opt/homebrew/lib -lfftw3f \
//     -o bench/micro/bin/convolve_check
#include <fftw3.h>

#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <random>
#include <vector>

#include "ducc0/fft/fft.h"
#include "ducc0/fft/fftnd_impl.h"
#include "math/compositefft.h"
#include "threading/staticfor.h"
#include "threading/threadpool.h"

using schaapcommon::StaticFor;
using schaapcommon::ThreadPool;

// Verbatim copy of upstream schaapcommon b47f19dace28 math::Convolve.
void ConvolveUpstream(float* image, const float* kernel, size_t image_width, size_t image_height) {
  using namespace schaapcommon::math;
  const size_t image_size = image_width * image_height;
  const size_t complex_width = image_width / 2 + 1;
  const size_t complex_size = complex_width * image_height;
  float* temp_data = fftwf_alloc_real(image_size);
  fftwf_complex* fft_image_data = fftwf_alloc_complex(complex_size);
  fftwf_complex* fft_kernel_data = fftwf_alloc_complex(complex_size);
  fftwf_plan plan_r2c = fftwf_plan_dft_r2c_1d(image_width, nullptr, nullptr, FFTW_ESTIMATE);
  fftwf_plan plan_c2c_forward =
      fftwf_plan_dft_1d(image_height, nullptr, nullptr, FFTW_FORWARD, FFTW_ESTIMATE);
  fftwf_plan plan_c2c_backward =
      fftwf_plan_dft_1d(image_height, nullptr, nullptr, FFTW_BACKWARD, FFTW_ESTIMATE);
  fftwf_plan plan_c2r = fftwf_plan_dft_c2r_1d(image_width, nullptr, nullptr, FFTW_ESTIMATE);
  StaticFor<size_t> loop;
  FftR2CComposite(plan_r2c, plan_c2c_forward, image_height, image_width, image, fft_image_data,
                  loop);
  std::copy_n(kernel, image_size, temp_data);
  FftR2CComposite(plan_r2c, plan_c2c_forward, image_height, image_width, temp_data, fft_kernel_data,
                  loop);
  const float fact = 1.0 / image_size;
  loop.Run(0, image_height, [&](size_t y_start, size_t y_end) {
    for (size_t y = y_start; y != y_end; ++y) {
      for (size_t x = 0; x != complex_width; ++x) {
        const size_t i = y * complex_width + x;
        reinterpret_cast<std::complex<float>*>(fft_image_data)[i] *=
            fact * reinterpret_cast<std::complex<float>*>(fft_kernel_data)[i];
      }
    }
  });
  FftC2RComposite(plan_c2c_backward, plan_c2r, image_height, image_width, fft_image_data, image,
                  loop);
  fftwf_free(fft_image_data);
  fftwf_free(fft_kernel_data);
  fftwf_free(temp_data);
  fftwf_destroy_plan(plan_r2c);
  fftwf_destroy_plan(plan_c2c_forward);
  fftwf_destroy_plan(plan_c2c_backward);
  fftwf_destroy_plan(plan_c2r);
}

// Copy of the mx version (patches/mx/schaapcommon/0002).
void ConvolveMx(float* image, const float* kernel, size_t image_width, size_t image_height) {
  const size_t image_size = image_width * image_height;
  const size_t complex_width = image_width / 2 + 1;
  const size_t complex_size = complex_width * image_height;
  const size_t n_threads = ThreadPool::GetInstance().NThreads();
  std::vector<std::complex<float>> fft_image_data(complex_size);
  std::vector<std::complex<float>> fft_kernel_data(complex_size);
  const ducc0::cfmav<float> image_in(image, {image_height, image_width});
  const ducc0::cfmav<float> kernel_in(kernel, {image_height, image_width});
  const ducc0::vfmav<std::complex<float>> image_fft(fft_image_data.data(),
                                                    {image_height, complex_width});
  const ducc0::vfmav<std::complex<float>> kernel_fft(fft_kernel_data.data(),
                                                     {image_height, complex_width});
  ducc0::r2c(image_in, image_fft, {0, 1}, true, 1.0f, n_threads);
  ducc0::r2c(kernel_in, kernel_fft, {0, 1}, true, 1.0f, n_threads);
  const float fact = 1.0 / image_size;
  StaticFor<size_t> loop;
  loop.Run(0, image_height, [&](size_t y_start, size_t y_end) {
    for (size_t i = y_start * complex_width; i != y_end * complex_width; ++i)
      fft_image_data[i] *= fact * fft_kernel_data[i];
  });
  const ducc0::vfmav<float> image_out(image, {image_height, image_width});
  ducc0::c2r_mut(image_fft, image_out, {0, 1}, false, 1.0f, n_threads);
}

std::vector<double> ConvolveReference(const std::vector<float>& image,
                                      const std::vector<float>& kernel, size_t w, size_t h) {
  const size_t cw = w / 2 + 1;
  std::vector<double> img(image.begin(), image.end()), ker(kernel.begin(), kernel.end());
  std::vector<std::complex<double>> fi(cw * h), fk(cw * h);
  ducc0::r2c(ducc0::cfmav<double>(img.data(), {h, w}),
             ducc0::vfmav<std::complex<double>>(fi.data(), {h, cw}), {0, 1}, true, 1.0, 4);
  ducc0::r2c(ducc0::cfmav<double>(ker.data(), {h, w}),
             ducc0::vfmav<std::complex<double>>(fk.data(), {h, cw}), {0, 1}, true, 1.0, 4);
  for (size_t i = 0; i != fi.size(); ++i) fi[i] *= fk[i] / double(w * h);
  std::vector<double> out(w * h);
  ducc0::c2r_mut(ducc0::vfmav<std::complex<double>>(fi.data(), {h, cw}),
                 ducc0::vfmav<double>(out.data(), {h, w}), {0, 1}, false, 1.0, 4);
  return out;
}

int main() {
  ThreadPool::GetInstance().SetNThreads(8);
  std::mt19937 rng(42);
  std::normal_distribution<float> noise(0.0f, 1e-3f);
  for (size_t n : {512, 1000, 2048, 4096}) {
    std::vector<float> image(n * n), kernel(n * n, 0.0f);
    for (float& v : image) v = noise(rng);
    for (int s = 0; s != 50; ++s) image[rng() % (n * n)] += 1.0f;
    // Gaussian scale kernel centred on pixel (0,0) with wrap-around, sum 1.
    const double sigma = 8.0;
    double sum = 0.0;
    for (size_t y = 0; y != n; ++y)
      for (size_t x = 0; x != n; ++x) {
        const double dx = std::min(x, n - x), dy = std::min(y, n - y);
        const double v = std::exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
        kernel[y * n + x] = v;
        sum += v;
      }
    for (float& v : kernel) v /= sum;

    const std::vector<double> ref = ConvolveReference(image, kernel, n, n);
    std::vector<float> a = image, b = image;
    auto t0 = std::chrono::steady_clock::now();
    ConvolveUpstream(a.data(), kernel.data(), n, n);
    auto t1 = std::chrono::steady_clock::now();
    ConvolveMx(b.data(), kernel.data(), n, n);
    auto t2 = std::chrono::steady_clock::now();

    double rr = 0, ea = 0, eb = 0, eab = 0, fa = 0, fb = 0, fr = 0;
    for (size_t i = 0; i != n * n; ++i) {
      rr += ref[i] * ref[i];
      ea += (a[i] - ref[i]) * (a[i] - ref[i]);
      eb += (b[i] - ref[i]) * (b[i] - ref[i]);
      eab += double(a[i] - b[i]) * double(a[i] - b[i]);
      fa += a[i];
      fb += b[i];
      fr += ref[i];
    }
    std::printf(
        "n=%5zu  upstream-vs-ref %.2e  mx-vs-ref %.2e  upstream-vs-mx %.2e  "
        "flux ref %.6f up %.6f mx %.6f  time up %.0f ms mx %.0f ms\n",
        n, std::sqrt(ea / rr), std::sqrt(eb / rr), std::sqrt(eab / rr), fr, fa, fb,
        std::chrono::duration<double, std::milli>(t1 - t0).count(),
        std::chrono::duration<double, std::milli>(t2 - t1).count());
  }
}
