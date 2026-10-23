// SPDX-License-Identifier: GPL-3.0-or-later
// Differential oracle: materialize float products, then use existing public scans.
#include "math/peak_finder.h"
#include <aocommon/image.h>
#include <aocommon/uvector.h>
#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace pf = radler::math::peak_finder;
using Number = aocommon::OptionalNumber<float>;
struct Peak { Number value; size_t x, y; };
volatile float sink = 0;

Peak Reference(const float* image, const float* weights, size_t w, size_t h,
               bool negative, size_t start, size_t end, const bool* mask,
               size_t xb, size_t yb) {
  aocommon::Image scratch(w, h);
  for (size_t i = 0; i != w*h; ++i) scratch[i] = image[i] * weights[i];
  Peak p;
  p.value = mask ? pf::FindWithMask(scratch.Data(), w, h, p.x, p.y, negative,
                                   start, end, mask, xb, yb)
                 : pf::Simple(scratch.Data(), w, h, p.x, p.y, negative,
                              start, end, xb, yb);
  return p;
}
Peak Candidate(const float* image, const float* weights, size_t w, size_t h,
               bool negative, size_t start, size_t end, const bool* mask,
               size_t xb, size_t yb) {
  Peak p;
  p.value = pf::SimpleWeighted(image, weights, w, h, p.x, p.y, negative,
                               start, end, mask, xb, yb);
  return p;
}
bool Same(const Peak& a, const Peak& b) {
  return bool(a.value) == bool(b.value) && a.x == b.x && a.y == b.y &&
    (!a.value || std::bit_cast<uint32_t>(*a.value) == std::bit_cast<uint32_t>(*b.value));
}
int main(int argc, char** argv) {
  std::mt19937 rng(731);
  std::uniform_real_distribution<float> noise(-8, 8), weight(-2, 2);
  size_t checks = 0, failures = 0;
  const float special[] = {0.0f, -0.0f, std::numeric_limits<float>::denorm_min(),
    std::numeric_limits<float>::min(), -std::numeric_limits<float>::min(),
    std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(),
    std::numeric_limits<float>::quiet_NaN(), 1.0f, -1.0f};
  for (size_t w : {1, 7, 8, 9, 31, 32, 33, 63, 64, 65}) {
    for (size_t h : {1, 3, 17}) {
      for (int data_case = 0; data_case != 14; ++data_case) {
        aocommon::Image image(w,h), weights(w,h);
        aocommon::UVector<bool> mask(w*h);
        for (size_t i=0; i!=w*h; ++i) {
          image[i] = data_case < 10 ? special[data_case] : noise(rng);
          weights[i] = data_case == 10 ? special[i%10] : data_case == 11 ? 1.0f : weight(rng);
          mask[i] = data_case == 12 ? false : i%3 != 0;
        }
        if (data_case == 13) {
          image = 0.0f; weights = 1.0f;
          image[w*h/3] = -100; image[w*h-1] = 100; // signed, cross-row ties
        }
        const aocommon::Image before_image(image), before_weights(weights);
        for (bool negative : {false,true}) for (bool masked : {false,true}) {
          for (size_t border : {size_t(0),size_t(1),w/2}) {
            const size_t xb = std::min(border,w), yb = std::min(border,h);
            for (bool partial : {false,true}) {
              const size_t start = partial ? h/2 : 0, end = partial ? h-1 : h;
              Peak a = Reference(image.Data(),weights.Data(),w,h,negative,start,end,
                                 masked?mask.data():nullptr,xb,yb);
              Peak b = Candidate(image.Data(),weights.Data(),w,h,negative,start,end,
                                 masked?mask.data():nullptr,xb,yb);
              ++checks;
              if (!Same(a,b)) {
                ++failures;
                if (failures<8) std::cerr << "Mismatch " << w << 'x' << h
                  << " case=" << data_case << " negative=" << negative
                  << " masked=" << masked << " border=" << border << '\n';
              }
            }
          }
        }
        if (std::memcmp(image.Data(),before_image.Data(),w*h*sizeof(float)) ||
            std::memcmp(weights.Data(),before_weights.Data(),w*h*sizeof(float))) ++failures;
      }
    }
  }
  // Exact products differ but round to one: comparing a wider intermediate
  // would incorrectly choose the later pixel across the eight-lane boundary.
  {
    aocommon::Image image(33, 2, 0.0f), weights(33, 2, 1.0f);
    aocommon::UVector<bool> mask(66, true);
    image[7] = -1.0f;
    image[8] = std::nextafter(1.0f, 2.0f);
    weights[8] = std::nextafter(1.0f, 0.0f);
    for (const bool* selected_mask : {static_cast<const bool*>(nullptr),
                                      static_cast<const bool*>(mask.data())}) {
      const Peak p = Candidate(image.Data(), weights.Data(), 33, 2, true,
                               0, 2, selected_mask, 0, 0);
      ++checks;
      if (!p.value || *p.value != -1.0f || p.x != 7 || p.y != 0) ++failures;
    }
    image = 0.0f; weights = 1.0f;
    image[7] = std::numeric_limits<float>::min();
    image[8] = -std::numeric_limits<float>::min();
    Peak p = Candidate(image.Data(), weights.Data(), 33, 2, true, 0, 2,
                       nullptr, 0, 0);
    ++checks;
    if (p.value || p.x != 33 || p.y != 2) ++failures;
    image[32] = std::nextafter(std::numeric_limits<float>::min(), 1.0f);
    image[33] = -image[32];
    p = Candidate(image.Data(), weights.Data(), 33, 2, true, 0, 2,
                   mask.data(), 0, 0);
    ++checks;
    if (!p.value || *p.value != image[32] || p.x != 32 || p.y != 0) ++failures;
  }
  std::cout << "weighted differential checks=" << checks << " failures=" << failures << '\n';
  if (failures || argc == 1) return failures ? 1 : 0;
  if (argc != 3 || std::string(argv[1]) != "--benchmark") return 2;
  const size_t w = std::stoul(argv[2]), h = w;
  if (w != 3072 && w != 4096) return 2;
  aocommon::Image image(w,h), weights(w,h);
  aocommon::UVector<bool> mask(w*h);
  for(size_t i=0;i!=w*h;++i) {
    image[i]=noise(rng); weights[i]=std::fabs(weight(rng)); mask[i]=i%3!=0;
  }
  for (bool masked : {false,true}) {
    const bool* m = masked ? mask.data() : nullptr;
    if (!Same(Reference(image.Data(),weights.Data(),w,h,true,0,h,m,8,8),
              Candidate(image.Data(),weights.Data(),w,h,true,0,h,m,8,8))) return 1;
    for (int rep=0;rep!=9;++rep) for(int j=0;j!=2;++j) {
      const bool candidate = (j==0) != (rep%2==0);
      auto start = std::chrono::steady_clock::now();
      const Peak p = candidate ? Candidate(image.Data(),weights.Data(),w,h,true,0,h,m,8,8)
                               : Reference(image.Data(),weights.Data(),w,h,true,0,h,m,8,8);
      const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
      sink=p.value.ValueOr(0.0f);
      std::cout << "timing," << w << ',' << masked << ',' << rep << ',' << candidate << ',' << ms << '\n';
    }
  }
}
