// Adjoint check: <gridAccumulate(v), G> == <v, gridDegrid(G)>.
// Catches grid/degrid convention mismatches (e.g. transposed grids).
#include "metal/metaldevice.h"

#include <cmath>
#include <complex>
#include <cstdio>
#include <random>
#include <vector>

int main() {
  constexpr std::size_t G = 352, supp = 8, nvis = 2000;
  std::mt19937_64 rng(20261020);
  std::uniform_real_distribution<double> uv(-115.0, 115.0);
  std::normal_distribution<double> nrm(0.0, 1.0);
  // Fake kernel coefficients (smooth blob); adjointness is kernel-independent.
  std::vector<float> coeff(supp * 4, 0.0f);
  // degree 3 polynomial approximating a blob per piece (values don't matter).
  for (std::size_t p = 0; p < supp; ++p) {
    coeff[p * 4 + 0] = 0.01f;
    coeff[p * 4 + 1] = 0.02f;
    coeff[p * 4 + 2] = 0.1f;
    coeff[p * 4 + 3] = 0.5f;
  }
  mx::metal::GridAccumInput in;
  in.grid_size = G;
  in.support = supp;
  in.kernel_degree = 3;
  in.kernel_coefficients = coeff;
  in.variant = mx::metal::Variant::kPoly;
  in.visibilities.resize(4 * nvis);
  std::vector<std::complex<double>> v(nvis);
  for (std::size_t k = 0; k < nvis; ++k) {
    const float u = static_cast<float>(uv(rng));
    const float vv = static_cast<float>(uv(rng));
    const double re = nrm(rng), im = nrm(rng);
    v[k] = {re, im};
    in.visibilities[4 * k + 0] = u;
    in.visibilities[4 * k + 1] = vv;
    in.visibilities[4 * k + 2] = static_cast<float>(re);
    in.visibilities[4 * k + 3] = static_cast<float>(im);
  }
  if (!mx::metal::deviceInfo().available) {
    std::printf("adjoint status=SKIP no-metal-device\n");
    return 0;
  }
  const mx::metal::GridAccumResult g = mx::metal::gridAccumulate(in);
  // Random grid.
  std::vector<float> grid(2 * G * G);
  std::vector<std::complex<double>> gg(G * G);
  for (std::size_t i = 0; i < G * G; ++i) {
    const double re = nrm(rng), im = nrm(rng);
    gg[i] = {re, im};
    grid[2 * i + 0] = static_cast<float>(re);
    grid[2 * i + 1] = static_cast<float>(im);
  }
  // u_v holds u,v per visibility (4 floats each).
  std::vector<float> uv_in(4 * nvis);
  for (std::size_t k = 0; k < nvis; ++k) {
    uv_in[4 * k + 0] = in.visibilities[4 * k + 0];
    uv_in[4 * k + 1] = in.visibilities[4 * k + 1];
  }
  const mx::metal::DegridResult d =
      mx::metal::gridDegrid(uv_in, grid, G, supp, coeff, 3);
  std::complex<double> lhs(0.0, 0.0), rhs(0.0, 0.0);
  for (std::size_t i = 0; i < G * G; ++i) {
    const double gr = static_cast<double>(g.grid[2 * i + 0]);
    const double gi = static_cast<double>(g.grid[2 * i + 1]);
    lhs += std::conj(std::complex<double>(gr, gi)) * gg[i];
  }
  for (std::size_t k = 0; k < nvis; ++k) {
    const double ur = static_cast<double>(d.values[2 * k + 0]);
    const double ui = static_cast<double>(d.values[2 * k + 1]);
    rhs += std::conj(v[k]) * std::complex<double>(ur, ui);
  }
  const double denom = std::abs(lhs);
  const double rel = denom > 0.0 ? std::abs(lhs - rhs) / denom : 0.0;
  std::printf("adjoint <Gv,w>=%.6g <v,Dw>=%.6g rel=%.4g status=%s\n", std::abs(lhs), std::abs(rhs),
              rel, rel < 1e-4 ? "PASS" : "FAIL");
  return rel < 1e-4 ? 0 : 1;
}
