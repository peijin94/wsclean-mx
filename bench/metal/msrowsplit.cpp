// Split first N rows of an MS into a new MS (main table + key subtables).
#include <casacore/tables/TaQL/TableParse.h>
#include <casacore/tables/Tables/Table.h>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: msrowsplit in.ms out.ms nrows\n";
    return 1;
  }
  std::string in = argv[1], out = argv[2], nrows = argv[3];
  try {
    casacore::tableCommand("SELECT * FROM " + in + " WHERE ROWNR() < " + nrows +
                           " GIVING " + out);
    const char* subs[] = {"ANTENNA",       "DATA_DESCRIPTION", "FEED",
                          "FIELD",         "FLAG_CMD",         "HISTORY",
                          "OBSERVATION",   "POINTING",         "POLARIZATION",
                          "PROCESSOR",     "SOURCE",           "SPECTRAL_WINDOW",
                          "STATE",         "DOPPLER",          "FREQ_OFFSET",
                          "SYSCAL",        "WEATHER",          nullptr};
    for (int i = 0; subs[i]; ++i) {
      try {
        casacore::Table sub(in + "/" + subs[i]);
        (void)sub;
        casacore::tableCommand("SELECT * FROM " + in + "::" + subs[i] +
                               " GIVING " + out + "::" + subs[i]);
      } catch (const std::exception& e) {
        std::cerr << "subtable " << subs[i] << ": " << e.what() << "\n";
      }
    }
  } catch (const std::exception& e) {
    std::cerr << "split failed: " << e.what() << "\n";
    return 1;
  }
  std::cout << "wrote " << out << "\n";
  return 0;
}
