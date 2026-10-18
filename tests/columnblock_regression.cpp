// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// Synthetic in-memory casacore fixtures; never opens the science MS.
#include "msproviders/columnblock.h"
#include <casacore/tables/Tables/ArrColDesc.h>
#include <casacore/tables/Tables/SetupNewTab.h>
#include <casacore/tables/Tables/TableDesc.h>
#include <iostream>
#include <stdexcept>
#include <type_traits>

namespace {
size_t checks = 0;
void Check(bool condition, const char* message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}
template <typename T>
T Value(size_t row, size_t element) {
  if constexpr (std::is_same_v<T, bool>) return (row + element) % 3 == 0;
  else if constexpr (std::is_same_v<T, casacore::Complex>)
    return {float(row * 13 + element), -float(row * 13 + element)};
  else return T(row * 13 + element);
}
template <typename T>
void CheckType(const char* name) {
  using namespace casacore;
  constexpr size_t rows = 1103;
  const IPosition shape(2, 4, 3);
  TableDesc description("", "1", TableDesc::Scratch);
  description.addColumn(ArrayColumnDesc<T>("VALUES"));
  SetupNewTable setup(name, description, Table::New);
  Table table(setup, Table::Memory, rows);
  ArrayColumn<T> column(table, "VALUES");
  Array<T> cell(shape);
  for (size_t row = 0; row != rows; ++row) {
    for (size_t i = 0; i != cell.nelements(); ++i) cell.data()[i] = Value<T>(row, i);
    column.put(row, cell);
  }
  wsclean::ColumnBlock<T> block;
  Check(!block.Loaded(), "new block must be unloaded");
  for (size_t length : {size_t(1), size_t(63), size_t(1024)}) {
    for (size_t first = 0; first < rows; first += length) {
      const size_t last = std::min(rows, first + length) - 1;
      block.Load(column, first, last);
      Check(block.Loaded(), "Load did not set loaded state");
      Check(block.CellSize() == 12, "block cell size is wrong");
      Check(block.CellShape() == shape, "block cell shape is wrong");
      for (size_t row = first; row <= last; ++row) {
        const Array<T> expected = column(row);
        for (size_t i = 0; i != 12; ++i)
          Check(block.Cell(row - first)[i] == expected.data()[i],
                "block value differs from row-wise casacore read");
      }
      block.Reset();
      Check(!block.Loaded(), "Reset did not clear loaded state");
    }
  }
}
}
int main() {
  try {
    CheckType<double>("uvw_fixture");
    CheckType<casacore::Complex>("visibility_fixture");
    CheckType<bool>("flag_fixture");
    CheckType<float>("weight_fixture");
    std::cout << "PASS: " << checks << " column-block assertions\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL after " << checks << " assertions: " << error.what() << '\n';
    return 1;
  }
}
