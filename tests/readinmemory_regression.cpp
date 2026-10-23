// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic MS fixtures exercised through production loaders and providers.
#include "gridding/msgridder.h"
#include "io/readinmemory.h"
#include "msproviders/contiguousms.h"
#include "msproviders/operations.h"
#include "msproviders/reorderedmsprovider.h"
#include "msproviders/reordering/reorderms.h"
#include "msproviders/rowproviders/directmsrowprovider.h"

#include <casacore/tables/Tables/ArrColDesc.h>
#include <casacore/tables/Tables/SetupNewTab.h>
#include <schaapcommon/reordering/msselection.h>

#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <unistd.h>

namespace {
using Complex = std::complex<float>;
using Selection = schaapcommon::reordering::MSSelection;
size_t checks = 0;
void Check(bool condition, const std::string &message) {
  ++checks;
  if (!condition)
    throw std::runtime_error(message);
}

struct Fixture {
  explicit Fixture(bool spectrum = true) {
    std::string pattern = (std::filesystem::temp_directory_path() /
                           "wsclean-inmemory-XXXXXX").string();
    const char *temp = mkdtemp(pattern.data());
    if (!temp)
      throw std::runtime_error("mkdtemp failed");
    directory = temp;
    path = directory + "/synthetic.ms";
    casacore::TableDesc desc = casacore::MS::requiredTableDesc();
    desc.addColumn(casacore::ArrayColumnDesc<Complex>("DATA"));
    if (spectrum)
      desc.addColumn(casacore::ArrayColumnDesc<float>("WEIGHT_SPECTRUM"));
    casacore::SetupNewTable setup(path, desc, casacore::Table::New);
    ms = std::make_unique<casacore::MeasurementSet>(setup);
    ms->createDefaultSubtables(casacore::Table::New);
    ms->antenna().addRow(2);
    for (size_t a = 0; a != 2; ++a) {
      casacore::ScalarColumn<casacore::String>(ms->antenna(), "NAME")
          .put(a, "ANT" + std::to_string(a));
      casacore::Vector<double> position(3, 0.0);
      position[0] = 6371000.0;
      casacore::ArrayColumn<double>(ms->antenna(), "POSITION").put(a, position);
    }
    ms->field().addRow(2);
    casacore::Array<double> direction(casacore::IPosition(2, 2, 1), 0.0);
    for (size_t field = 0; field != 2; ++field) {
      casacore::ScalarColumn<casacore::String>(ms->field(), "NAME")
          .put(field, "synthetic");
      casacore::ArrayColumn<double>(ms->field(), "PHASE_DIR")
          .put(field, direction);
    }
    ms->observation().addRow();
    casacore::ScalarColumn<casacore::String>(ms->observation(), "OBSERVER")
        .put(0, "test");
    casacore::ScalarColumn<casacore::String>(ms->observation(),
                                             "TELESCOPE_NAME")
        .put(0, "synthetic");
    AddBand(3);
    ms->polarization().addRow();
    casacore::ScalarColumn<int>(ms->polarization(), "NUM_CORR").put(0, 2);
    casacore::Vector<int> correlations(2);
    correlations[0] = 9;  // XX
    correlations[1] = 12; // YY
    casacore::ArrayColumn<int>(ms->polarization(), "CORR_TYPE")
        .put(0, correlations);
  }
  ~Fixture() {
    ms.reset();
    std::filesystem::remove_all(directory);
  }
  void AddBand(size_t channels) {
    const size_t id = ms->spectralWindow().nrow();
    ms->spectralWindow().addRow();
    casacore::ScalarColumn<int>(ms->spectralWindow(), "NUM_CHAN")
        .put(id, channels);
    casacore::ScalarColumn<double>(ms->spectralWindow(), "REF_FREQUENCY")
        .put(id, 100e6);
    casacore::Vector<double> frequencies(channels), widths(channels, 1e6);
    for (size_t ch = 0; ch != channels; ++ch)
      frequencies[ch] = 100e6 + ch * 1e6;
    casacore::ArrayColumn<double>(ms->spectralWindow(), "CHAN_FREQ")
        .put(id, frequencies);
    casacore::ArrayColumn<double>(ms->spectralWindow(), "CHAN_WIDTH")
        .put(id, widths);
    ms->dataDescription().addRow();
    casacore::ScalarColumn<int>(ms->dataDescription(), "SPECTRAL_WINDOW_ID")
        .put(id, id);
    casacore::ScalarColumn<int>(ms->dataDescription(), "POLARIZATION_ID")
        .put(id, 0);
  }
  void AddRow(double time, int antenna2 = 1, int field = 0, bool payload = true,
              size_t channels = 3, int ddid = 0, bool define_spectrum = true) {
    const size_t row = ms->nrow();
    ms->addRow();
    casacore::ScalarColumn<int>(*ms, "ANTENNA1").put(row, 0);
    casacore::ScalarColumn<int>(*ms, "ANTENNA2").put(row, antenna2);
    casacore::ScalarColumn<int>(*ms, "FIELD_ID").put(row, field);
    casacore::ScalarColumn<int>(*ms, "DATA_DESC_ID").put(row, ddid);
    casacore::ScalarColumn<double>(*ms, "TIME").put(row, time);
    casacore::ScalarColumn<double>(*ms, "INTERVAL").put(row, 2.0);
    casacore::Vector<double> uvw(3);
    uvw[0] = 10 + row;
    uvw[1] = 20 + row;
    uvw[2] = 30 + row;
    casacore::ArrayColumn<double>(*ms, "UVW").put(row, uvw);
    if (!payload)
      return;
    const casacore::IPosition shape(2, 2, channels);
    casacore::Array<Complex> data(shape);
    casacore::Array<float> spectrum(shape);
    for (size_t i = 0; i != 2 * channels; ++i) {
      data.data()[i] = Value(row, i);
      spectrum.data()[i] = 10 * row + i + 1;
    }
    casacore::ArrayColumn<Complex>(*ms, "DATA").put(row, data);
    casacore::ArrayColumn<bool>(*ms, "FLAG")
        .put(row, casacore::Array<bool>(shape, false));
    if (define_spectrum && ms->tableDesc().isColumn("WEIGHT_SPECTRUM"))
      casacore::ArrayColumn<float>(*ms, "WEIGHT_SPECTRUM").put(row, spectrum);
    casacore::Vector<float> weight(2);
    weight[0] = 100 + row;
    weight[1] = 200 + row;
    casacore::ArrayColumn<float>(*ms, "WEIGHT").put(row, weight);
  }
  static Complex Value(size_t row, size_t i) {
    return {float(100 * row + i + 1), -float(100 * row + i + 2)};
  }
  wsclean::InMemoryMs Read(const Selection &selection = Selection(),
                           bool sort = false) {
    ms->flush();
    return wsclean::ReadMsInMemory(path, "DATA", selection, sort);
  }
  std::string directory, path;
  std::unique_ptr<casacore::MeasurementSet> ms;
};

void Antennas() {
  Fixture f;
  f.AddRow(1000);
  f.AddRow(1000, 0);
  const auto result = f.Read();
  Check(result.rows.size() == 1,
        "cross-correlation must survive and auto-correlation be excluded");
  Check(result.rows[0].antenna1 == 0 && result.rows[0].antenna2 == 1,
        "ANTENNA2 metadata");
  Check(result.rows[0].data[5] == Fixture::Value(0, 5), "full data payload");
}

void Interval() {
  Fixture f;
  for (double time : {1000., 1000., 1002., 1002., 1004., 1006.})
    f.AddRow(time);
  Selection selection;
  selection.SetInterval(1, 3);
  const auto result = f.Read(selection);
  Check(result.rows.size() == 3,
        "interval must contain exactly timesteps 1 and 2");
  for (size_t i = 0; i != 3; ++i) {
    Check(result.rows[i].data[0] == Fixture::Value(i + 2, 0),
          "interval row identity");
    Check(result.rows[i].time == (i == 2 ? 1004 : 1002), "interval time");
  }
  selection.SetEvenOrOddTimesteps(Selection::kEvenTimesteps);
  const auto even = f.Read(selection);
  Check(even.rows.size() == 1 && even.rows[0].time == 1004,
        "absolute even timestep after interval start");
}

void ScalarWeights() {
  Fixture f(false);
  f.AddRow(1000);
  casacore::Array<bool> flags(casacore::IPosition(2, 2, 3), false);
  flags.data()[3] = true;
  casacore::ArrayColumn<bool>(*f.ms, "FLAG").put(0, flags);
  Selection selection;
  selection.SetChannelRange(1, 2);
  const auto result = f.Read(selection);
  Check(result.rows.size() == 1, "scalar row count");
  Check(result.rows[0].data.size() == 6 && result.rows[0].weights.size() == 6,
        "channel selection must be deferred and weights cover all channels");
  for (size_t i = 0; i != 6; ++i) {
    Check(result.rows[0].data[i] == Fixture::Value(0, i),
          "full-channel DATA order");
    Check(result.rows[0].weights[i] == (i == 3 ? 0 : (i % 2 == 0 ? 100 : 200)),
          "per-correlation WEIGHT expansion and FLAG masking");
  }
}

void MixedWeights() {
  Fixture f;
  // Undefined first spectrum cell must not disable valid later spectra.
  f.AddRow(1000, 1, 0, true, 3, 0, false);
  f.AddRow(1002);
  f.AddRow(1004, 1, 0, true, 3, 0, false);
  const auto result = f.Read();
  Check(result.rows.size() == 3, "mixed weights row count");
  for (size_t row = 0; row != 3; ++row)
    for (size_t i = 0; i != 6; ++i)
      Check(result.rows[row].weights[i] ==
                (row == 1 ? float(11 + i)
                          : float((i % 2 == 0 ? 100 : 200) + row)),
            "spectrum/fallback decision must be per row");
}

void IncompatibleSpectrum() {
  Fixture f;
  f.AddRow(1000);
  // Same element count is insufficient: the correlation/channel axes matter.
  casacore::Array<float> weights(casacore::IPosition(2, 3, 2), 9.0f);
  casacore::ArrayColumn<float>(*f.ms, "WEIGHT_SPECTRUM").put(0, weights);
  const auto result = f.Read();
  Check(result.rows.size() == 1, "incompatible spectrum row count");
  for (size_t i = 0; i != 6; ++i)
    Check(result.rows[0].weights[i] == (i % 2 == 0 ? 100 : 200),
          "incompatible spectrum must fall back to scalar weights");
}

template <typename Function>
void ExpectError(Function &&function, const std::string &text) {
  try {
    function();
  } catch (const std::exception &error) {
    Check(std::string(error.what()).find(text) != std::string::npos,
          "wrong error: " + std::string(error.what()));
    return;
  }
  Check(false, "expected rejection: " + text);
}

void DataShape() {
  for (const auto &shape :
       {casacore::IPosition(2, 3, 2), casacore::IPosition(1, 6),
        casacore::IPosition(2, 2, 2), casacore::IPosition(3, 2, 3, 1)}) {
    Fixture f;
    f.AddRow(1000);
    // Equal element counts, rank changes and shorter channel axes are invalid.
    casacore::Array<Complex> data(shape, Complex(1, 0));
    casacore::ArrayColumn<Complex>(*f.ms, "DATA").put(0, data);
    ExpectError([&] { f.Read(); }, "DATA column shape");
  }
}

void FlagShape() {
  for (const auto &shape :
       {casacore::IPosition(2, 3, 2), casacore::IPosition(2, 2, 2),
        casacore::IPosition(2, 2, 4)}) {
    Fixture f;
    f.AddRow(1000);
    casacore::Array<bool> flags(shape, false);
    casacore::ArrayColumn<bool>(*f.ms, "FLAG").put(0, flags);
    ExpectError([&] { f.Read(); }, "FLAG column shape");
  }
}

void ScalarShape() {
  Fixture f(false);
  f.AddRow(1000);
  casacore::Vector<float> weights(3, 5.0f);
  casacore::ArrayColumn<float>(*f.ms, "WEIGHT").put(0, weights);
  ExpectError([&] { f.Read(); }, "WEIGHT column shape");
}

void UndefinedSelected() {
  for (const std::string missing : {"DATA", "FLAG", "WEIGHT"}) {
    Fixture f;
    f.AddRow(1000, 1, 0, false);
    const casacore::IPosition shape(2, 2, 3);
    if (missing != "DATA")
      casacore::ArrayColumn<Complex>(*f.ms, "DATA")
          .put(0, casacore::Array<Complex>(shape, Complex(1, 0)));
    if (missing != "FLAG")
      casacore::ArrayColumn<bool>(*f.ms, "FLAG")
          .put(0, casacore::Array<bool>(shape, false));
    if (missing != "WEIGHT")
      casacore::ArrayColumn<float>(*f.ms, "WEIGHT")
          .put(0, casacore::Vector<float>(2, 1.0f));
    ExpectError([&] { f.Read(); }, missing + " column shape");
  }
}

void BeyondInterval() {
  Fixture f;
  f.AddRow(1000);
  f.AddRow(1002);
  Selection selection;
  selection.SetInterval(4, 6);
  Check(f.Read(selection).rows.empty(),
        "interval starting beyond all timesteps must be empty");
  selection.SetInterval(2, 3);
  Check(f.Read(selection).rows.empty(),
        "interval starting immediately after last timestep must be empty");
  selection.SetInterval(1, 1);
  Check(f.Read(selection).rows.empty(),
        "equal interval endpoints must be empty");
  selection.SetInterval(2, 1);
  Check(f.Read(selection).rows.empty(), "reversed interval must be empty");
  selection.SetInterval(1, 9);
  const auto tail = f.Read(selection);
  Check(tail.rows.size() == 1 && tail.rows[0].time == 1002,
        "interval ending beyond MS must retain tail");
}

void SharedEmptyRowRange() {
  Fixture f(false);
  Selection selection;
  selection.SetInterval(1, 3);
  size_t begin, end;
  wsclean::GetRowRange(*f.ms, selection, begin, end);
  Check(begin == 0 && end == 0, "shared empty-MS range");
}

void EmptyRowProvider() {
  Fixture f;
  for (double time : {1000., 1000., 1002., 1004.})
    f.AddRow(time);
  f.ms->flush();
  for (const auto &[first, last] :
       {std::pair<size_t, size_t>{3, 9}, {100, 200}, {1, 1}, {2, 1}}) {
    Selection selection;
    selection.SetInterval(first, last);
    auto provider = wsclean::MakeMsRowProvider(
        f.path, selection, aocommon::VectorSet<size_t>{0}, "DATA", "MODEL_DATA", false, false);
    Check(provider->AtEnd(), "empty interval row provider must start at EOF");
    Check(provider->CurrentProgress() == 0 && provider->TotalProgress() == 0,
          "empty interval row provider must have zero progress");
    const auto &direct = dynamic_cast<const wsclean::DirectMSRowProvider &>(*provider);
    Check(direct.StartTimestep() == first && direct.EndTimestep() == first,
          "empty interval must have no timestep span");
  }
  Fixture empty;
  empty.ms->flush();
  auto provider = wsclean::MakeMsRowProvider(
      empty.path, Selection(), aocommon::VectorSet<size_t>{0}, "DATA", "MODEL_DATA", false, false);
  Check(provider->AtEnd() && provider->TotalProgress() == 0,
        "empty MS row provider must start at EOF, even with WEIGHT_SPECTRUM");
}

void EmptyRowProviderEpoch(bool start) {
  for (bool empty_ms : {false, true}) {
    Fixture f;
    if (!empty_ms) {
      f.AddRow(1000);
      f.AddRow(1002);
    }
    f.ms->flush();
    for (const auto &[first, last] :
         {std::pair<size_t, size_t>{2, 9}, {100, 200}, {1, 1}, {2, 1}}) {
      Selection selection;
      selection.SetInterval(first, last);
      auto provider = wsclean::MakeMsRowProvider(
          f.path, selection, aocommon::VectorSet<size_t>{0}, "DATA", "MODEL_DATA", false, false);
      Check(provider->AtEnd(), "empty epoch test requires EOF");
      // EndTime must not expose the final unselected epoch or underflow at 0.
      ExpectError([&] { start ? provider->StartTime() : provider->EndTime(); },
                  "empty row range");
    }
  }
}

void EmptyRowProviderStartTime() { EmptyRowProviderEpoch(true); }
void EmptyRowProviderEndTime() { EmptyRowProviderEpoch(false); }

aocommon::VectorMap<schaapcommon::reordering::ChannelRange> ProviderChannels() {
  aocommon::VectorMap<schaapcommon::reordering::ChannelRange> channels;
  channels.AlwaysEmplace(0, schaapcommon::reordering::ChannelRange{0, 0, 3});
  return channels;
}

std::unique_ptr<wsclean::ContiguousMS> MakeContiguous(
    Fixture &f, const Selection &selection, bool sort = false) {
  f.ms->flush();
  return std::make_unique<wsclean::ContiguousMS>(
      f.path, "DATA", "MODEL_DATA",
      schaapcommon::reordering::StorageManagerType::Default, selection,
      ProviderChannels(), aocommon::Polarization::XX, false, sort);
}

void EmptyContiguousProvider() {
  Fixture f;
  for (double time : {1000., 1000., 1002., 1004.})
    f.AddRow(time);
  for (bool sort : {false, true}) {
    for (const auto &[first, last] :
         {std::pair<size_t, size_t>{3, 9}, {100, 200}, {1, 1}, {2, 1}}) {
      Selection selection;
      selection.SetInterval(first, last);
      auto provider = MakeContiguous(f, selection, sort);
      Check(provider->NRows() == 0, "empty contiguous interval must have no rows");
      auto reader = provider->MakeReader();
      Check(!reader->CurrentRowAvailable() && !reader->CurrentRowAvailable(),
            "empty contiguous reader must remain at EOF");
      provider->ResetWritePosition();
      Check(!provider->MakeReader()->CurrentRowAvailable(),
            "reset must not expose row zero for an empty interval");
      ExpectError([&] { provider->StartTime(); }, "empty row range");
    }
  }
}

// Supply only geometry to exercise the real collection initialization; no
// imaging kernel should run when a selected epoch does not exist.
class ProviderGeometryGridder final : public wsclean::MsGridder {
 public:
  using MsGridder::MsGridder;
  void StartInversion() override { throw std::runtime_error("unexpected imaging"); }
  size_t GridMeasurementSet(const wsclean::MsProviderCollection::MsData &) override {
    throw std::runtime_error("unexpected imaging");
  }
  void FinishInversion() override { throw std::runtime_error("unexpected imaging"); }
  void StartPredict(std::vector<aocommon::Image> &&) override {
    throw std::runtime_error("unexpected prediction");
  }
  size_t PredictMeasurementSet(const wsclean::MsProviderCollection::MsData &) override {
    throw std::runtime_error("unexpected prediction");
  }
  void FinishPredict() override { throw std::runtime_error("unexpected prediction"); }
  std::vector<aocommon::Image> ResultImages() override { return {}; }
 private:
  size_t GetSuggestedWGridSize() const override { return 1; }
};

void EmptyContiguousPipeline() {
  Fixture f;
  f.AddRow(1000);
  f.AddRow(1002);
  for (const auto &[first, last] :
       {std::pair<size_t, size_t>{2, 9}, {1, 1}, {2, 1}}) {
    Selection selection;
    selection.SetInterval(first, last);
    wsclean::Settings settings;
    settings.pixelScaleX = settings.pixelScaleY = 0.001;
    wsclean::MsProviderCollection collection;
    collection.Add(MakeContiguous(f, selection), selection, 0);
    collection.InitializeMS();
    ProviderGeometryGridder gridder(settings, collection);
    gridder.SetMetaDataCache(std::make_unique<wsclean::MetaDataCache>());
    gridder.SetImageWidth(16);
    gridder.SetImageHeight(16);
    wsclean::ImageWeights weights(wsclean::WeightMode(wsclean::WeightClass::Natural),
                                  16, 16, 0.001, 0.001, false, 1.0);
    weights.SetAllValues(1.0);
    gridder.SetImageWeights(&weights);
    ExpectError([&] { collection.InitializeMSDataVector({&gridder}, 0.0, false); },
                "empty row range");
    Check(collection.ms_data_vector_[0].total_rows_processed == 0,
          "empty contiguous pipeline must process no visibilities");
  }
}

wsclean::ReorderedHandle ReorderFixture(Fixture &f, const Selection &selection,
                                       double averaging = 0.0) {
  f.ms->flush();
  wsclean::Settings settings;
  settings.modelUpdateRequired = false;
  settings.temporaryDirectory = f.directory;
  settings.polarizations = {aocommon::Polarization::XX};
  settings.baselineDependentAveragingInWavelengths = averaging;
  return wsclean::ReorderMS(
      f.path, {ProviderChannels()}, selection, "DATA", "MODEL_DATA",
      schaapcommon::reordering::StorageManagerType::Default, false, false, settings);
}

void EmptyReorderingPipeline() {
  Fixture f;
  f.AddRow(1000);
  f.AddRow(1002);
  for (const auto &[first, last] :
       {std::pair<size_t, size_t>{2, 9}, {100, 200}, {1, 1}, {2, 1}}) {
    Selection selection;
    selection.SetInterval(first, last);
    // Also exercise the averaging constructor, which needs both epochs.
    for (double averaging : {0.0, 1.0})
      ExpectError([&] { ReorderFixture(f, selection, averaging); }, "empty row range");
  }
}

void CheckProviderRows(wsclean::MSProvider &provider, size_t first, size_t end) {
  auto reader = provider.MakeReader();
  for (size_t row = first; row != end; ++row) {
    Check(reader->CurrentRowAvailable(), "ordinary provider row must be available");
    wsclean::MSProvider::MetaData metadata{};
    reader->ReadMeta(metadata);
    Check(metadata.time == (row < 2 ? 1000 : 998 + 2 * row) &&
              metadata.u_in_m == 10 + row,
          "ordinary provider must retain selected row identity");
    Complex values[3];
    reader->ReadData(values);
    for (size_t ch = 0; ch != 3; ++ch)
      Check(values[ch] == Fixture::Value(row, 2 * ch),
            "ordinary provider selected DATA");
    reader->NextInputRow();
  }
  Check(!reader->CurrentRowAvailable(), "ordinary provider must reach EOF");
}

void OrdinaryProviderIntervals() {
  Fixture f;
  for (double time : {1000., 1000., 1002., 1004.})
    f.AddRow(time);
  f.ms->flush();
  struct IntervalCase { size_t start, end, first_row, end_row; };
  for (const auto &interval : {IntervalCase{0, 1, 0, 2}, {1, 2, 2, 3},
                               {2, 9, 3, 4}, {1, 9, 2, 4}, {0, 0, 0, 4}}) {
    Selection selection;
    selection.SetInterval(interval.start, interval.end);
    const double first_time = interval.first_row < 2 ? 1000 : 998 + 2 * interval.first_row;
    const double last_time = interval.end_row <= 2 ? 1000 : 998 + 2 * (interval.end_row - 1);
    auto direct = wsclean::MakeMsRowProvider(
        f.path, selection, aocommon::VectorSet<size_t>{0}, "DATA", "MODEL_DATA", false, false);
    Check(std::abs(direct->StartTime() - first_time / 86400.0) < 1e-12 &&
              std::abs(direct->EndTime() - last_time / 86400.0) < 1e-12,
          "ordinary row provider epochs must stay in days");
    for (size_t row = interval.first_row; row != interval.end_row; ++row) {
      Check(!direct->AtEnd(), "ordinary direct row must be available");
      wsclean::MsRowProviderBase::DataArray data;
      wsclean::MsRowProviderBase::FlagArray flags;
      wsclean::MsRowProviderBase::WeightArray weights;
      double u, v, w, time;
      uint32_t ddid, a1, a2, field;
      float duration;
      direct->ReadData(data, flags, weights, u, v, w, ddid, a1, a2, field, time, duration);
      Check(data.data()[0] == Fixture::Value(row, 0) && u == 10 + row,
            "ordinary direct DATA identity");
      direct->NextRow();
    }
    Check(direct->AtEnd(), "ordinary direct provider must reach EOF");
    // Reaching EOF after iteration does not erase the selected interval epochs.
    Check(std::abs(direct->EndTime() - last_time / 86400.0) < 1e-12,
          "nonempty interval retains end epoch after iteration");
    for (bool sort : {false, true}) {
      auto contiguous = MakeContiguous(f, selection, sort);
      Check(contiguous->NRows() == interval.end_row - interval.first_row &&
                std::abs(contiguous->StartTime() - first_time / 86400.0) < 1e-12,
            "ordinary contiguous range and epoch");
      CheckProviderRows(*contiguous, interval.first_row, interval.end_row);
    }
    auto handle = ReorderFixture(f, selection);
    wsclean::ReorderedMsProvider reordered(handle, 0, aocommon::Polarization::XX);
    Check(reordered.NRows() == interval.end_row - interval.first_row &&
              std::abs(reordered.StartTime() - first_time / 86400.0) < 1e-12,
          "ordinary reordering range and epoch");
    CheckProviderRows(reordered, interval.first_row, interval.end_row);
  }
}

void SharedRowRange() {
  Fixture f(false);
  Selection selection;
  size_t begin, end;
  f.AddRow(1000);
  f.AddRow(1000);
  f.AddRow(1002);
  f.AddRow(1004);
  const auto range = [&](size_t first, size_t last, size_t expected_begin,
                         size_t expected_end) {
    selection.SetInterval(first, last);
    wsclean::GetRowRange(*f.ms, selection, begin, end);
    Check(begin == expected_begin && end == expected_end,
          "shared timestep range " + std::to_string(first) + ":" +
              std::to_string(last));
  };
  range(0, 1, 0, 2);
  range(1, 2, 2, 3);
  range(2, 9, 3, 4);
  range(3, 9, 4, 4);
  range(100, 200, 4, 4);
  range(1, 1, 4, 4);
  // MSSelection uses end==0 as the no-interval sentinel, not an empty range.
  range(0, 0, 0, 4);
}

void EmptyMs() {
  Fixture f(false);
  Check(f.Read().rows.empty(), "empty MS without interval");
  Selection selection;
  selection.SetInterval(1, 3);
  const auto result = f.Read(selection);
  Check(result.rows.empty(), "empty MS with interval");
  Check(result.start_time == 0.0, "empty MS start time sentinel");
}

void UnselectedUndefined() {
  Fixture f;
  f.AddBand(1);
  f.AddRow(1000, 1, 1, false); // field exclusion, undefined payload
  f.AddRow(1000);
  f.AddRow(1002, 0, 0, false); // auto-correlation exclusion
  f.AddRow(1002, 1, 0, false); // odd timestep exclusion
  f.AddRow(1004, 1, 0, true, 1, 1);
  f.AddRow(1006, 1, 1, false);
  casacore::Array<bool> flags(casacore::IPosition(2, 2, 3), false);
  flags.data()[4] = true;
  casacore::ArrayColumn<bool>(*f.ms, "FLAG").put(1, flags);
  Selection selection;
  selection.SetEvenOrOddTimesteps(Selection::kEvenTimesteps);
  const auto result = f.Read(selection);
  Check(result.rows.size() == 2,
        "unselected undefined DATA/FLAG/weights must never be read");
  Check(result.start_time == 1000 && result.antenna_names.size() == 2 &&
            result.polarizations.size() == 2 &&
            result.field_name == "synthetic",
        "MS metadata");
  for (size_t i = 0; i != 2; ++i) {
    const size_t original_row = i == 0 ? 1 : 4;
    const auto &row = result.rows[i];
    Check(row.data_desc_id == i && row.field_id == 0 && row.interval == 2,
          "selected row metadata");
    Check(row.uvw[0] == 10 + original_row && row.uvw[1] == 20 + original_row &&
              row.uvw[2] == 30 + original_row,
          "UVW metadata");
    Check(row.data.size() == (i == 0 ? 6 : 2) &&
              row.weights.size() == row.data.size(),
          "variable channel counts and all correlations");
    for (size_t j = 0; j != row.data.size(); ++j) {
      Check(row.data[j] == Fixture::Value(original_row, j),
            "selected DATA values");
      Check(row.weights[j] ==
                (i == 0 && j == 4 ? 0 : 10 * original_row + j + 1),
            "spectral weights and flags");
    }
  }
  // A prefix outside the time interval can also contain undefined arrays.
  selection.SetInterval(2, 3);
  const auto interval = f.Read(selection);
  Check(interval.rows.size() == 1 && interval.rows[0].data_desc_id == 1,
        "interval must skip undefined prefix payloads");
  selection.SetFieldIds({1});
  selection.SetInterval(2, 3);
  Check(f.Read(selection).rows.empty(), "empty row selection");
}

void Ordering() {
  Fixture f;
  f.AddRow(1004);
  f.AddRow(1000);
  f.AddRow(1002);
  Selection selection;
  selection.SetInterval(0, 2);
  ExpectError([&] { f.Read(selection); }, "not ordered in time");
  const auto sorted = f.Read(selection, true);
  Check(sorted.rows.size() == 2, "sorted interval row count");
  for (size_t i = 0; i != 2; ++i) {
    Check(sorted.rows[i].time == 1000 + 2 * i, "sorted time");
    Check(sorted.rows[i].data[0] == Fixture::Value(i + 1, 0),
          "sorted DATA identity");
  }
  Check(f.Read().rows.size() == 3,
        "unsorted MS is allowed without an interval");
}
} // namespace

