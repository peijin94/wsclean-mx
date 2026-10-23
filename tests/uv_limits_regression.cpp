// SPDX-License-Identifier: GPL-3.0-or-later
// Calls the production collection with real in-memory providers. The gridder
// adapter supplies geometry only; no imaging kernels or science MS are needed.
#include "gridding/msgridder.h"
#include "msproviders/inmemoryprovider.h"

#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
size_t checks = 0;
void Check(bool good, const std::string& message) {
  ++checks;
  if (!good) throw std::runtime_error(message);
}
void Near(double actual, double expected, const std::string& message) {
  Check(std::abs(actual - expected) <= 1e-12 * std::max(1.0, std::abs(expected)),
        message + ": got " + std::to_string(actual) + ", expected " + std::to_string(expected));
}

class GeometryGridder final : public wsclean::MsGridder {
 public:
  using MsGridder::MsGridder;
  using MsGridder::MaxBaseline;
  using MsGridder::MaxW;
  using MsGridder::MinW;
  void StartInversion() override { throw std::runtime_error("unexpected imaging"); }
  size_t GridMeasurementSet(const wsclean::MsProviderCollection::MsData&) override {
    throw std::runtime_error("unexpected imaging");
  }
  void FinishInversion() override { throw std::runtime_error("unexpected imaging"); }
  void StartPredict(std::vector<aocommon::Image>&&) override {
    throw std::runtime_error("unexpected prediction");
  }
  size_t PredictMeasurementSet(const wsclean::MsProviderCollection::MsData&) override {
    throw std::runtime_error("unexpected prediction");
  }
  void FinishPredict() override { throw std::runtime_error("unexpected prediction"); }
  std::vector<aocommon::Image> ResultImages() override { return {}; }
 private:
  size_t GetSuggestedWGridSize() const override { return 1; }
};

struct Row {
  double u, v, w;
  float weight = 1.0f;
};

void Run(const std::vector<Row>& rows, size_t width, size_t height,
         double dx, double dy, aocommon::PolarizationEnum polarization,
         bool zero_imaging_weights = false) {
  wsclean::InMemoryPart part{};
  part.info = std::make_shared<wsclean::InMemoryInfo>();
  part.info->start_time = 61041.0 * 86400.0;
  part.meta_data = std::make_shared<std::vector<wsclean::MSProvider::MetaData>>();
  part.polarization = polarization;
  part.is_regular = true;
  // One metre wavelength makes the input coordinates and the independent
  // geometric expectations directly readable in wavelengths.
  part.selected_bands.SetBand(0, aocommon::BandData({{299792458.0, 0.0}}, 299792458.0));
  const size_t npol = aocommon::Polarization::GetVisibilityCount(polarization);
  for (size_t i = 0; i != rows.size(); ++i) {
    wsclean::MSProvider::MetaData meta{};
    meta.u_in_m = rows[i].u;
    meta.v_in_m = rows[i].v;
    meta.w_in_m = rows[i].w;
    meta.time = 1000 + 2 * i;
    meta.interval = 2;
    part.meta_data->push_back(meta);
    part.rows.emplace_back();
    part.rows.back().data_model_weights.Resize(npol);
    std::fill(part.rows.back().Weights().begin(), part.rows.back().Weights().end(), rows[i].weight);
  }
  wsclean::Settings settings;
  settings.pixelScaleX = dx;
  settings.pixelScaleY = dy;
  wsclean::MsProviderCollection collection;
  collection.Add(std::make_unique<wsclean::InMemoryProvider>(part), {}, 0);
  collection.InitializeMS();
  GeometryGridder gridder(settings, collection);
  gridder.SetMetaDataCache(std::make_unique<wsclean::MetaDataCache>());
  gridder.SetImageWidth(width);
  gridder.SetImageHeight(height);
  // Deliberately wider than the footprint: GetWeight must not hide a broken
  // geometric rejection, including at the exact Nyquist boundary.
  wsclean::ImageWeights weights(wsclean::WeightMode(wsclean::WeightClass::Natural),
                                64, 64, 1.0 / 256, 1.0 / 256, false, 1.0);
  weights.SetAllValues(zero_imaging_weights ? 0.0 : 1.0);
  gridder.SetImageWeights(&weights);
  collection.InitializeMSDataVector({&gridder}, 0.0, false);

  double min_w = std::numeric_limits<double>::max(), max_w = 0, max_baseline = 0;
  // Independent support oracle: both coordinates must lie between the last
  // fully supported integer cells on their respective axes. This is an interval
  // test, not a copy of the implementation's floor/ceil predicate.
  const double max_u = double((width - 1) / 2) / (width * dx);
  const double max_v = double((height - 1) / 2) / (height * dy);
  for (const Row& row : rows) {
    if (row.weight != 0 && !zero_imaging_weights &&
        std::abs(row.u) <= max_u && std::abs(row.v) <= max_v) {
      min_w = std::min(min_w, std::abs(row.w));
      max_w = std::max(max_w, std::abs(row.w));
      max_baseline = std::max(max_baseline, std::hypot(row.u, row.v, row.w));
    }
  }
  if (min_w == std::numeric_limits<double>::max()) min_w = 0;
  const auto& actual = collection.ms_data_vector_.at(0);
  Near(actual.min_w, min_w, "minimum w");
  Near(actual.max_w, max_w, "maximum w");
  Near(actual.max_baseline_uvw, max_baseline, "baseline in wavelengths");
  Near(actual.max_baseline_in_m, max_baseline, "baseline in metres");
  Near(actual.integration_time, rows.size() < 2 ? 1 : 2, "integration time");
  Near(gridder.MinW(), min_w, "grid planning minimum w");
  Near(gridder.MaxW(), max_w, "grid planning maximum w");
  Near(gridder.MaxBaseline(), max_baseline, "grid planning baseline");
  Near(collection.MaxAbsW(), max_w, "collection maximum w");
  // A cached second initialization must preserve the computed geometry.
  collection.InitializeMSDataVector({&gridder}, 0.0, false);
  Near(gridder.MaxW(), max_w, "cached grid planning maximum w");
}
}  // namespace

