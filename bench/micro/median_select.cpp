// Bitwise check and timing of aocommon's median/MAD against the original
// std::nth_element implementation.
//
//   c++ -std=c++17 -O3 -march=native -ffast-math -I work/aocommon/include \
//       bench/micro/median_select.cpp -o bench/micro/bin/median_select

#include <aocommon/image.h>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <random>

namespace reference {

template <typename NumT>
NumT MedianWithCopy(const NumT* data, size_t size, aocommon::UVector<NumT>& copy) {
  copy.reserve(size);
  for (const NumT* i = data; i != data + size; ++i) {
    if (std::isfinite(*i)) copy.push_back(*i);
  }
  if (copy.empty()) return 0.0;
  bool even = (copy.size() % 2) == 0;
  auto mid = copy.begin() + (copy.size() - 1) / 2;
  std::nth_element(copy.begin(), mid, copy.end());
  NumT median = *mid;
  if (even) {
    std::nth_element(mid, mid + 1, copy.end());
    median = (median + *(mid + 1)) * 0.5;
  }
  return median;
}

template <typename NumT>
std::pair<NumT, NumT> Mad(const NumT* data, size_t size) {
  aocommon::UVector<NumT> copy;
  const NumT median = MedianWithCopy(data, size, copy);
  if (copy.empty()) return {0.0, 0.0};
  auto mid = copy.begin() + (copy.size() - 1) / 2;
  for (auto i = copy.begin(); i != mid + 1; ++i) *i = median - *i;
  for (auto i = mid + 1; i != copy.end(); ++i) *i = *i - median;
  std::nth_element(copy.begin(), mid, copy.end());
  NumT mad = *mid;
  if ((copy.size() % 2) == 0) {
    std::nth_element(mid, mid + 1, copy.end());
    mad = (mad + *(mid + 1)) * 0.5;
  }
  return {median, mad};
}

}  // namespace reference

size_t signed_zero_differences = 0;

// std::nth_element may return either of -0 and +0 when both occur at the
// selected rank, so a zero median's sign is not part of the contract.
template <typename NumT>
bool SameBits(NumT a, NumT b) {
  if (std::memcmp(&a, &b, sizeof(NumT)) == 0) return true;
  if (a == NumT(0) && b == NumT(0)) {
    ++signed_zero_differences;
    return true;
  }
  return false;
}

template <typename NumT>
bool Check(const char* name, const std::vector<NumT>& data) {
  const auto ref = reference::Mad(data.data(), data.size());
  const auto test = aocommon::detail::MadImplementation(data.data(), data.size());
  const bool ok = SameBits(ref.first, test.first) && SameBits(ref.second, test.second);
  if (!ok) {
    std::printf("MISMATCH %s n=%zu: median %.9g vs %.9g, mad %.9g vs %.9g\n", name, data.size(),
                double(ref.first), double(test.first), double(ref.second),
                double(test.second));
  }
  return ok;
}

template <typename NumT>
size_t RunChecks(std::mt19937_64& rng) {
  size_t failures = 0;
  std::normal_distribution<double> normal(0.0, 1.0);
  for (size_t n : {1, 2, 3, 4, 5, 10, 11, 1000, 1001, 65536, 65537, 1000000, 1000001}) {
    std::vector<NumT> data(n);
    for (NumT& v : data) v = normal(rng) * 2.5e-5 - 1.6e-6;
    failures += !Check("normal", data);
    for (NumT& v : data) v = std::round(normal(rng) * 3.0);
    failures += !Check("duplicates", data);
    for (size_t i = 0; i != n; ++i) data[i] = (i % 3 == 0) ? normal(rng) : 0.0;
    failures += !Check("mostly-zero", data);
    for (size_t i = 0; i != n; ++i) data[i] = (i % 2 == 0) ? -0.0 : 0.0;
    failures += !Check("signed-zeros", data);
    for (NumT& v : data) v = std::exp(normal(rng) * 20.0) * (normal(rng) < 0 ? -1 : 1);
    failures += !Check("wide-range", data);
    for (size_t i = 0; i != n; ++i)
      data[i] = (i % 7 == 0) ? std::numeric_limits<NumT>::quiet_NaN() : normal(rng);
    failures += !Check("with-nan", data);
  }
  return failures;
}

int main() {
  std::mt19937_64 rng(42);
  const size_t failures = RunChecks<float>(rng) + RunChecks<double>(rng);
  std::printf("bitwise checks: %s (%zu failures, %zu zero medians differing only in sign)\n",
              failures ? "FAIL" : "PASS", failures, signed_zero_differences);

  const size_t n = 4096 * 4096;
  std::vector<float> image(n);
  std::normal_distribution<float> normal(0.0f, 2.5e-5f);
  for (float& v : image) v = normal(rng);
  for (size_t i = 0; i < n; i += 997) image[i] += 1e-3f;
  for (int rep = 0; rep != 3; ++rep) {
    auto t0 = std::chrono::steady_clock::now();
    const auto ref = reference::Mad(image.data(), n);
    auto t1 = std::chrono::steady_clock::now();
    const auto test = aocommon::detail::MadImplementation(image.data(), n);
    auto t2 = std::chrono::steady_clock::now();
    std::printf("4096^2 MAD: nth_element %.1f ms, radix %.1f ms, identical=%d\n",
                std::chrono::duration<double, std::milli>(t1 - t0).count(),
                std::chrono::duration<double, std::milli>(t2 - t1).count(),
                SameBits(ref.first, test.first) && SameBits(ref.second, test.second));
  }
  return failures ? 1 : 0;
}
