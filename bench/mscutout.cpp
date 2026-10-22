// Materialise a time-range cutout of a Measurement Set.
//
// taql can only make *reference* tables for this MS (its storage manager
// supports neither DELETE nor INSERT), and a reference table re-reads the
// parent on every pass - a 108 s imaging run became 17 minutes. Table::copy()
// on a selection is the supported way to get a standalone copy, and it is what
// python-casacore's table.copy() uses underneath.
//
// usage: mscutout <in.ms> <out.ms> "<taql where clause>"
#include <casacore/casa/Arrays/Vector.h>
#include <casacore/casa/Exceptions/Error.h>
#include <casacore/tables/Tables/Table.h>
#include <casacore/tables/TaQL/TableParse.h>

#include <cstdio>
#include <cstdlib>
#include <string>

int main(int argc, char** argv) {
  if (argc < 4) {
    std::fprintf(stderr, "usage: %s <in.ms> <out.ms> \"<where clause>\"\n", argv[0]);
    return 2;
  }
  try {
    const std::string cmd = "select from " + std::string(argv[1]) + " where " + argv[3];
    std::fprintf(stderr, "[mscutout] %s\n", cmd.c_str());
    casacore::Table selected = casacore::tableCommand(casacore::String(cmd));
    std::fprintf(stderr, "[mscutout] selected %lld rows; copying...\n",
                 static_cast<long long>(selected.nrow()));
    selected.copy(casacore::String(argv[2]), casacore::Table::New);
    casacore::Table out(casacore::String(argv[2]), casacore::Table::Old);
    std::fprintf(stderr, "[mscutout] wrote %lld rows to %s\n",
                 static_cast<long long>(out.nrow()), argv[2]);
    return 0;
  } catch (const casacore::AipsError& e) {
    std::fprintf(stderr, "[mscutout] casacore error: %s\n", e.getMesg().c_str());
    return 1;
  }
}
