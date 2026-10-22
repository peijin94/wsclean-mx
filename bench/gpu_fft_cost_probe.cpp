// Synthetic FFT cost ablation, not an optimization or real-MS science proof.
// Usage: gpu_fft_cost_probe n batch reps (even n: 2..4096, batch: 1..8,
// reps: 1..20). Link the SAME production mxvkfft.cpp.o; do not rebuild it.
// One actual, untimed forward R2C creates the retained dense spectrum.
// Each mode has exactly one excluded warmup (rep=-1, warmup=true).
// init_s includes Fft construction + initReal on fresh calls and reused
// warmups; reused measured calls report zero. submit_wait_s includes all
// submit-side shader/input-buffer setup, copies, encode, and completion wait.
// Inverse CPU spectrum preparation and all validation are outside that timer.
// gpu_s is Fft::gpuSeconds(), not a subtraction of CPU and GPU clock epochs.
// MX_METAL_PROFILE=1 supplies production same-Mach encode/wait/GPU intervals
// separately on stderr. steady_clock is used ONLY for elapsed durations here.
// LIMITATION: fresh-plan teardown is excluded from every reported duration;
// fresh plans can still benefit from process/driver caches after warmup.
// Validation checks every real cell in every batch plane, excluding padding.
// Reported errors are the worst per-plane relative RMS and max-error/peak.
// Fixed acceptance limits: relative RMS <= 1e-5, max-error/peak <= 1e-4.
// No performance conclusions are implied by this synthetic delta fixture.

#include "metal/mxvkfft.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
using Fft = mx::vk::Fft;
constexpr double kRmsLimit = 1e-5;
constexpr double kPeakLimit = 1e-4;
constexpr const char* kModes[] = {
    "fresh-convolution", "reused-convolution", "reused-inverse"};

std::size_t argument(const char* text, std::size_t limit) {
  std::size_t value = 0;
  if (!*text) throw std::runtime_error("empty argument");
  for (const char* p = text; *p; ++p) {
    if (*p < '0' || *p > '9')
      throw std::runtime_error("arguments must be unsigned decimal integers");
    const std::size_t digit = static_cast<std::size_t>(*p - '0');
    if (digit > limit || value > (limit - digit) / 10)
      throw std::runtime_error("argument exceeds its bound");
    value = value * 10 + digit;
  }
  if (!value) throw std::runtime_error("arguments must be positive");
  return value;
}

void require(bool ok, const Fft& fft, const char* operation) {
  if (!ok) throw std::runtime_error(std::string(operation) + ": " + fft.error());
}

struct Errors {
  double rms = 0;
  double peak = 0;
};

Errors validate(const float* output, const std::vector<float>& original,
                std::size_t n, std::size_t batch, std::size_t pitch) {
  Errors worst;
  // Do not stop at the first bad plane or cell: inspect the entire output.
  for (std::size_t b = 0; b < batch; ++b) {
    double squared_error = 0, squared_reference = 0;
    double max_error = 0, peak = 0;
    bool finite = true;
    for (std::size_t y = 0; y < n; ++y) {
      for (std::size_t x = 0; x < n; ++x) {
        const double reference = original[y * n + x];
        const double actual = output[(b * n + y) * pitch + x];
        if (!std::isfinite(actual) || !std::isfinite(reference)) {
          finite = false;
          continue;
        }
        const double error = actual - reference;
        squared_error += error * error;
        squared_reference += reference * reference;
        max_error = std::max(max_error, std::abs(error));
        peak = std::max(peak, std::abs(reference));
      }
    }
    const double rms = finite && squared_reference > 0
                           ? std::sqrt(squared_error / squared_reference)
                           : std::numeric_limits<double>::infinity();
    const double relative_peak = finite && peak > 0
                                     ? max_error / peak
                                     : std::numeric_limits<double>::infinity();
    worst.rms = std::max(worst.rms, rms);
    worst.peak = std::max(worst.peak, relative_peak);
  }
  return worst;
}

void number(double value) {
  if (std::isfinite(value)) std::cout << value;
  else std::cout << "null";  // JSON has no NaN/Infinity literals.
}

