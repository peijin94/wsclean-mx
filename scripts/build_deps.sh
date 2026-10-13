#!/usr/bin/env bash
# Build dependencies that Homebrew cannot provide at the required version into
# a project-local prefix (deps/install), leaving system packages untouched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/env.sh"

CASACORE_TAG="${CASACORE_TAG:-v3.8.2}"
SRC="$ROOT/deps/src"
mkdir -p "$SRC" "$DEPS_PREFIX"

if [ ! -d "$SRC/casacore" ]; then
  git clone --depth 1 --branch "$CASACORE_TAG" \
    https://github.com/casacore/casacore.git "$SRC/casacore"
fi

"$CMAKE" -S "$SRC/casacore" -B "$SRC/casacore/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$DEPS_PREFIX" \
  -DCMAKE_PREFIX_PATH="$BREW" \
  -DCMAKE_Fortran_COMPILER="$BREW/bin/gfortran" \
  -DBUILD_PYTHON=OFF -DBUILD_PYTHON3=OFF \
  -DBUILD_TESTING=OFF \
  -DUSE_OPENMP=OFF -DUSE_THREADS=ON \
  -DUSE_FFTW3=ON -DUSE_HDF5=OFF -DUSE_ADIOS2=OFF -DUSE_MPI=OFF \
  -DDATA_DIR="$BREW/opt/casacore-data/data"

"$CMAKE" --build "$SRC/casacore/build" -j "$(sysctl -n hw.ncpu)"
"$CMAKE" --install "$SRC/casacore/build"
