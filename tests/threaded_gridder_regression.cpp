// Standalone production-API regression. See thread-*-command.txt in the task
// artifacts for the compiler/link recipe; no copied gridding implementation.
#include "ducc0/wgridder/wgridder_impl.h"
#include "ducc0/fft/fftnd_impl.h"

#include <atomic>
#include <cstring>
#include <iomanip>
#include <limits>
#include <mutex>
#include <set>
#include <stdexcept>
#include <thread>

namespace {
using ducc0::cmav;
using ducc0::vmav;
using std::complex;
constexpr double c = 299792458.;
size_t failures = 0, checks = 0;
void check(bool ok, const std::string& message) {
  ++checks;
  if (!ok) { ++failures; std::cerr << "FAIL " << message << '\n'; }
}
template<class T> bool bytes(const std::vector<T>& a, const std::vector<T>& b) {
  return a.size() == b.size() && std::memcmp(a.data(), b.data(), a.size()*sizeof(T)) == 0;
}
template<class T> bool finite_value(T x) { return std::isfinite(x); }
template<class T> bool finite_value(complex<T> x) {
  return std::isfinite(x.real()) && std::isfinite(x.imag());
}
template<class T> bool all_finite(const std::vector<T>& values) {
  return std::all_of(values.begin(),values.end(),[](T x){ return finite_value(x); });
}
template<class T> bool same_finite(const std::vector<T>& a, const std::vector<T>& b) {
  return all_finite(a) && all_finite(b) && bytes(a,b);
}
struct ErrorStats {
  long double maxerr=0, scale=0;
  bool valid=true;
  template<class T> void observe(T actual, T expected) {
    if (!finite_value(actual) || !finite_value(expected)) { valid=false; return; }
    const long double error=std::abs(expected-actual), magnitude=std::abs(expected);
    if (!std::isfinite(error) || !std::isfinite(magnitude)) { valid=false; return; }
    maxerr=std::max(maxerr,error);
    scale=std::max(scale,magnitude);
  }
  bool within(long double limit, bool relative=true) const {
    const long double threshold=limit*(relative ? std::max(1.L,scale) : 1.L);
    return valid && std::isfinite(limit) && std::isfinite(threshold)
        && std::isfinite(maxerr) && std::isfinite(scale) && maxerr<=threshold;
  }
};

void nonfinite_guards() {
  for (double bad : {std::numeric_limits<double>::quiet_NaN(),
                     std::numeric_limits<double>::infinity(),
                     -std::numeric_limits<double>::infinity()}) {
    // Stable NaN bit patterns and infinities must fail repetition guards too.
    std::vector<double> image{bad};
    check(!same_finite(image,image),"reject nonfinite image/reinversion/mixed repeat");
    for (complex<double> value : {complex<double>(bad,0),complex<double>(0,bad)}) {
      std::vector<complex<double>> predicted{value};
      check(!same_finite(predicted,predicted),"reject nonfinite prediction repeat components");
      ErrorStats prediction;
      prediction.observe(complex<long double>(value),complex<long double>(0));
      prediction.observe(complex<long double>(0),complex<long double>(0));
      check(!prediction.within(4.e-9L,false),"reject nonfinite prediction oracle components");
    }
    ErrorStats inversion, reference;
    inversion.observe(static_cast<long double>(bad),0.L);
    inversion.observe(0.L,0.L);
    reference.observe(0.L,static_cast<long double>(bad));
    check(!inversion.within(4.e-9L),"reject nonfinite image oracle output");
    check(!reference.within(4.e-9L),"reject nonfinite oracle reference");
  }
  ErrorStats overflow;
  overflow.observe(std::numeric_limits<long double>::max(),-std::numeric_limits<long double>::max());
  check(!overflow.within(4.e-9L),"reject nonfinite computed error");
  ErrorStats finite;
  finite.observe(0.L,0.L);
  check(!finite.within(std::numeric_limits<long double>::infinity()),"reject nonfinite tolerance");
  check(finite.within(4.e-9L),"finite oracle control");
  check(same_finite(std::vector<double>{1.},std::vector<double>{1.}),"finite repeat control");
}

// scanData reads every element once. Only subsequent reads count, so this
// measures participation in gridding itself, rather than the parallel scan.
template<class T> struct TrackedInput {
  cmav<complex<T>,1> data;
  mutable std::unique_ptr<std::atomic<unsigned>[]> reads;
  mutable std::mutex mutex;
  mutable std::set<std::thread::id> grid_threads;
  explicit TrackedInput(const std::vector<complex<T>>& v)
      : data(v.data(), {v.size()}), reads(new std::atomic<unsigned>[v.size()]) {
    for (size_t i=0; i<v.size(); ++i) reads[i] = 0;
  }
  auto shape() const { return data.shape(); }
  complex<T> operator()(size_t i) const {
    if (reads[i].fetch_add(1, std::memory_order_relaxed) != 0) {
      std::lock_guard<std::mutex> lock(mutex);
      grid_threads.insert(std::this_thread::get_id());
    }
    return data(i);
  }
  void prefetch_r(size_t i) const { data.prefetch_r(i); }
};

template<class T> uint64_t fingerprint(const std::vector<T>& v) {
  uint64_t h=14695981039346656037ull;
  const auto* p=reinterpret_cast<const unsigned char*>(v.data());
  for (size_t i=0; i<v.size()*sizeof(T); ++i) { h^=p[i]; h*=1099511628211ull; }
  return h;
}

template<class T> struct Fixture {
  size_t nr, nx=96, ny=64;
  double px=.002, py=.003;
  std::vector<double> uvw, freqs;
  std::vector<size_t> ids, nf, offsets;
  std::vector<complex<T>> vis;
  std::vector<T> weights;
  std::vector<uint8_t> mask;
  // mode 0: one channel; 1: rectangular multi-channel; 2: variable channels.
  Fixture(int mode, bool small=false) : nr(small ? 23 : 4096), uvw(3*nr), ids(nr) {
    nf = mode==2 ? std::vector<size_t>{1,3,7} : std::vector<size_t>{mode==0 ? 1ul : 4ul};
    for (auto n : nf) for (size_t j=0; j<n; ++j) freqs.push_back(c*(.94+.02*j));
    offsets.push_back(0);
    for (size_t r=0; r<nr; ++r) {
      ids[r] = mode==2 ? (r/4)%3 : 0;
      offsets.push_back(offsets.back()+nf[ids[r]]);
      size_t group=r/4;
      // Repeated coordinates give strong cancellation in shared buckets.
      // Nearby tiles overlap at their halos; near-zero and +/-period samples
      // exercise both periodic edges in the rectangular grid.
      const double us[] = {0., .0001, -.0001, 1., -1., .24, .25, .26, .27, .28, .49, -.49};
      const double vs[] = {0., -.0001, .0001, -1., 1., .24, .25, .26, .27, .28, -.49, .49};
      uvw[3*r] = small ? (int(r%7)-3)*2.1 : us[group%std::size(us)]/px + (int(group%5)-2)*.03;
      uvw[3*r+1] = small ? (int(r%5)-2)*1.7 : vs[(group/std::size(us))%std::size(vs)]/py;
      uvw[3*r+2] = small ? (int(r%6)-3)*13. : (int(group%11)-5)*260.;
    }
    vis.resize(offsets.back()); weights.resize(vis.size()); mask.resize(vis.size());
    const double amp[] = {1.e5, 1., -1.e5, -.375};
    for (size_t r=0; r<nr; ++r) for (size_t ch=0; ch<nf[ids[r]]; ++ch) {
      size_t k=offsets[r]+ch;
      double a=small ? std::sin(double(k)+.3) : amp[r%4];
      vis[k] = complex<T>(T(a), T(small ? .2*std::cos(double(k)) : a*.375));
      weights[k] = T(.5+.125*((r/4+ch)%5));
      mask[k] = ((r/4+ch)%17 != 0);
      if ((r/4+ch)%29==0) weights[k]=0;
    }
  }
  bool same(const Fixture& f) const {
    return bytes(uvw,f.uvw)&&bytes(freqs,f.freqs)&&bytes(ids,f.ids)&&bytes(nf,f.nf)
        &&bytes(vis,f.vis)&&bytes(weights,f.weights)&&bytes(mask,f.mask);
  }
  std::vector<T> invert(bool w, size_t threads, bool tracked, size_t& participants,
                        const std::vector<complex<T>>* input=nullptr) const {
    const auto& v = input ? *input : vis;
    std::vector<T> out(nx*ny, T(-17));
    vmav<T,2> image(out.data(), {nx,ny});
    auto run = [&](const auto& in) {
      ducc0::ms2dirty_bda<T,T,T>(cmav<double,2>(uvw.data(),{nr,3}),
          cmav<size_t,1>(ids.data(),{nr}), cmav<size_t,1>(nf.data(),{nf.size()}),
          cmav<double,1>(freqs.data(),{freqs.size()}), in,
          cmav<T,1>(weights.data(),{v.size()}), cmav<uint8_t,1>(mask.data(),{v.size()}),
          px,py,std::is_same_v<T,float> ? 1.e-4 : 1.e-9,w,threads,image,0,
          false,false,false,false,1.1,2.6,0.,0.,true);
    };
    if (tracked) { TrackedInput<T> in(v); run(in); participants=in.grid_threads.size(); }
    else { run(cmav<complex<T>,1>(v.data(),{v.size()})); participants=0; }
    return out;
  }
  std::vector<T> invert_regular(bool w, size_t threads) const {
    std::vector<T> out(nx*ny);
    ducc0::ms2dirty<T,T,T>(cmav<double,2>(uvw.data(),{nr,3}),
        cmav<double,1>(freqs.data(),{freqs.size()}),
        cmav<complex<T>,2>(vis.data(),{nr,nf[0]}), cmav<T,2>(weights.data(),{nr,nf[0]}),
        cmav<uint8_t,2>(mask.data(),{nr,nf[0]}),px,py,
        std::is_same_v<T,float> ? 1.e-4 : 1.e-9,w,threads,vmav<T,2>(out.data(),{nx,ny}),0,
        false,false,false,false,1.1,2.6,0.,0.,true);
    return out;
  }
  std::vector<complex<T>> predict(const std::vector<T>& image, bool w,
                                 complex<T> initial) const {
    std::vector<complex<T>> out(vis.size(),initial);
    ducc0::dirty2ms_bda<T,T,T>(cmav<double,2>(uvw.data(),{nr,3}),
        cmav<size_t,1>(ids.data(),{nr}), cmav<size_t,1>(nf.data(),{nf.size()}),
        cmav<double,1>(freqs.data(),{freqs.size()}), cmav<T,2>(image.data(),{nx,ny}),
        cmav<T,1>(weights.data(),{vis.size()}), cmav<uint8_t,1>(mask.data(),{vis.size()}),
        px,py,std::is_same_v<T,float> ? 1.e-4 : 1.e-9,w,8,
        vmav<complex<T>,1>(out.data(),{out.size()}),0,
        false,false,false,false,1.1,2.6,0.,0.,true);
    return out;
  }
};

template<class T> void repeatability(int repeats) {
  for (int mode=0; mode<3; ++mode) for (bool w : {false,true}) {
    Fixture<T> f(mode), saved=f;
    const std::string label=(std::is_same_v<T,float>?"float":"double")+
        std::string(" mode=")+std::to_string(mode)+" w="+std::to_string(w);
    size_t nthreads=0, minthreads=999, different=0;
    auto first=f.invert(w,8,true,nthreads);
    minthreads=std::min(minthreads,nthreads);
    for (int rep=1; rep<repeats; ++rep) {
      auto next=f.invert(w,8,true,nthreads);
      minthreads=std::min(minthreads,nthreads);
      if (!same_finite(first,next)) ++different;
    }
    check(different==0,label+" inversion repeats differing="+std::to_string(different));
    check(minthreads>1,label+" actual gridding threads="+std::to_string(minthreads));
    check(all_finite(first),label+" finite");
    auto plain=f.invert(w,8,false,nthreads);
    check(same_finite(first,plain),label+" tracked/plain equality");
    size_t plain_different=0;
    for (int rep=1; rep<repeats; ++rep)
      if (!same_finite(plain,f.invert(w,8,false,nthreads))) ++plain_different;
    check(plain_different==0,label+" uninstrumented inversion repeats");
    if (mode!=2) check(same_finite(first,f.invert_regular(w,8)),label+" regular/BDA equality");
    // A sparse, moderate image avoids cancellation obscuring prediction checks.
    std::vector<T> image(f.nx*f.ny,0);
    image[(f.nx/2)*f.ny+f.ny/2]=T(1);
    image[(f.nx/2+3)*f.ny+f.ny/2-2]=T(-.25);
    auto image_saved=image;
    auto pred=f.predict(image,w,complex<T>(T(31),T(-9)));
    check(all_finite(pred),label+" finite prediction");
    for (int rep=1; rep<repeats; ++rep) {
      // Interleave a different image and overwrite poisoned output each time.
      auto other=image; other[0]=T(.125);
      auto interleaved=f.predict(other,w,complex<T>(T(-8),T(4)));
      check(all_finite(interleaved),label+" finite interleaved prediction");
      check(same_finite(pred,f.predict(image,w,complex<T>(T(rep),T(-rep)))),label+" prediction isolation");
    }
    auto reinvert=f.invert(w,8,false,nthreads,&pred);
    check(same_finite(reinvert,f.invert(w,8,false,nthreads,&pred)),label+" finite predicted visibility reinversion");
    auto one=f.invert(w,1,false,nthreads);
    check(same_finite(one,f.invert(w,1,false,nthreads)),label+" one-thread repeatability");
    check(f.same(saved)&&bytes(image,image_saved),label+" immutable inputs");
    std::cout << label << " repeats=" << repeats << " differing=" << different
              << " plain_differing=" << plain_different << " min_grid_threads=" << minthreads << " one_thread_hash="
              << std::hex << fingerprint(one) << std::dec << '\n';
  }
}

// Alternating wrapped coordinates: channels 0, 2 and 4 coincide, while 1
// and 3 cross a tile boundary. Endpoint/midpoint sampling misses both.
void periodic_crossing(bool regular, bool v_axis) {
  Fixture<double> f(1);
  f.nx=128; f.ny=96;
  f.nf={5}; f.freqs={c,1.5*c,2*c,2.5*c,3*c};
  f.offsets.clear();
  for (size_t r=0; r<=f.nr; ++r) f.offsets.push_back(5*r);
  f.vis.resize(5*f.nr); f.weights.assign(5*f.nr,1.); f.mask.assign(5*f.nr,1);
  for (size_t r=0; r<f.nr; ++r) {
    f.uvw[3*r]=v_axis ? 0. : 1./f.px;
    f.uvw[3*r+1]=v_axis ? 1./f.py : 0.;
    f.uvw[3*r+2]=0.;
    for (size_t ch=0; ch<5; ++ch) f.vis[5*r+ch]={.125*(ch+1),-.25};
  }
  const std::string label=std::string("periodic ")+(regular?"regular":"BDA")+(v_axis?" v":" u");
  std::cout << "RUN " << label << std::endl;
  size_t participants;
  auto run=[&](size_t threads) {
    return regular ? f.invert_regular(false,threads) : f.invert(false,threads,false,participants);
  };
  auto one=run(1), many=run(8);
  check(all_finite(one)&&all_finite(many),label+" finite output");
  ErrorStats error;
  for (size_t i=0; i<one.size(); ++i) {
    error.observe(static_cast<long double>(many[i]),static_cast<long double>(one[i]));
  }
  check(error.within(4.e-9L),label+" serial/parallel accuracy");
  for (int repeat=0; repeat<3; ++repeat) check(same_finite(many,run(8)),label+" uninstrumented repeat");
  if (!regular) {
    auto tracked=f.invert(false,8,true,participants);
    check(same_finite(many,tracked),label+" tracked/plain equality");
    check(participants>1,label+" genuine gridding workers="+std::to_string(participants));
  }
  std::cout << "PASS " << label << " relative_max_error=" << double(error.maxerr/std::max(1.L,error.scale)) << std::endl;
}

void mixed_precision_repeatability(int repeats) {
  for (int mode=0; mode<3; ++mode) for (bool w : {false,true}) {
    Fixture<float> f(mode), saved=f;
    auto invert = [&](bool tracked, size_t& participants) {
      std::vector<double> out(f.nx*f.ny);
      auto run = [&](const auto& in) {
        ducc0::ms2dirty_bda<double,double,float>(cmav<double,2>(f.uvw.data(),{f.nr,3}),
          cmav<size_t,1>(f.ids.data(),{f.nr}), cmav<size_t,1>(f.nf.data(),{f.nf.size()}),
          cmav<double,1>(f.freqs.data(),{f.freqs.size()}),in,
          cmav<float,1>(f.weights.data(),{f.vis.size()}),cmav<uint8_t,1>(f.mask.data(),{f.vis.size()}),
          f.px,f.py,1.e-9,w,8,vmav<double,2>(out.data(),{f.nx,f.ny}),0,
            false,false,false,false,1.1,2.6,0.,0.,true);
      };
      if (tracked) {
        TrackedInput<float> in(f.vis); run(in); participants=in.grid_threads.size();
      } else {
        run(cmav<complex<float>,1>(f.vis.data(),{f.vis.size()})); participants=0;
      }
      return out;
    };
    size_t participants, different=0, minthreads=999;
    auto first=invert(true,participants);
    minthreads=std::min(minthreads,participants);
    for (int rep=1; rep<repeats; ++rep) {
      if (!same_finite(first,invert(true,participants))) ++different;
      minthreads=std::min(minthreads,participants);
    }
    check(different==0,"double calculation/float visibility repeatability");
    check(minthreads>1,"mixed precision actual gridding participation");
    check(all_finite(first),"mixed precision finite output");
    auto plain=invert(false,participants);
    check(same_finite(first,plain),"mixed precision tracked/plain equality");
    size_t plain_different=0;
    for (int rep=1; rep<repeats; ++rep)
      if (!same_finite(plain,invert(false,participants))) ++plain_different;
    check(plain_different==0,"mixed precision uninstrumented inversion repeats");
    check(f.same(saved),"mixed precision immutable inputs");
    std::cout << "mixed mode=" << mode << " w=" << w << " repeats=" << repeats
              << " differing=" << different << " plain_differing=" << plain_different
              << " min_grid_threads=" << minthreads << '\n';
  }
}

// Independent direct Fourier sum at every pixel of a small finite fixture.
// dirty2ms uses the negative phase; ms2dirty is its real adjoint. divide_by_n
// is explicitly false, so neither oracle includes a 1/n factor.
template<class T> void fourier_oracle() {
  for (int mode : {0,1,2}) for (bool w : {false,true}) {
    Fixture<T> f(mode,true), saved=f;
    size_t ignored;
    auto image=f.invert(w,8,false,ignored);
    ErrorStats error;
    std::vector<size_t> freqbase{0};
    for (auto n:f.nf) freqbase.push_back(freqbase.back()+n);
    for (size_t x=0; x<f.nx; ++x) for (size_t y=0; y<f.ny; ++y) {
      long double l=(double(x)-double(f.nx)/2)*f.px;
      long double m=(double(y)-double(f.ny)/2)*f.py;
      long double nm1=std::sqrt(1-l*l-m*m)-1, sum=0;
      for (size_t r=0; r<f.nr; ++r) for (size_t ch=0; ch<f.nf[f.ids[r]]; ++ch) {
        size_t k=f.offsets[r]+ch;
        long double fact=f.freqs[freqbase[f.ids[r]]+ch]/c;
        long double phase=2*std::acos(-1.L)*fact*(f.uvw[3*r]*l+f.uvw[3*r+1]*m-(w?f.uvw[3*r+2]*nm1:0));
        sum += f.mask[k]*f.weights[k]*(f.vis[k].real()*std::cos(phase)-f.vis[k].imag()*std::sin(phase));
      }
      error.observe(static_cast<long double>(image[x*f.ny+y]),sum);
    }
    const long double limit=std::is_same_v<T,float> ? 4.e-4L : 4.e-9L;
    check(error.within(limit),"direct Fourier image oracle");
    std::cout << "oracle " << (std::is_same_v<T,float>?"float":"double")
              << " mode=" << mode << " w=" << w << " relative_max_error="
              << double(error.maxerr/std::max(1.L,error.scale)) << " limit=" << double(limit) << '\n';
    std::vector<T> sky(f.nx*f.ny,0);
    sky[(f.nx/2)*f.ny+f.ny/2]=T(1);
    sky[(f.nx/2+2)*f.ny+f.ny/2-3]=T(-.25);
    auto sky_saved=sky;
    auto pred=f.predict(sky,w,complex<T>(T(12),T(-7)));
    ErrorStats prediction_error;
    for (size_t r=0; r<f.nr; ++r) for (size_t ch=0; ch<f.nf[f.ids[r]]; ++ch) {
      size_t k=f.offsets[r]+ch;
      complex<long double> sum(0);
      for (size_t x=0; x<f.nx; ++x) for (size_t y=0; y<f.ny; ++y) if (sky[x*f.ny+y]!=0) {
        long double l=(double(x)-double(f.nx)/2)*f.px;
        long double m=(double(y)-double(f.ny)/2)*f.py;
        long double nm1=std::sqrt(1-l*l-m*m)-1;
        long double fact=f.freqs[freqbase[f.ids[r]]+ch]/c;
        long double phase=-2*std::acos(-1.L)*fact*(f.uvw[3*r]*l+f.uvw[3*r+1]*m-(w?f.uvw[3*r+2]*nm1:0));
        sum += static_cast<long double>(sky[x*f.ny+y])*complex<long double>(std::cos(phase),std::sin(phase));
      }
      sum *= static_cast<long double>(f.weights[k]*f.mask[k]);
      prediction_error.observe(complex<long double>(pred[k]),sum);
    }
    check(prediction_error.within(limit,false),"direct Fourier prediction oracle");
    std::cout << "prediction_oracle max_error=" << double(prediction_error.maxerr) << " limit=" << double(limit) << '\n';
    check(f.same(saved)&&bytes(sky,sky_saved),"oracle immutable inputs");
  }
}
} // namespace
int main(int argc,char** argv) {
  try {
    if (argc>1 && std::string(argv[1])=="--nonfinite") {
      nonfinite_guards();
      std::cout << "checks=" << checks << " failures=" << failures << '\n';
      return failures ? 1 : 0;
    }
    if (argc>1 && std::string(argv[1])=="--periodic") {
      periodic_crossing(argc>2 && std::string(argv[2])=="regular",
                        argc>3 && std::string(argv[3])=="v");
      std::cout << "checks=" << checks << " failures=" << failures << '\n';
      return failures ? 1 : 0;
    }
    int repeats=argc>1 ? std::stoi(argv[1]) : 8;
    if (repeats<2) throw std::runtime_error("at least two repeats required");
    nonfinite_guards();
    for (bool regular : {false,true}) for (bool v_axis : {false,true})
      periodic_crossing(regular,v_axis);
    fourier_oracle<float>(); fourier_oracle<double>();
    repeatability<float>(repeats); repeatability<double>(repeats);
    mixed_precision_repeatability(repeats);
  } catch (const std::exception& e) { ++failures; std::cerr << "EXCEPTION " << e.what() << '\n'; }
  std::cout << "checks=" << checks << " failures=" << failures << '\n';
  return failures ? 1 : 0;
}