int main(int argc, char **argv) {
  try {
    const std::string mode = argc > 1 ? argv[1] : "all";
    const std::pair<const char *, void (*)()> tests[] = {
        {"antennas", Antennas},
        {"interval", Interval},
        {"scalar", ScalarWeights},
        {"mixed-weights", MixedWeights},
        {"incompatible-spectrum", IncompatibleSpectrum},
        {"data-shape", DataShape},
        {"flag-shape", FlagShape},
        {"scalar-shape", ScalarShape},
        {"beyond-interval", BeyondInterval},
        {"empty", EmptyMs},
        {"shared-range", SharedRowRange},
        {"shared-empty-range", SharedEmptyRowRange},
        {"empty-row-provider", EmptyRowProvider},
        {"empty-row-provider-start", EmptyRowProviderStartTime},
        {"empty-row-provider-end", EmptyRowProviderEndTime},
        {"empty-contiguous-provider", EmptyContiguousProvider},
        {"empty-contiguous-pipeline", EmptyContiguousPipeline},
        {"empty-reordering-pipeline", EmptyReorderingPipeline},
        {"ordinary-provider-intervals", OrdinaryProviderIntervals},
        {"unselected", UnselectedUndefined},
        {"ordering", Ordering},
        {"undefined-selected", UndefinedSelected}};
    bool found = false;
    for (const auto &[name, test] : tests) {
      if (mode == "all" || mode == name) {
        test();
        found = true;
        std::cout << "PASS " << name << '\n';
      }
    }
    if (!found)
      throw std::runtime_error("unknown test: " + mode);
    std::cout << "PASS " << mode << ": " << checks << " assertions\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL after " << checks << " assertions: " << error.what()
              << '\n';
    return 1;
  }
}
