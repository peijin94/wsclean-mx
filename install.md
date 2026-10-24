# Installing wsclean-mx

Choose the CPU release for ordinary use, or build `gpu-dev` explicitly to test
Metal. Release 0.1.1 names the primary command **`wsclean-mx`**, replacing the
package’s old `wsclean` command without installing a compatibility alias.
Installing the Homebrew package does **not** enable Metal.

| Installation | Executable | GPU support |
|---|---|---|
| Homebrew CPU release | `wsclean-mx` | No; rejects `-mgpu` |
| CPU source build at `v0.1.1` | `build-mx/wsclean-mx` | Off by default |
| Experimental Metal source build | `build-mx-metal/wsclean-mx` | `-mgpu` enables prediction; deconvolution requires additional opt-ins |

The build scripts target Apple Silicon macOS. The current GPU implementation was
validated on an Apple M2 with 16 GiB RAM and macOS 27.0.1; that is a tested
configuration, not a claim of validation on every Mac or macOS version.

> **Experimental GPU status:** inversion and CPU gridding/degridding stay on
> ducc0. GPU convolution and resident peak processing still fail strict
> CPU-reference image checks on the deep 3K/4K workloads. No dependable
> whole-program speedup was demonstrated for the new deconvolution path. Keep
> these features opt-in and validate your own science products. See the
> [resource-residency report](docs/gpu-resource-optimization-2026-10-22.md).

## 1. Prerequisites