bool call(int mode, int rep, bool warmup, std::size_t n, std::size_t batch,
          const std::vector<float>& original,
          const std::vector<float>& spectrum,
          const std::vector<const float*>& kernels,
          std::unique_ptr<Fft>& reused) {
  const double missing = std::numeric_limits<double>::quiet_NaN();
  double init_s = 0, submit_wait_s = missing, gpu_s = missing;
  Errors errors{missing, missing};
  bool passed = false;
  std::unique_ptr<Fft> fresh;
  try {
    Fft* fft = reused.get();
    if (mode == 0 || !fft) {
      const auto begin = Clock::now();
      auto& owner = mode == 0 ? fresh : reused;
      owner = std::make_unique<Fft>();
      fft = owner.get();
      const bool initialized = fft->initReal(n, n, batch);
      init_s = std::chrono::duration<double>(Clock::now() - begin).count();
      require(initialized, *fft, "initReal");
    }
    const std::size_t pitch = 2 * (n / 2 + 1);
    if (!fft->data() || fft->rowFloats() != pitch)
      throw std::runtime_error("unexpected real FFT buffer layout");
    if (mode == 2) {
      // Match submitConvolution's exact double-to-float normalization factor.
      const float factor = 1.0 / double(n * n);
      float* input = fft->data();
      for (std::size_t b = 0; b < batch; ++b)
        for (std::size_t i = 0; i < spectrum.size(); ++i)
          input[b * spectrum.size() + i] = spectrum[i] * factor;
    }
    const auto begin = Clock::now();
    const bool submitted = mode == 2 ? fft->submit()
                                    : fft->submitConvolution(spectrum.data(),
                                                             kernels.data());
    const bool completed = submitted && fft->wait();
    submit_wait_s = std::chrono::duration<double>(Clock::now() - begin).count();
    require(completed, *fft, "submit/wait");
    gpu_s = fft->gpuSeconds();
    errors = validate(fft->data(), original, n, batch, pitch);
    passed = std::isfinite(init_s) && init_s >= 0 &&
             std::isfinite(submit_wait_s) && submit_wait_s >= 0 &&
             std::isfinite(gpu_s) && gpu_s >= 0 &&
             std::isfinite(errors.rms) && std::isfinite(errors.peak) &&
             errors.rms <= kRmsLimit && errors.peak <= kPeakLimit;
  } catch (const std::exception& error) {
    std::cerr << kModes[mode] << " rep=" << rep << ": " << error.what() << '\n';
  }
  std::cout << "{\"mode\":\"" << kModes[mode] << "\",\"rep\":" << rep
            << ",\"warmup\":" << (warmup ? "true" : "false")
            << ",\"n\":" << n << ",\"batch\":" << batch << ",\"init_s\":";
  number(init_s);
  std::cout << ",\"submit_wait_s\":"; number(submit_wait_s);
  std::cout << ",\"gpu_s\":"; number(gpu_s);
  std::cout << ",\"relative_rms\":"; number(errors.rms);
  std::cout << ",\"max_rel_peak\":"; number(errors.peak);
  std::cout << ",\"synthetic_fixture\":true,\"passed\":"
            << (passed ? "true" : "false") << "}\n" << std::flush;
  if (!passed)
    std::cerr << "FAIL " << kModes[mode] << " rep=" << rep
              << ": finite output/timing and fixed error limits required\n";
  return passed;
  // fresh is destroyed here, outside init_s and submit_wait_s.
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc != 4)
      throw std::runtime_error("usage: gpu_fft_cost_probe n batch reps");
    const std::size_t n = argument(argv[1], 4096);
    const std::size_t batch = argument(argv[2], 8);
    const int reps = static_cast<int>(argument(argv[3], 20));
    if (n < 2 || n % 2)
      throw std::runtime_error("n must be even and in [2,4096]");
    std::cerr << "Synthetic delta-kernel FFT fixture; not real-MS science proof. "
                 "Excluded warmups use rep=-1. Limits: relative RMS<=1e-5, "
                 "max/peak<=1e-4 in every plane. Fresh teardown excluded.\n";
    const std::size_t pitch = 2 * (n / 2 + 1);
    const std::size_t plane_floats = pitch * n;
    std::vector<float> original(n * n), spectrum;
    std::uint32_t state = 0x6d2b79f5u;
    for (float& value : original) {
      // Exact bounded binary fractions; deterministic across standard libraries.
      state = state * 1664525u + 1013904223u;
      value = static_cast<float>(static_cast<int>(state >> 16) - 32768) / 32768.0f;
    }
    {
      Fft forward;
      require(forward.initReal(n, n), forward, "fixture initReal");
      if (!forward.data() || forward.rowFloats() != pitch)
        throw std::runtime_error("unexpected fixture layout");
      std::fill_n(forward.data(), plane_floats, 0.0f);
      for (std::size_t y = 0; y < n; ++y)
        std::copy_n(original.data() + y * n, n, forward.data() + y * pitch);
      require(forward.submitForward() && forward.wait(), forward, "fixture R2C");
      spectrum.assign(forward.data(), forward.data() + plane_floats);
      for (float value : spectrum)
        if (!std::isfinite(value)) throw std::runtime_error("nonfinite fixture spectrum");
    }
    // Separate allocations, not aliased pointers into one shared unity kernel.
    std::vector<std::vector<float>> kernel_storage(batch);
    std::vector<const float*> kernels(batch);
    for (std::size_t b = 0; b < batch; ++b) {
      kernel_storage[b].assign(plane_floats, 0.0f);
      for (std::size_t i = 0; i < plane_floats; i += 2)
        kernel_storage[b][i] = 1.0f;
      kernels[b] = kernel_storage[b].data();
    }
    std::cout << std::setprecision(17);
    std::array<std::unique_ptr<Fft>, 3> plans;
    for (int mode = 0; mode < 3; ++mode)
      if (!call(mode, -1, true, n, batch, original, spectrum, kernels, plans[mode]))
        return EXIT_FAILURE;
    // Every six reps balances each mode in each position and each pair ordering.
    constexpr int orders[6][3] = {
        {0, 1, 2}, {1, 2, 0}, {2, 0, 1},
        {2, 1, 0}, {1, 0, 2}, {0, 2, 1}};
    for (int rep = 0; rep < reps; ++rep)
      for (int mode : orders[rep % 6])
        if (!call(mode, rep, false, n, batch, original, spectrum, kernels, plans[mode]))
          return EXIT_FAILURE;
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "gpu_fft_cost_probe: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
