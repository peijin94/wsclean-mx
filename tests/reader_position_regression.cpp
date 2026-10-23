// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic reordered files, read through the production provider/reader APIs.
#include "msproviders/reorderedmsprovider.h"
#include "gridding/msgridder.h"

#include <casacore/tables/Tables/SetupNewTab.h>

#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <unistd.h>

namespace {
using Complex = std::complex<float>;
using namespace schaapcommon::reordering;
size_t checks = 0;
void Check(bool condition, const std::string& message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}

struct Fixture {
  explicit Fixture(bool variable, aocommon::PolarizationEnum pol, bool limits = false)
      : polarization(pol), npol(aocommon::Polarization::GetVisibilityCount(pol)) {
    std::string pattern =
        (std::filesystem::temp_directory_path() /
         "wsclean-reader-position-XXXXXX").string();
    const char* temp = mkdtemp(pattern.data());
    if (!temp) throw std::runtime_error("mkdtemp failed");
    directory = temp;
    const std::string ms_path = directory + "/synthetic.ms";
    // The provider only needs INTERVAL from this MS. Payloads are independent
    // synthetic files, encoded using the production reordering format.
    casacore::SetupNewTable setup(ms_path, casacore::MS::requiredTableDesc(),
                                 casacore::Table::New);
    casacore::MeasurementSet ms(setup);
    ms.createDefaultSubtables(casacore::Table::New);
    ms.addRow();
    casacore::ScalarColumn<double>(ms, "INTERVAL").put(0, 2.0);
    ms.flush();

    aocommon::MultiBandData bands;
    for (size_t count = 1; count <= 4; ++count) {
      std::vector<aocommon::ChannelInfo> channels;
      for (size_t ch = 0; ch != count; ++ch)
        channels.emplace_back(100e6 + (limits ? 0 : ch * 1e6), 1e6);
      bands.SetBand(count, aocommon::BandData(channels, 100e6));
    }
    channels = variable ? std::vector<size_t>{3, 1, 4, 2, 3, 1}
                        : std::vector<size_t>(6, 3);
    if (limits) channels.resize(3);
    auto handle_data = std::make_unique<HandleData>();
    handle_data->ms_path_ = ms_path;
    handle_data->temporary_directory_ = directory;
    handle_data->bands_per_part_.push_back(bands);
    handle_data->metadata_indices_[0] = 0;
    handle_data->model_update_required_ = false;
    handle_data->keep_temporary_files_ = true;
    handle_data->has_frequency_bda_ = variable;
    handle_data->n_antennas_ = 2;
    wsclean::ReorderedHandle handle(std::move(handle_data));

    MetaHeader header;
    header.start_time = 61041.0;
    header.selected_row_count = channels.size();
    header.filename_length = ms_path.size();
    if (!variable) {
      header.data_desc_id = 3;
      header.constant_interval = 2.0f;
    }
    std::ofstream meta(GetMetaFilename(ms_path, directory, 0), std::ios::binary);
    header.Write(meta);
    meta.write(ms_path.data(), ms_path.size());
    prefix = GetPartPrefix(ms_path, 0, pol, directory);
    std::ofstream data(prefix + ".tmp", std::ios::binary);
    std::ofstream weights(prefix + "-w.tmp", std::ios::binary);
    std::ofstream model(prefix + "-m.tmp", std::ios::binary);
    PartHeader part_header;
    part_header.max_channel_count = variable ? 4 : 3;
    part_header.has_model = true;
    part_header.Write(data);
    for (size_t row = 0; row != channels.size(); ++row) {
      BdaMetaRecord record;
      record.u = 10.0 + row;
      record.v = 20.0 + row;
      record.w = 30.0 + row;
      record.time = 1000.0 + 2 * row;
      record.antenna2 = 1;
      record.data_desc_id = channels[row];
      record.interval = 2.0 + row;
      if (limits) {
        record.u = 0;
        record.v = 0;
        record.w = row == 2 ? 20 : 10;
      }
      if (variable) {
        record.Write(meta);
      } else {
        MetaRecord simple{record.u, record.v, record.w, record.time, 0, 1, 0};
        simple.Write(meta);
      }
      for (size_t i = 0; i != channels[row] * npol; ++i) {
        const Complex d = Data(row, i), m = Model(row, i);
        const float w = Weight(row, i);
        data.write(reinterpret_cast<const char*>(&d), sizeof(d));
        model.write(reinterpret_cast<const char*>(&m), sizeof(m));
        weights.write(reinterpret_cast<const char*>(&w), sizeof(w));
      }
    }
    meta.close();
    data.close();
    weights.close();
    model.close();
    provider = std::make_unique<wsclean::ReorderedMsProvider>(handle, 0, pol);
  }
  ~Fixture() {
    provider.reset();
    std::filesystem::remove_all(directory);
  }
  static Complex Data(size_t row, size_t i) {
    return {float(100 * row + i + 1), -float(100 * row + i + 2)};
  }
  static Complex Model(size_t row, size_t i) {
    return {float(1000 + 100 * row + i), float(2000 + 100 * row + i)};
  }
  static float Weight(size_t row, size_t i) {
    return row == 1 || row == 4 ? 0.0f : float(10 * row + i + 1);
  }
  void Verify(wsclean::MSReader& reader, size_t row, bool data, bool weights,
              bool model) {
    Check(reader.CurrentRowAvailable(), "row unavailable");
    Check(reader.RowId() == row, "wrong row id");
    wsclean::MSProvider::MetaData meta{};
    reader.ReadMeta(meta);
    Check(meta.u_in_m == 10 + row && meta.v_in_m == 20 + row &&
              meta.w_in_m == 30 + row && meta.time == 1000 + 2 * row &&
              meta.data_desc_id == channels[row], "wrong metadata");
    const size_t n = channels[row] * npol;
    // Guard cells also catch reads using the previous row's channel count.
    std::vector<Complex> values(4 * npol + 1, Complex(-999, -999));
    if (data) {
      reader.ReadData(values.data());
      for (size_t i = 0; i != n; ++i)
        Check(values[i] == Data(row, i), "data mismatch at row " + std::to_string(row));
      Check(values[n] == Complex(-999, -999), "data overwrote guard");
    }
    if (weights) {
      std::vector<float> values(4 * npol + 1, -999.0f);
      reader.ReadWeights(values.data());
      for (size_t i = 0; i != n; ++i)
        Check(values[i] == Weight(row, i), "weight mismatch at row " + std::to_string(row));
      Check(values[n] == -999.0f, "weights overwrote guard");
    }
    if (model) {
      std::fill(values.begin(), values.end(), Complex(-999, -999));
      reader.ReadModel(values.data());
      for (size_t i = 0; i != n; ++i)
        Check(values[i] == Model(row, i), "model mismatch at row " + std::to_string(row));
      Check(values[n] == Complex(-999, -999), "model overwrote guard");
    }
  }
  aocommon::PolarizationEnum polarization;
  size_t npol;
  std::string directory, prefix;
  std::vector<size_t> channels;
  std::unique_ptr<wsclean::ReorderedMsProvider> provider;
};

void Run(bool variable, aocommon::PolarizationEnum polarization, const std::string& mode) {
  Fixture fixture(variable, polarization);
  auto reader = fixture.provider->MakeReader();
  for (size_t row = 0; row != fixture.channels.size(); ++row) {
    const bool data = mode != "weights" && (mode == "sequential" || row % 3 != 0);
    const bool weights = mode != "data" && (mode == "sequential" || row % 3 != 2);
    fixture.Verify(*reader, row, data, weights, true);
    fixture.Verify(*reader, row, data, weights, true);  // cached repeat
    reader->NextInputRow();
  }
  Check(!reader->CurrentRowAvailable(), "reader did not reach end");
  // Read MODEL only after skipped rows, independent of both other payloads.
  auto model_only = fixture.provider->MakeReader();
  for (size_t row = 0; row != fixture.channels.size(); ++row) {
    const bool read_model = row % 3 == 2 || row + 1 == fixture.channels.size();
    fixture.Verify(*model_only, row, false, false, read_model);
    if (read_model) fixture.Verify(*model_only, row, false, false, true);
    model_only->NextInputRow();
  }
  Check(!model_only->CurrentRowAvailable(), "model-only reader did not reach end");
  // MSReader has no Reset: MakeReader must restart independently at row zero.
  auto reset = fixture.provider->MakeReader();
  auto other = fixture.provider->MakeReader();
  other->NextInputRow();
  other->NextInputRow();
  fixture.Verify(*other, 2, true, true, true);
  fixture.Verify(*reset, 0, true, true, true);
  other->NextInputRow();
  reset->NextInputRow();
  fixture.Verify(*reset, 1, true, true, true);
  fixture.Verify(*other, 3, true, true, true);

  // ResetWritePosition must also reset the variable-shape model writer.
  for (size_t row = 0; row != fixture.channels.size(); ++row)
    fixture.provider->NextOutputRow();
  fixture.provider->ResetWritePosition();
  std::vector<Complex> replacement(4 * fixture.npol, Complex(42, -13));
  fixture.provider->WriteModel(replacement.data(), false);
  std::vector<Complex> model(4 * fixture.npol);
  reset = fixture.provider->MakeReader();
  reset->ReadModel(model.data());
  Check(std::equal(model.begin(), model.begin() + fixture.channels[0] * fixture.npol,
                   replacement.begin()), "model write reset failed");
  reset->NextInputRow();
  fixture.Verify(*reset, 1, true, true, true);
}

void ImagingWeights(bool variable, aocommon::PolarizationEnum polarization) {
  Fixture fixture(variable, polarization);
  std::vector<float> expected;
  for (size_t row = 0; row != fixture.channels.size(); ++row)
    for (size_t i = 0; i != fixture.channels[row] * fixture.npol; ++i)
      expected.push_back(-float(100 * row + i + 1));
  {
    std::ofstream file(fixture.prefix + "-imgw.tmp", std::ios::binary);
    file.write(reinterpret_cast<const char*>(expected.data()), expected.size() * sizeof(float));
  }
  auto reader = fixture.provider->MakeReader();
  size_t offset = 0;
  for (size_t row = 0; row != fixture.channels.size(); ++row) {
    const size_t n = fixture.channels[row] * fixture.npol;
    if (row % 3 != 0) {
      std::vector<float> values(n);
      for (size_t i = 0; i != n; ++i) {
        values[i] = i % 3 == 1 ? std::numeric_limits<float>::quiet_NaN()
                              : float(1000 + 100 * row + i);
        if (std::isfinite(values[i])) expected[offset + i] = values[i];
      }
      reader->WriteImagingWeights(values.data());
      reader->WriteImagingWeights(values.data());
    }
    offset += n;
    reader->NextInputRow();
  }
  reader.reset();  // close/flush before checking the serialized result
  std::vector<float> actual(expected.size());
  std::ifstream file(fixture.prefix + "-imgw.tmp", std::ios::binary);
  file.read(reinterpret_cast<char*>(actual.data()), actual.size() * sizeof(float));
  Check(file.gcount() == std::streamsize(expected.size() * sizeof(float)),
        "wrong imaging-weight file length");
  for (size_t i = 0; i != expected.size(); ++i)
    Check(actual[i] == expected[i], "imaging weight mismatch at value " + std::to_string(i));
}

// Only geometry is needed to call the public production limits workflow.
class GeometryGridder final : public wsclean::MsGridder {
 public:
  using MsGridder::MsGridder;
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

void ConditionalWeights(bool variable, aocommon::PolarizationEnum polarization) {
  Fixture fixture(variable, polarization, true);
  // Row 0 establishes the extrema. Row 1 cannot extend them, so the real
  // collection skips its zero weights. Row 2 must read its own nonzero weights,
  // not row 1's, and extend the range to 20 / wavelength.
  const double wavelength = fixture.provider->SelectedBands()[fixture.channels[2]].ChannelWavelength(
      fixture.channels[2] - 1);
  wsclean::Settings settings;
  settings.pixelScaleX = 1.0 / 256;
  settings.pixelScaleY = 1.0 / 256;
  wsclean::MsProviderCollection collection;
  collection.Add(std::move(fixture.provider), {}, 0);
  collection.InitializeMS();
  GeometryGridder gridder(settings, collection);
  gridder.SetMetaDataCache(std::make_unique<wsclean::MetaDataCache>());
  gridder.SetImageWidth(64);
  gridder.SetImageHeight(64);
  wsclean::ImageWeights weights(wsclean::WeightMode(wsclean::WeightClass::Natural),
                                64, 64, settings.pixelScaleX, settings.pixelScaleY, false, 1.0);
  weights.SetAllValues(1.0);
  gridder.SetImageWeights(&weights);
  collection.InitializeMSDataVector({&gridder}, 0.0, false);
  const double expected = 20 / wavelength;
  Check(std::abs(collection.ms_data_vector_[0].max_w - expected) < 1e-12,
        "conditionally read weights selected the wrong row");
  Check(std::abs(collection.ms_data_vector_[0].max_baseline_uvw - expected) < 1e-12,
        "conditionally read weights changed grid planning baseline");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string mode = argc == 1 ? "all" : argv[1];
    if (mode != "all" && mode != "mixed" && mode != "data" && mode != "weights" &&
        mode != "sequential" && mode != "imaging" && mode != "limits")
      throw std::runtime_error("unknown regression mode");
    for (bool variable : {false, true})
      for (auto pol : {aocommon::PolarizationEnum::StokesI,
                       aocommon::PolarizationEnum::DiagonalInstrumental,
                       aocommon::PolarizationEnum::Instrumental}) {
        if (mode == "all") {
          Run(variable, pol, "mixed");
          Run(variable, pol, "sequential");
          ImagingWeights(variable, pol);
          ConditionalWeights(variable, pol);
        } else if (mode == "limits") ConditionalWeights(variable, pol);
        else if (mode == "imaging") ImagingWeights(variable, pol);
        else Run(variable, pol, mode);
      }
    std::cout << "PASS: " << checks << " reader position assertions\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL after " << checks << " assertions: " << error.what() << '\n';
    return 1;
  }
}
