// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
//
// Exact-DFT point-source injector: writes analytic visibilities for K
// unpolarized point sources into DATA of an MS copy, giving a calibrated
// testbed with known ground truth (positions in direction cosines, fluxes
// in Jy). No gridding is involved in the truth: V = S*exp(-2*pi*i*(ul+vm+w(nm1))).
//
//   pointflux_tool <ms> <l1,m1,s1[;l2,m2,s2...]>
//
// l,m in radians, S in Jy (Stokes I; XX=YY=S/2, XY=YX=0). Rows with
// non-finite UVW are flagged; FLAG is otherwise left untouched so both
// builds under test see identical selection. Run only on a scratch copy:
// the tool overwrites DATA.
#include <casacore/ms/MSOper/MSReader.h>
#include <casacore/tables/Tables/Table.h>
#include <casacore/tables/Tables/ArrayColumn.h>
#include <casacore/tables/Tables/ScalarColumn.h>
#include <casacore/casa/Arrays/Vector.h>
#include <casacore/casa/Arrays/Cube.h>
#include <casacore/casa/BasicMath/Math.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

constexpr double kTwoPi = 6.283185307179586476925286766559;
constexpr double kSpeedOfLight = 299792458.0;

struct Source {
  double l, m, flux;
};

bool parseSources(const char* text, std::vector<Source>& out) {
  for (const char* p = text; *p;) {
    Source s{};
    char* end = nullptr;
    s.l = std::strtod(p, &end);
    if (end == p || *end != ',') return false;
    p = end + 1;
    s.m = std::strtod(p, &end);
    if (end == p || *end != ',') return false;
    p = end + 1;
    s.flux = std::strtod(p, &end);
    if (end == p) return false;
    p = end;
    if (*p == ';') ++p;
    out.push_back(s);
  }
  return !out.empty();
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::fprintf(stderr, "usage: %s <ms> <l1,m1,s1[;...]>\n", argv[0]);
    return 2;
  }
  std::vector<Source> sources;
  if (!parseSources(argv[2], sources)) {
    std::fprintf(stderr, "bad source list\n");
    return 2;
  }
  casacore::Table ms(argv[1], casacore::Table::Update);
  const casacore::uInt nrow = ms.nrow();
  casacore::ArrayColumn<casacore::Double> uvw(ms, "UVW");
  casacore::ArrayColumn<casacore::Complex> data(ms, "DATA");
  casacore::ArrayColumn<casacore::Bool> flag(ms, "FLAG");
  // First spectral window, all its channels (exact per-channel wavelength).
  casacore::Table spw(ms.keywordSet().asTable("SPECTRAL_WINDOW"));
  casacore::ArrayColumn<casacore::Double> chanFreq(spw, "CHAN_FREQ");
  const casacore::Vector<casacore::Double> freqs = chanFreq.get(0);
  const casacore::uInt nchan = freqs.nelements();

  casacore::Vector<casacore::Double> uvwVec(3);
  casacore::Array<casacore::Complex> cell;
  casacore::Array<casacore::Bool> flagCell;
  std::size_t nwritten = 0, nflagged = 0;
  for (casacore::uInt row = 0; row < nrow; ++row) {
    uvw.get(row, uvwVec);
    if (!std::isfinite(uvwVec(0)) || !std::isfinite(uvwVec(1)) || !std::isfinite(uvwVec(2))) {
      data.get(row, cell);  // keep shape
      flag.get(row, flagCell);
      flagCell = true;
      flag.put(row, flagCell);
      ++nflagged;
      continue;
    }
    data.get(row, cell);
    // DATA is (nchan, npol=4): flat-spectrum points, XX=YY=I/2, XY=YX=0,
    // with the exact per-channel wavelength (no-averaged-frequency error).
    casacore::Cube<casacore::Complex> cube(cell);
    for (casacore::uInt ch = 0; ch < cube.nrow() && ch < nchan; ++ch) {
      const double wavelength = kSpeedOfLight / freqs(ch);
      const double u = uvwVec(0) / wavelength;
      const double v = uvwVec(1) / wavelength;
      const double w = uvwVec(2) / wavelength;
      casacore::Complex sum(0.0f, 0.0f);
      for (const Source& s : sources) {
        const double nm1 = std::sqrt(std::max(0.0, 1.0 - s.l * s.l - s.m * s.m)) - 1.0;
        const double phase = -kTwoPi * (u * s.l + v * s.m + w * nm1);
        sum += static_cast<float>(s.flux) *
               casacore::Complex(static_cast<float>(std::cos(phase)),
                                 static_cast<float>(std::sin(phase)));
      }
      const casacore::Complex half = sum * 0.5f;
      cube(ch, 0, 0) = half;
      if (cube.ncolumn() > 1) cube(ch, 1, 0) = casacore::Complex(0.0f, 0.0f);
      if (cube.ncolumn() > 2) cube(ch, 2, 0) = casacore::Complex(0.0f, 0.0f);
      if (cube.ncolumn() > 3) cube(ch, 3, 0) = half;
    }
    data.put(row, cell);
    ++nwritten;
  }
  std::printf("inject: nchan=%u rows=%u written=%zu newly_flagged=%zu sources=%zu\n",
              nchan, nrow, nwritten, nflagged, sources.size());
  return 0;
}
