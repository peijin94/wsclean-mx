// Replays one exact wsclean inversion: reads a dump written by the
// MX_METAL_DEBUG_DUMP_INPUTS hook (header, geometry, uvws, frequencies,
// visibilities), runs the Metal inversion and the ducc0 reference with the
// identical call-site parameters, and compares. This puts real-data failures
// inside the probe harness with all its discriminators.
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "ducc0/infra/mav.h"
#include "ducc0/wgridder/wgridder.h"
#include "ducc0/wgridder/wgridder_impl.h"
#include "metal/metalinversion.h"

namespace {
void compare(const std::vector<float>& mine, const std::vector<float>& reference,
             const char* label) {
  double max_ref = 0.0, max_diff = 0.0, sum_sq = 0.0, sum_ref = 0.0;
  std::size_t n_diff = 0;
  for (std::size_t i = 0; i < mine.size(); ++i) {
    const double r = reference[i];
    const double d = static_cast<double>(mine[i]) - r;
    max_ref = std::max(max_ref, std::fabs(r));
    sum_ref += r * r;
    if (d != 0.0) {
      ++n_diff;
      max_diff = std::max(max_diff, std::fabs(d));
      sum_sq += d * d;
    }
  }
  const double rms = std::sqrt(sum_sq / static_cast<double>(mine.size()));
  std::printf("%s peak mine=%.5g ref=%.5g | diff max=%.4g rms=%.4g | rel_max=%.4g rel_rms=%.4g n_diff=%zu/%zu\n",
              label, *std::max_element(mine.begin(), mine.end()),
              *std::max_element(reference.begin(), reference.end()), max_diff, rms,
              max_diff / max_ref, rms / max_ref, n_diff, mine.size());
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 2 || argc > 3) {
    std::fprintf(stderr, "usage: replay_check <dump> [--2d]\n");
    return 2;
  }
  const bool two_d = argc == 3 && std::string(argv[2]) == "--2d";
  FILE* dump = std::fopen(argv[1], "rb");
  if (dump == nullptr) {
    std::fprintf(stderr, "cannot open %s\n", argv[1]);
    return 2;
  }
  std::uint64_t header[2];
  double geom[7];
  if (std::fread(header, sizeof(header), 1, dump) != 1 ||
      std::fread(geom, sizeof(geom), 1, dump) != 1) {
    std::fprintf(stderr, "short dump header\n");
    return 2;
  }
  const std::size_t n_rows = static_cast<std::size_t>(header[0]);
  const std::size_t n_channels = static_cast<std::size_t>(header[1]);
  std::vector<double> uvw(3 * n_rows);
  std::vector<double> freqs(n_channels);
  std::vector<std::complex<float>> ms(n_rows * n_channels);
  if (std::fread(uvw.data(), sizeof(double) * 3 * n_rows, 1, dump) != 1 ||
      std::fread(freqs.data(), sizeof(double) * n_channels, 1, dump) != 1 ||
      std::fread(ms.data(), sizeof(std::complex<float>) * n_rows * n_channels, 1, dump) != 1) {
    std::fprintf(stderr, "short dump body\n");
    return 2;
  }
  std::fclose(dump);
  const std::size_t image_width = static_cast<std::size_t>(geom[3]);
  const std::size_t image_height = static_cast<std::size_t>(geom[4]);

  mx::metal::InversionInput input;
  input.n_rows = n_rows;
  input.uvws = uvw.data();
  input.frequencies = freqs.data();
  input.n_channels = n_channels;
  input.ms = ms.data();
  input.pixel_size_x = geom[0];
  input.pixel_size_y = geom[1];
  input.epsilon = geom[2];
  input.n_threads = 8;
  input.flip_u = false;
  input.flip_v = true;  // wsclean call site
  input.flip_w = false;
  input.l_shift = geom[5];
  input.m_shift = geom[6];
  input.image_width = image_width;
  input.image_height = image_height;
  input.w_gridding = !two_d;

  std::printf("replay rows=%zu nchan=%zu image=%zux%zu pix=%.6g epsilon=%.3g shift=(%.3g,%.3g)\n",
              n_rows, n_channels, image_width, image_height, geom[0], geom[2], geom[5], geom[6]);
  std::vector<float> mine(image_width * image_height);
  const bool ok = mx::metal::inversion(input, mine.data());
  std::printf("metal inversion: %s\n", ok ? "computed" : "REFUSED");

  std::vector<float> reference(image_width * image_height);
  {
    const ducc0::cmav<double, 2> uvw_ma(uvw.data(), {n_rows, 3});
    const ducc0::cmav<size_t, 1> freqlist_id =
        ducc0::cmav<size_t, 1>::build_uniform({n_rows}, 0);
    const ducc0::cmav<size_t, 1> freqlist_nfreqs =
        ducc0::cmav<size_t, 1>::build_uniform({1}, n_channels);
    const ducc0::cmav<double, 1> freqlist_freqs(freqs.data(), {n_channels});
    const ducc0::cmav<std::complex<float>, 1> ms_ma(ms.data(), {n_rows * n_channels});
    const ducc0::cmav<float, 1> weight_ma(nullptr, {0});
    const ducc0::cmav<std::uint8_t, 1> mask_ma(nullptr, {0});
    ducc0::vmav<float, 2> dirty({image_width, image_height});
    ducc0::ms2dirty_bda<float, float>(uvw_ma, freqlist_id, freqlist_nfreqs, freqlist_freqs,
                                      ms_ma, weight_ma, mask_ma, geom[0], geom[1], geom[2],
                                      /*do_wgridding=*/!two_d, 8, dirty, /*verbosity=*/1, false,
                                      true, false, false, 1.1, 2.0, -geom[5], -geom[6],
                                      /*allow_nshift=*/true);
    for (std::size_t i = 0; i < image_width * image_height; ++i) reference[i] = dirty.raw(i);
  }
  if (!ok) return 1;
  compare(mine, reference, "replay vs ducc0:");
  if (const char* dump_prefix = std::getenv("MX_METAL_DEBUG_DUMP_GRIDS")) {
    // Raw float32 dumps of both images for tap-level forensics (IFFT the
    // reference back to ducc0's combined uv grid, compare tap by tap).
    const std::string mine_path = std::string(dump_prefix) + ".mine.raw";
    const std::string ref_path = std::string(dump_prefix) + ".ref.raw";
    FILE* fm = std::fopen(mine_path.c_str(), "wb");
    FILE* fr = std::fopen(ref_path.c_str(), "wb");
    if (fm != nullptr && fr != nullptr) {
      std::fwrite(mine.data(), sizeof(float) * mine.size(), 1, fm);
      std::fwrite(reference.data(), sizeof(float) * reference.size(), 1, fr);
    }
    if (fm != nullptr) std::fclose(fm);
    if (fr != nullptr) std::fclose(fr);
  }
  return 0;
}
