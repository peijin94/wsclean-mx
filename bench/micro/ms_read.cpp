// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Reading UVW, DATA, FLAG and WEIGHT of every row of a measurement set: row by
// row, alternating between the columns (as wsclean's ContiguousMSReader
// does), against blocks of rows per column. All columns of the test MS are
// indirect arrays in one StandardStMan file, which shares one 64 kB buffer.
//
//   c++ -std=c++20 -O2 -I deps/install/include -I deps/install/include/casacore \
//       bench/micro/ms_read.cpp -L deps/install/lib -lcasa_tables -lcasa_casa \
//       -Wl,-rpath,$PWD/deps/install/lib -o bench/micro/bin/ms_read
//   bench/micro/bin/ms_read <ms> [block=1024]

#include <casacore/casa/Arrays/Array.h>
#include <casacore/tables/Tables/ArrayColumn.h>
#include <casacore/tables/Tables/RefRows.h>
#include <casacore/tables/Tables/Table.h>

#include <chrono>
#include <complex>
#include <cstdio>
#include <cstdlib>

using casacore::ArrayColumn;

int main(int argc, char** argv) {
  const casacore::Table table(argv[1]);
  const size_t block = argc > 2 ? std::atoi(argv[2]) : 1024;
  ArrayColumn<double> uvw(table, "UVW");
  ArrayColumn<casacore::Complex> data(table, "DATA");
  ArrayColumn<bool> flag(table, "FLAG");
  ArrayColumn<float> weight(table, "WEIGHT");
  const size_t n_rows = table.nrow();
  double checksum = 0.0;

  for (int pass = 0; pass != 2; ++pass) {
    auto t0 = std::chrono::steady_clock::now();
    casacore::Array<double> u;
    casacore::Array<casacore::Complex> d;
    casacore::Array<bool> f;
    casacore::Array<float> w;
    for (size_t row = 0; row != n_rows; ++row) {
      uvw.get(row, u, true);
      data.get(row, d, true);
      flag.get(row, f, true);
      weight.get(row, w, true);
      checksum += u.data()[0] + d.data()[0].real() + f.data()[0] + w.data()[0];
    }
    auto t1 = std::chrono::steady_clock::now();
    for (size_t start = 0; start < n_rows; start += block) {
      const casacore::RefRows rows(start, std::min(start + block, n_rows) - 1);
      const casacore::Array<double> ub = uvw.getColumnCells(rows);
      const casacore::Array<casacore::Complex> db = data.getColumnCells(rows);
      const casacore::Array<bool> fb = flag.getColumnCells(rows);
      const casacore::Array<float> wb = weight.getColumnCells(rows);
      checksum += ub.data()[0] + db.data()[0].real() + fb.data()[0] + wb.data()[0];
    }
    auto t2 = std::chrono::steady_clock::now();
    std::printf("pass %d: row by row %.3f s, blocks of %zu rows %.3f s\n", pass,
                std::chrono::duration<double>(t1 - t0).count(), block,
                std::chrono::duration<double>(t2 - t1).count());
  }
  std::printf("rows %zu checksum %g\n", n_rows, checksum);
}