int main() {
  try {
    for (auto pol : {aocommon::PolarizationEnum::StokesI,
                     aocommon::PolarizationEnum::DiagonalInstrumental,
                     aocommon::PolarizationEnum::Instrumental}) {
      // Rectangular 16x8 footprint, anisotropic 1/32 by 1/8 pixels:
      // supported limits are |u| <= 14, |v| <= 3.
      for (const Row row : std::vector<Row>{{10, 1, 7}, {1, 4, 90}, {-10, -1, -7},
                                           {-1, -4, -90}, {0, 0, 3}, {14, 3, 7},
                                           {-14, -3, -7}, {16, 0, 90}, {0, 4, 90},
                                           {-16, 0, 90}, {0, -4, 90},
                                           {std::nextafter(14.0, 15.0), 0, 90},
                                           {0, std::nextafter(3.0, 4.0), 90},
                                           {std::nextafter(-14.0, -15.0), 0, 90},
                                           {0, std::nextafter(-3.0, -4.0), 90},
                                           {std::nextafter(14.0, 0.0), 0, 7},
                                           {0, std::nextafter(3.0, 0.0), 7}})
        Run({row}, 16, 8, 1.0 / 32, 1.0 / 8, pol);
      // Swap the axes and use odd dimensions as separate geometry controls.
      Run({{1, 10, 7}, {4, 1, 90}}, 8, 16, 1.0 / 8, 1.0 / 32, pol);
      Run({{0, 3, 7}, {0, 4, 90}}, 9, 7, 1.0 / 9, 1.0 / 7, pol);
      // Mixed extrema: outside rows and zero-weight rows must not determine
      // the beam/baseline or the w range sent to grid planning.
      Run({{10, 1, 7}, {2, 2, -2}, {1, 4, 900}, {0, 0, 1000, 0},
           {1, 1, 4}}, 16, 8, 1.0 / 32, 1.0 / 8, pol);
      Run({{10, 1, 7}}, 16, 8, 1.0 / 32, 1.0 / 8, pol, true);
    }
    std::cout << "PASS: " << checks << " UV limits assertions\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL after " << checks << " assertions: " << error.what() << '\n';
    return 1;
  }
}
