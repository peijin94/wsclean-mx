// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Real-header regression for fundamental and extended allocation alignment.
#include <aocommon/multiarray.h>
#include <complex>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace {
size_t checks = 0, failures = 0;
void Check(bool value, const char* message) {
  ++checks;
  if (!value) throw std::runtime_error(message);
}
struct alignas(64) Extended {
  int value;
  bool operator==(const Extended&) const = default;
};

template <typename T>
void Single(const char* name) {
  try {
    aocommon::MultiArray<T> empty(0);
    Check(empty.Size() == 0 && empty.ByteLength() == 0, "empty allocation changed");
    aocommon::MultiArray<T> values(3);
    Check(values.ByteLength() == 3 * sizeof(T), "logical byte length changed");
    Check(reinterpret_cast<uintptr_t>(values.template Get<0>()) % alignof(T) == 0,
          "allocated pointer is misaligned");
    Check(values.template Get<0>()[0] == T{}, "value initialization changed");
    values.template Get<0>()[1] = T(7);
    aocommon::MultiArray<T> copy(values);
    Check(copy.template Get<0>()[1] == T(7), "copy lost contents");
    aocommon::MultiArray<T> moved(std::move(copy));
    Check(copy.Size() == 0 && moved.template Get<0>()[1] == T(7), "move changed contents");
    moved.Resize(5);
    Check(moved.template Get<0>()[1] == T(7), "resize lost contents");
    Check(moved.template Get<0>()[4] == T{}, "resize did not value-initialize extension");
    moved.Resize(2);
    Check(moved.Size() == 2 && moved.template Get<0>()[1] == T(7), "shrink failed");
    moved.Clear();
    Check(moved.Size() == 0 && moved.ByteLength() == 0, "clear failed");
    aocommon::MultiArray<T> skipped(3, aocommon::kSkipInitialization);
    for (auto& value : skipped.template Span<0>()) value = T(7);
    Check(skipped.template Get<0>()[2] == T(7), "skip-initialization storage failed");
    std::cout << name << " PASS\n";
  } catch (const std::exception& error) {
    ++failures;
    std::cerr << name << " FAIL: " << error.what() << '\n';
  }
}
}

int main() {
  Single<bool>("bool");
  Single<char>("char");
  Single<float>("float");
  Single<double>("double");
  Single<Extended>("alignas(64)");
  try {
    using Row = aocommon::MultiArray<std::complex<float>, std::complex<float>, float>;
    Row row(6);
    Check(row.ByteLength() == 120, "visibility/model/weight layout changed");
    Check(row.Get<0>()[0] == std::complex<float>{} && row.Get<1>()[0] == std::complex<float>{}
              && row.Get<2>()[0] == 0.0f, "mixed value initialization changed");
    row.Get<0>()[2] = {3.0f, -4.0f};
    row.Get<1>()[2] = {5.0f, 6.0f};
    row.Get<2>()[2] = 7.0f;
    Row copy(row);
    copy.Resize(9);
    Check(copy.Get<0>()[2] == std::complex<float>(3.0f, -4.0f) &&
              copy.Get<1>()[2] == std::complex<float>(5.0f, 6.0f) && copy.Get<2>()[2] == 7.0f,
          "mixed copy/resize lost contents");
    Check(copy.Get<0>()[8] == std::complex<float>{} && copy.Get<2>()[8] == 0.0f,
          "mixed extension not initialized");
    std::cout << "visibility/model/weights PASS\n";
  } catch (const std::exception& error) {
    ++failures;
    std::cerr << "visibility/model/weights FAIL: " << error.what() << '\n';
  }
  std::cout << checks << " assertions, " << failures << " failing layouts\n";
  return failures ? 1 : 0;
}
