// SPDX-License-Identifier: LGPL-3.0-only
// Copyright (C) 2026 Peijin Zhang
// Adapted from radler's SubMinorLoop, Copyright (C) ASTRON (Netherlands
// Institute for Radio Astronomy), LGPL-3.0-only.
// Single-threaded timing of radler's subminor loop body (PSF subtraction over
// the selected pixels + peak search): upstream's version (copy to scratch, then
// search) against searching the residual in place, with size_t and 32-bit
// positions. Random data, so the PSF gathers are less cache friendly than in a
// real run.
//
//   c++ -O3 -march=native -std=c++20 bench/micro/subminor_loop.cpp -o /tmp/subminor_loop
//   /tmp/subminor_loop [size=2048] [density=0.03] [iterations=4000]

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <utility>
#include <vector>

template <typename Coord>
struct Data {
  size_t width, height;
  std::vector<float> psf;
  std::vector<std::pair<Coord, Coord>> positions;
  std::vector<float> residual;
};

template <typename Coord>
Data<Coord> Make(size_t size, double density) {
  Data<Coord> d{size, size, std::vector<float>(size * size), {}, {}};
  std::mt19937 rng(42);
  std::normal_distribution<float> normal;
  std::uniform_real_distribution<double> uniform;
  for (float& v : d.psf) v = 0.01f * normal(rng);
  d.psf[size / 2 + (size / 2) * size] = 1.0f;
  for (size_t y = 0; y != size; ++y)
    for (size_t x = 0; x != size; ++x)
      if (uniform(rng) < density) {
        d.positions.emplace_back(x, y);
        d.residual.push_back(normal(rng));
      }
  return d;
}

// Upstream: subtract, copy to scratch (GetLinearIntegrated), search.
template <typename Coord>
double Upstream(Data<Coord> d, size_t iterations, size_t& checksum) {
  const size_t n = d.positions.size();
  std::vector<float> scratch(n);
  auto max_component = [&](float& max_value) {
    scratch = d.residual;
    size_t max_component = 0;
    max_value = scratch[0];
    for (size_t i = 0; i != n; ++i) {
      const float value = std::fabs(scratch[i]);
      if (value > max_value) {
        max_component = i;
        max_value = value;
      }
    }
    max_value = scratch[max_component];
    return max_component;
  };
  float max_value;
  size_t peak = max_component(max_value);
  const auto start = std::chrono::steady_clock::now();
  for (size_t it = 0; it != iterations; ++it) {
    const size_t x = d.positions[peak].first, y = d.positions[peak].second;
    const float factor = d.residual[peak] * 0.1f;
    float* image = d.residual.data();
    for (size_t px = 0; px != n; ++px) {
      int psf_x = d.positions[px].first - x + d.width / 2;
      int psf_y = d.positions[px].second - y + d.height / 2;
      if (psf_x >= 0 && psf_x < int(d.width) && psf_y >= 0 && psf_y < int(d.height))
        image[px] -= d.psf[psf_x + psf_y * d.width] * factor;
    }
    peak = max_component(max_value);
    checksum += peak;
  }
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

// mx-p5: subtract in place, then search the residual directly.
template <typename Coord>
double Mx(Data<Coord> d, size_t iterations, size_t& checksum) {
  const size_t n = d.positions.size();
  auto search = [&]() {
    size_t best_index = 0;
    float best = std::fabs(d.residual[0]);
    for (size_t px = 0; px != n; ++px) {
      const float value = std::fabs(d.residual[px]);
      if (value > best) {
        best_index = px;
        best = value;
      }
    }
    return best_index;
  };
  size_t peak = search();
  const auto start = std::chrono::steady_clock::now();
  for (size_t it = 0; it != iterations; ++it) {
    const size_t x = d.positions[peak].first, y = d.positions[peak].second;
    const float factor = d.residual[peak] * 0.1f;
    float* image = d.residual.data();
    const float* psf = d.psf.data();
    const std::pair<Coord, Coord>* positions = d.positions.data();
    for (size_t px = 0; px != n; ++px) {
      const int psf_x = positions[px].first - x + d.width / 2;
      const int psf_y = positions[px].second - y + d.height / 2;
      if (psf_x >= 0 && psf_x < int(d.width) && psf_y >= 0 && psf_y < int(d.height))
        image[px] -= psf[psf_x + psf_y * d.width] * factor;
    }
    peak = search();
    checksum += peak;
  }
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

int main(int argc, char** argv) {
  const size_t size = argc > 1 ? atoi(argv[1]) : 2048;
  const double density = argc > 2 ? atof(argv[2]) : 0.03;
  const size_t iterations = argc > 3 ? atoi(argv[3]) : 4000;
  const Data<size_t> d64 = Make<size_t>(size, density);
  const Data<uint32_t> d32 = Make<uint32_t>(size, density);
  printf("size %zu, %zu selected pixels, %zu iterations\n", size, d64.positions.size(),
         iterations);
  for (int rep = 0; rep != 2; ++rep) {
    size_t c1 = 0, c2 = 0, c3 = 0, c4 = 0;
    const double t1 = Upstream(d64, iterations, c1);
    const double t2 = Upstream(d32, iterations, c2);
    const double t3 = Mx(d64, iterations, c3);
    const double t4 = Mx(d32, iterations, c4);
    printf("upstream size_t %.3f s | upstream uint32 %.3f s | mx size_t %.3f s | mx uint32 %.3f s"
           "  (checksums %s)\n",
           t1, t2, t3, t4, (c1 == c2 && c2 == c3 && c3 == c4) ? "equal" : "DIFFER");
  }
}
