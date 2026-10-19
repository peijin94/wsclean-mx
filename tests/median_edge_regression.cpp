// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Numerical edge cases of the patched aocommon median (radix-histogram select
// instead of full nth_element).
//
// These pin INHERITED upstream semantics that this project deliberately does
// not change: they are documentation-by-test, so that a future change to the
// selection or the averaging becomes a visible decision instead of an accident.
#include <cfloat>
#include <cmath>
#include <iostream>
#include <limits>

#include <aocommon/image.h>

int main() {
  size_t failures = 0;

  // (1) Even-count median of two huge finite values overflows through the
  // inherited (a + b) * 0.5 averaging. Upstream computes the same expression,
  // so this is recorded, not fixed.
  {
    const float huge = std::numeric_limits<float>::max();
    const float data[2] = {huge, huge};
    const float median = aocommon::Image::Median(data, 2);
    const bool overflowed = std::isinf(median);
    std::cout << "(1) even median of two FLT_MAX: " << median
              << (overflowed ? " (inf, inherited overflow)" : " (finite)")
              << ' ' << (overflowed ? "PASS" : "FAIL") << '\n';
    failures += !overflowed;
  }

  // (2) Where no overflow occurs, the radix selection must still return the
  // exact average of the two middle values, i.e. bitwise the same element the
  // nth_element version averaged.
  {
    const float a = 1.0e38f;
    const float b = a + 4.0e30f;
    const float data[2] = {a, b};
    const float median = aocommon::Image::Median(data, 2);
    const float expected = (a + b) * 0.5f;
    const bool good = (median == expected) && std::isfinite(median);
    std::cout << "(2) even median of a large finite pair: " << median
              << " expected " << expected << ' ' << (good ? "PASS" : "FAIL") << '\n';
    failures += !good;
  }

  // (3) Non-finite values are filtered before selection (inherited filter), so
  // an image with infinities and NaNs medians over its finite values only.
  {
    const float data[4] = {1.0f, std::numeric_limits<float>::infinity(),
                           std::numeric_limits<float>::quiet_NaN(), 3.0f};
    const float median = aocommon::Image::Median(data, 4);
    const bool good = median == 2.0f;
    std::cout << "(3) median ignoring non-finite values: " << median
              << " expected 2 " << (good ? "PASS" : "FAIL") << '\n';
    failures += !good;
  }

  // (4) Subnormal-only data: the median of a set whose values are all subnormal
  // must be subnormal, not flushed to zero, and it must equal the value an
  // independent selection of the middle element produces.
  {
    const float denormal = std::numeric_limits<float>::denorm_min() * 8.0f;
    const float data[3] = {denormal * 3.0f, denormal, denormal * 2.0f};
    const float median = aocommon::Image::Median(data, 3);
    const bool good = (median == denormal * 2.0f) && (median > 0.0f);
    std::cout << "(4) median of subnormal-only data: " << median
              << " expected " << denormal * 2.0f << ' ' << (good ? "PASS" : "FAIL") << '\n';
    failures += !good;
  }

  // (5) Median-and-MAD on subnormal-only data keeps both values subnormal
  // (the MAD path reuses the selection after subtracting the median).
  {
    const float denormal = std::numeric_limits<float>::denorm_min() * 8.0f;
    const float data[3] = {denormal, denormal * 3.0f, denormal * 2.0f};
    aocommon::Image copy(3, 1, 0.0f);
    for (size_t i = 0; i != 3; ++i) copy[i] = data[i];
    const std::pair<float, float> median_and_mad = copy.MedianAndMAD();
    const bool good = median_and_mad.first == denormal * 2.0f &&
                      median_and_mad.second == denormal && median_and_mad.second > 0.0f;
    std::cout << "(5) subnormal median/MAD: " << median_and_mad.first << " / "
              << median_and_mad.second << " expected " << denormal * 2.0f << " / " << denormal
              << ' ' << (good ? "PASS" : "FAIL") << '\n';
    failures += !good;
  }

  std::cout << "median edge cases: " << failures << " failure(s) of 5\n";
  return failures ? 1 : 0;
}
