// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// Extracts ducc0's fitted gridding kernel for the w-gridder's accuracy class
// and validates the evaluation convention the Metal kernel uses.
//
// ducc0 approximates its ES kernel with W piecewise polynomials of degree D in
// the local coordinate; its wgridder evaluates exactly those polynomials (not
// exp/pow). The Metal kernel must reproduce that evaluation, so this tool:
//   1. replicates ducc0's kernel-database selection (smallest support W with
//      ndim, single precision, ofactor and epsilon at least as good as asked),
//   2. writes W, D and the W*(D+1) coefficients in the layout
//      coeff[nth*(D+1) + j] (interval-major monomial coefficients in locx),
//   3. re-evaluates the kernel from the written numbers with the same
//      interval/local-coordinate convention the Metal shader uses, and compares
//      it against ducc0's own PolynomialKernel::eval on a dense x grid.
//
// Build/run through scripts/metal_kernel_coeffs.sh.

#include "ducc0/math/gridding_kernel.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {

struct Selected {
  std::size_t index = 0;
  std::size_t support = 0;
  std::size_t degree = 0;
  std::vector<double> coefficients_double;  // as fitted
  std::vector<float> coefficients;          // as the float32 kernels store them
  std::shared_ptr<ducc0::detail_gridding_kernel::PolynomialKernel> kernel;
};

// Mirrors ducc0's selectKernel<T>(ofactor, ndim, epsilon): smallest W that
// meets the accuracy class, in single precision (what wsclean builds).
Selected selectKernel(double ofactor, std::size_t ndim, double epsilon) {
  // Exactly ducc0's loop (their selectKernel<T>): among rows meeting the
  // accuracy class the LAST one with the smallest support wins, so replicating
  // the <= comparison matters - several rows can share (W, ofactor, ndim,
  // singleprec) with different beta/e0 fits.
  const auto &db = ducc0::detail_gridding_kernel::KernelDB;
  std::size_t best = db.size();
  std::size_t best_w = ducc0::detail_gridding_kernel::Wmax<float>();  // as ducc0 does
  for (std::size_t i = 0; i < db.size(); ++i) {
    const auto &entry = db[i];
    if (entry.ndim == ndim && entry.singleprec && entry.ofactor <= ofactor &&
        entry.epsilon <= epsilon && entry.W <= best_w) {
      best = i;
      best_w = entry.W;
    }
  }
  if (best == db.size()) {
    std::fprintf(stderr, "no kernel in the database matches the request\n");
    std::exit(2);
  }
  Selected result;
  result.index = best;
  result.kernel = ducc0::detail_gridding_kernel::selectKernel(best);
  result.support = result.kernel->support();
  result.degree = result.kernel->degree();
  result.coefficients_double = result.kernel->Coeff();
  result.coefficients.assign(result.coefficients_double.begin(),
                             result.coefficients_double.end());
  return result;
}

// The convention the Metal shader implements, evaluated in double here.
template <typename T>
double evaluate(const std::vector<T> &coefficients, std::size_t support,
                std::size_t degree, double x_normalised) {
  if (std::fabs(x_normalised) >= 1.0) return 0.0;
  const double xrel = 0.5 * static_cast<double>(support) * (x_normalised + 1.0);
  long nth = static_cast<long>(xrel);
  if (nth > static_cast<long>(support) - 1) nth = static_cast<long>(support) - 1;
  const double locx = ((xrel - static_cast<double>(nth)) - 0.5) * 2.0;
  const std::size_t ofs = static_cast<std::size_t>(nth) * (degree + 1);
  double value = static_cast<double>(coefficients[ofs]);
  for (std::size_t i = 1; i <= degree; ++i) {
    value = value * locx + static_cast<double>(coefficients[ofs + i]);
  }
  return value;
}

}  // namespace

