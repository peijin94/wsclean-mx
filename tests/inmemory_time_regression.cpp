// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Peijin Zhang
// MSProvider::StartTime is MJD days; row metadata remains MS seconds.
#include "msproviders/inmemoryprovider.h"
#include "msproviders/msreaders/msreader.h"
#include <cmath>
#include <iostream>

int main() {
  constexpr double mjd = 61041.25;
  constexpr double seconds = mjd * 86400.0;
  wsclean::InMemoryPart data{};
  data.info = std::make_shared<wsclean::InMemoryInfo>();
  data.info->start_time = seconds;
  data.meta_data = std::make_shared<std::vector<wsclean::MSProvider::MetaData>>();
  wsclean::MSProvider::MetaData metadata{};
  metadata.time = seconds + 10.0;
  data.meta_data->push_back(metadata);
  data.rows.emplace_back();
  wsclean::InMemoryProvider provider(data);
  wsclean::MSProvider& base = provider;
  const bool start_ok = std::fabs(base.StartTime() - mjd) < 1e-12;
  auto reader = provider.MakeReader();
  wsclean::MSProvider::MetaData actual{};
  reader->ReadMeta(actual);
  const bool row_ok = actual.time == metadata.time;
  std::cout << "StartTime MJD days: " << (start_ok ? "PASS" : "FAIL") << '\n';
  std::cout << "row metadata seconds unchanged: " << (row_ok ? "PASS" : "FAIL") << '\n';
  return start_ok && row_ok ? 0 : 1;
}
