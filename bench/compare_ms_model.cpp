// Read-only, bounded-memory comparison of complete MODEL_DATA columns.
#include <casacore/tables/Tables/Table.h>
#include <casacore/tables/Tables/ArrayColumn.h>
#include <casacore/casa/Arrays/Slicer.h>
#include <casacore/casa/Arrays/IPosition.h>
#include <algorithm>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <stdexcept>

int main(int argc, char** argv) {
  if (argc != 3) { std::cerr << "usage: compare_ms_model reference.ms candidate.ms\n"; return 2; }
  try {
    using namespace casacore;
    Table ref(argv[1], Table::Old), test(argv[2], Table::Old);
    if (ref.nrow() != test.nrow()) throw std::runtime_error("row count mismatch");
    ROArrayColumn<Complex> ca(ref, "MODEL_DATA"), cb(test, "MODEL_DATA");
    double energy = 0, error = 0, peak = 0, maxdiff = 0;
    size_t count = 0, different = 0;
    for (size_t row = 0; row < ref.nrow(); row += 4096) {
      const size_t n = std::min<size_t>(4096, ref.nrow() - row);
      const Slicer rows(IPosition(1, row), IPosition(1, n), Slicer::endIsLength);
      Array<Complex> a, b;
      ca.getColumnRange(rows, a, true); cb.getColumnRange(rows, b, true);
      if (a.shape() != b.shape()) throw std::runtime_error("MODEL_DATA shape mismatch");
      auto ai = a.cbegin(), bi = b.cbegin();
      for (; ai != a.cend(); ++ai, ++bi) {
        const std::complex<double> x(ai->real(), ai->imag()), y(bi->real(), bi->imag());
        if (!std::isfinite(x.real()) || !std::isfinite(x.imag()) ||
            !std::isfinite(y.real()) || !std::isfinite(y.imag()))
          throw std::runtime_error("nonfinite MODEL_DATA");
        energy += std::norm(x); error += std::norm(y-x);
        peak = std::max(peak, std::abs(x)); maxdiff = std::max(maxdiff, std::abs(y-x));
        different += x != y; ++count;
      }
    }
    if (count == 0 || energy == 0 || peak == 0)
      throw std::runtime_error("empty or zero reference is not a prediction test");
    const double relative = std::sqrt(error / energy), relative_peak = maxdiff / peak;
    const bool pass = relative <= 5e-6 && relative_peak <= 1e-4;
    std::cout << std::setprecision(17)
              << "{\"rows\":" << ref.nrow() << ",\"complex_cells\":" << count
              << ",\"different_cells\":" << different
              << ",\"rel_rms\":" << relative << ",\"max_over_peak\":" << relative_peak
              << ",\"peak_reference\":" << peak << ",\"max_difference\":" << maxdiff
              << ",\"pass\":" << (pass ? "true" : "false") << "}\n";
    return pass ? 0 : 1;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 2; }
}