int main(int argc, char** argv) {
  double ofactor = 2.0, epsilon = 1.0e-7;
  std::size_t ndim = 3;
  std::string out;
  for (int i = 1; i < argc; ++i) {
    const std::string argument = argv[i];
    auto value = [&](const char* name) -> const char* {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "%s needs a value\n", name);
        std::exit(2);
      }
      return argv[++i];
    };
    if (argument == "--ofactor") {
      ofactor = std::strtod(value("--ofactor"), nullptr);
    } else if (argument == "--epsilon") {
      epsilon = std::strtod(value("--epsilon"), nullptr);
    } else if (argument == "--ndim") {
      ndim = std::strtoull(value("--ndim"), nullptr, 10);
    } else if (argument == "--out") {
      out = value("--out");
    } else {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 2;
    }
  }
  if (out.empty()) {
    std::fprintf(stderr, "usage: ducc0_kernel_tool --out FILE [--ofactor F] "
                         "[--epsilon E] [--ndim N]\n");
    return 2;
  }

  const Selected kernel = selectKernel(ofactor, ndim, epsilon);

  // Two checks against ducc0's own evaluation:
  //  * convention: with the double-precision coefficients, the interval/local
  //    coordinate/Horner convention the shader uses must reproduce ducc0's
  //    polynomial exactly (rounding-level agreement);
  //  * storage: with the float32 coefficients the shader will actually carry,
  //    the deviation is the float32 storage level - which is also what ducc0's
  //    own float kernels store (their TemplateKernel casts to T = float).
  double worst_convention = 0.0, worst_storage = 0.0, peak = 0.0;
  for (int i = 0; i <= 200000; ++i) {
    const double x = -1.05 + 2.1 * static_cast<double>(i) / 200000.0;
    const double reference = kernel.kernel->eval(x);
    worst_convention = std::max(
        worst_convention,
        std::fabs(evaluate(kernel.coefficients_double, kernel.support, kernel.degree, x) - reference));
    worst_storage = std::max(
        worst_storage,
        std::fabs(evaluate(kernel.coefficients, kernel.support, kernel.degree, x) - reference));
    peak = std::max(peak, std::fabs(reference));
  }

  FILE* file = std::fopen(out.c_str(), "w");
  if (file == nullptr) {
    std::fprintf(stderr, "cannot write %s\n", out.c_str());
    return 2;
  }
  std::fprintf(file, "# ducc0 gridding kernel: ofactor %.6g ndim %zu epsilon %.6g\n",
               ofactor, ndim, epsilon);
  const auto &row = ducc0::detail_gridding_kernel::getKernel(kernel.index);
  std::fprintf(file, "support %zu\n", kernel.support);
  std::fprintf(file, "beta_norm %.17g\n", row.beta);
  std::fprintf(file, "e0 %.17g\n", row.e0);
  std::fprintf(file, "degree %zu\n", kernel.degree);
  std::fprintf(file, "coefficients %zu\n", kernel.coefficients.size());
  for (std::size_t nth = 0; nth < kernel.support; ++nth) {
    std::fprintf(file, "interval %zu", nth);
    for (std::size_t j = 0; j <= kernel.degree; ++j) {
      std::fprintf(file, " %.9g", static_cast<double>(kernel.coefficients[nth * (kernel.degree + 1) + j]));
    }
    std::fprintf(file, "\n");
  }
  std::fclose(file);

  // The row's own kernel parameters: the analytic formula the polynomial
  // approximates uses beta_norm * support and e0, so they must be reported (and
  // must match whatever the harness hard-codes) or a fit-error comparison
  // silently compares two different kernels.
  const auto &parameters = ducc0::detail_gridding_kernel::getKernel(kernel.index);
  std::printf("ducc0_kernel index=%zu support=%zu degree=%zu coefficients=%zu ofactor=%.3f "
              "ndim=%zu epsilon=%.3g beta_norm=%.17g e0=%.17g row_epsilon=%.6g\n",
              kernel.index, kernel.support, kernel.degree, kernel.coefficients.size(), ofactor,
              ndim, epsilon, parameters.beta, parameters.e0, parameters.epsilon);
  const bool convention_ok = worst_convention <= 1e-12 * std::max(peak, 1e-30);
  const bool storage_ok = worst_storage <= 1.0e-6 * std::max(peak, 1e-30);
  std::printf("convention_check points=200001 max_abs_diff=%.3g peak=%.6g status=%s\n",
              worst_convention, peak, convention_ok ? "PASS" : "FAIL");
  std::printf("storage_check points=200001 max_abs_diff=%.3g peak=%.6g tolerance=1e-06 "
              "status=%s\n",
              worst_storage, peak, storage_ok ? "PASS" : "FAIL");
  std::printf("wrote %s\n", out.c_str());
  return (convention_ok && storage_ok) ? 0 : 1;
}