Install [Homebrew](https://docs.brew.sh/Installation) if it is not already
available, following its shell setup instructions. Use native arm64 tools, not a
Rosetta shell. Check your environment:

```bash
uname -m                    # arm64
brew --prefix               # normally /opt/homebrew
xcode-select -p              # selected developer-tools directory
```

If Command Line Tools are missing, run `xcode-select --install` and finish the
installer before building. Full Xcode and a standalone `metal` compiler are not
required by this backend: its shaders compile at runtime from source strings.

## 2. Homebrew CPU release

```bash
brew tap peijin94/wsclean-mx
brew install peijin94/wsclean-mx/wsclean-mx
command -v wsclean-mx
wsclean-mx -version
```

Homebrew selects a compatible bottle when available; otherwise it may build from
source. The checked-in formula declares arm64 and macOS Sequoia or newer, but
bottle availability is specific to the OS/platform. Follow any Homebrew tap-trust
prompt deliberately; do not bypass its checks.

To update this installation:

```bash
brew update
brew upgrade peijin94/wsclean-mx/wsclean-mx
```

`brew install --HEAD` follows `gpu-dev`, but the formula still explicitly builds
CPU-only and labels the MX version `HEAD`. For Metal, use the source instructions
below. Stable 0.1.1 reports both `wsclean-mx version 0.1.1` and upstream
`WSClean version 3.7`. The formula is maintained in
[`Formula/wsclean-mx.rb`](Formula/wsclean-mx.rb).

## 3. Source-build dependencies

Install these once for either source-build route:

```bash
brew install cmake ninja pkgconf bison gcc fftw cfitsio hdf5 gsl boost \
  openblas wcslib pybind11 open-mpi uv
brew tap ska-sa/tap
brew install ska-sa/tap/casacore-data

# casacore needs GNU Bison >= 3, not the older system Bison.
export PATH="$(brew --prefix bison)/bin:$(brew --prefix)/bin:$PATH"
bison --version
```

The scripts use Homebrew's CMake explicitly and build casacore into
`deps/install` rather than using an older system casacore. The dependency script
currently defaults to casacore 3.8.2. Do not run the build scripts with `sudo`.

The examples below use separate, fresh checkout names so CPU and GPU builds do
not overwrite each other. Run all subsequent commands from the selected checkout's
root directory. HTTPS cloning does not require GitHub SSH-key setup.

### CPU source build

```bash
git clone --recurse-submodules --branch v0.1.1 \
  https://github.com/peijin94/wsclean-mx.git wsclean-mx-cpu
cd wsclean-mx-cpu
unset ROOT

scripts/build_deps.sh
scripts/build_mx.sh
build-mx/wsclean-mx -version
```

`build_mx.sh` creates missing `work/` developer trees, applies the exported
patches, configures the CPU build and checks that the correct casacore headers
were used. `build_mx.sh` honors `JOBS` and defaults to four build jobs.
`build_deps.sh` still derives its build parallelism from `hw.ncpu` rather than
using `JOBS`.

### Experimental Metal source build

```bash
git clone --recurse-submodules --branch gpu-dev \
  https://github.com/peijin94/wsclean-mx.git wsclean-mx-gpu
cd wsclean-mx-gpu
unset ROOT

scripts/build_deps.sh
scripts/mx_tree.sh init
JOBS=4 scripts/metal_build.sh --reconfigure
scripts/check_headers.sh build-mx-metal
build-mx-metal/wsclean-mx -version
```

**Do not skip `scripts/mx_tree.sh init`:** unlike `build_mx.sh`, the Metal build
script expects the patched `work/{wsclean,aocommon,schaapcommon,radler}` trees to
exist. It enables `WSCLEAN_MX_METAL=ON`, disables the retired inversion archive,
and maps all patched dependencies to those work trees.

The Metal build script honors `JOBS`; four build jobs is a conservative starting
point on a 16 GiB Mac. The dependency build still uses its own parallelism as
noted above. A fresh checkout also needs network access to the pinned upstream
and dependency Git repositories.

## 4. Use the intended executable

The source builds run in place. Prefer an explicit path when comparing CPU and
GPU installations:

```bash
build-mx-metal/wsclean-mx -version
```

Optionally add **one** build directory to the current shell's PATH, from the
checkout root:

```bash
export PATH="$PWD/build-mx-metal:$PATH"
command -v wsclean-mx
type -a wsclean-mx
```

For a CPU source build, use `$PWD/build-mx` instead. Persist an absolute path in
your shell configuration only if desired. This can shadow the Homebrew CPU
executable; use `command -v` to check which one will run.

Do not copy just the source-built executable into `/usr/local/bin` or delete its
checkout afterward. It depends on the local casacore installation and a
build-directory `libschaapthreading.dylib`. Keep the build and `deps/install` in
place. For a relocatable packaged CPU installation, use Homebrew instead.

## 5. GPU execution and opt-in controls

A Metal build without `-mgpu` uses CPU execution. Plain `-mgpu` enables the
bounded two-slot prediction FFT path; it does **not** offload inversion. A
`-niter 0` dirty-image run is not proof of GPU prediction execution.

Example deep-imaging invocation, from the GPU checkout root. Replace the MS path
with a disposable working copy and choose a fresh output directory:

```bash
mkdir -p output && mkdir output/run-001 && mkdir output/run-001/tmp && \
MX_METAL_DEBUG_TIMING=1 build-mx-metal/wsclean-mx \
  -mgpu -j 8 -size 3072 3072 -scale 2.7amin -weight briggs 0 -pol I \
  -multiscale -multiscale-scale-bias 0.8 -niter 150000 -mgain 0.95 \
  -auto-threshold 0.5 -auto-mask 3 -local-rms -horizon-mask 10deg -mem 40 \
  -reorder -no-update-model-required -data-column CORRECTED_DATA \
  -temp-dir output/run-001/tmp -name output/run-001/img \
  "/path/to/working-copy.ms"
```

The chained directory creation prevents accidentally reusing this example's
output name. The MS flags are not a general read-only sandbox: protect valuable
inputs independently and never predict into the original science MS.
The explicit column assumes the MS has `CORRECTED_DATA`; choose the intended
column deliberately for other data. The iteration budget is a cap, not a
requirement to continue after the stopping threshold is reached.
For 4096-square comparisons in this benchmark family, use `-scale 2amin`.

Set environment controls **before the executable**, in addition to `-mgpu`:

| Variable | Purpose |
|---|---|
| `MX_METAL_DEBUG_TIMING=1` | Print completed-work and resource counters |
| `MX_METAL_PROFILE=1` | Add structured timing/copy spans; keep profiling separate from timing runs |
| `MX_METAL_MEMORY_MB=1024` | Shared owned-buffer-capacity budget, in integer MiB; 1024 is the default |
| `MX_METAL_CONVOLVE=1` | Opt into GPU multiscale convolution and immutable kernel residency |
| `MX_METAL_FUSE=1` | With convolution enabled, opt into resident weighting/peak processing |
| `MX_METAL_NO_PLAN_CACHE=1` | Disable plan retention for an ablation |
| `MX_METAL_NO_KERNEL_CACHE=1` | Disable immutable kernel residency for an ablation |
| `MX_METAL_NO_FUSE=1` | Disable the fused peak hook |
| `MX_METAL_PREDICT_SERIAL=1` | Diagnostic immediate waits instead of normal overlap |

For example, the experimental combination prefixes the imaging command with
`MX_METAL_MEMORY_MB=1024 MX_METAL_CONVOLVE=1 MX_METAL_FUSE=1`.
Leave these deconvolution opt-ins unset for the prediction-only default.

The buffer budget covers explicitly owned Metal buffer capacities, including
FFT workspaces and both prediction slots, rounded to 16 KiB. It is **not** a hard
limit on total physical unified memory, driver overhead or process RSS. Accepted
budget values are decimal integers from 1 through 65536 MiB. An explicitly invalid
value disables backend buffer allocations rather than silently increasing the cap.
A valid but insufficient cap can cause CPU fallback; do not count fallback as GPU
acceleration. Increasing the cap is not a correctness or performance fix.

## 6. Verify the build

For the development branch, set up the repository's Python test environment and
run the active regression suite:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r bench/requirements.txt
JOBS=4 scripts/test.sh build-mx-metal
```

Use `scripts/test.sh build-mx` for a CPU build. In an existing checkout, reuse an
appropriate existing virtual environment rather than replacing it blindly.
The suite rebuilds the selected executable, checks source/header mappings and
runs linked numerical and active Metal gates. Fixture-dependent upstream
integration tests are separate; native test success is not scientific release
approval.

For real imaging, inspect `MX_METAL_DEBUG_TIMING=1` output for nonzero submitted
and completed prediction work and any fallback counts. A version string, accepted
`-mgpu` flag, successful compilation or CPU fallback is not sufficient proof.

Run native Metal validation in a normal host terminal. A restricted coding-agent
sandbox can report no Metal device even on a working Mac. A skipped/no-device
probe is not a GPU pass. The retired GPU-inversion archive is deliberately not
part of this installation or the active validation path.

## 7. Updating source checkouts and troubleshooting

- **Downloaded patches changed, but your build did not:** `mx_tree.sh init`
  preserves existing work trees; it does not replay updated patches into them.
  Use a new checkout directory for an updated installation. Developers should
  reconcile/export their changes deliberately. Never use `init --force` as an
  update shortcut: it discards developer trees and unexported work.
- **Missing submodule:** in a fresh checkout, run
  `git submodule update --init --recursive` before initializing work trees.
  Do not edit `upstream/wsclean` in place.
- **Wrong CMake or casacore headers:** keep the Homebrew tools on PATH and run
  `scripts/check_headers.sh` against the selected build. Do not mix headers or
  libraries from unrelated casacore installations.
- **Bison version error:** put `$(brew --prefix bison)/bin` before the system
  directories on PATH, then retry the dependency build.
- **CMake source-directory mismatch:** use a fresh build/checkout directory or
  preserve the old directory under a different name. Do not reset a developer
  tree to force a cache to match.
- **`-mgpu requires a build with WSCLEAN_MX_METAL=ON`:** you invoked the CPU
  executable. Check `command -v wsclean-mx` and use `build-mx-metal/wsclean-mx` explicitly.
- **Missing dylib after moving the binary:** restore its build/dependency
  directories or rebuild. Copying one executable is not a source installation.
- **GPU output differs from CPU:** retain all products, commands and logs;
  consult the [known acceptance failures](docs/gpu-resource-optimization-2026-10-22.md).
  Do not loosen thresholds or silently substitute a fallback result.
