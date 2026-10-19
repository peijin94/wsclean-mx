# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
#
# Homebrew formula for wsclean-mx: Apple-Silicon optimized WSClean.
#
# Status: LOCAL BOTTLE STAGING ONLY — do not publish until 0.1.0 is tagged.
# Brew only accepts tap formulas, so stage with:
#   brew tap-new peijin94/wsclean-mx   (once)
#   cp Formula/wsclean-mx.rb "$(brew --repo peijin94/wsclean-mx)/Formula/"
#   brew install --HEAD --build-bottle peijin94/wsclean-mx/wsclean-mx
#   brew bottle wsclean-mx   # (after install, produces the bottle tarball)
# This file is the source of truth; the tap copy is disposable.
#
# At release time fill in the v0.1.0 tarball url/sha256 below (the `head`
# line stays for development builds).

class WscleanMx < Formula
  desc "WSClean optimized for Apple Silicon (multithreaded gridding/deconvolution)"
  homepage "https://github.com/peijin94/wsclean-mx"
  # Release tarball (fill in at 0.1.0 tag time; the `head` line below is
  # what local --HEAD bottle staging uses until then):
  # url "https://github.com/peijin94/wsclean-mx/archive/refs/tags/v0.1.0.tar.gz"
  # sha256 "<release tarball sha256>"
  head "https://github.com/peijin94/wsclean-mx.git", branch: "main"
  version "0.1.0"

  depends_on arch: :arm64
  depends_on macos: :sequoia
  depends_on "cmake" => :build
  depends_on "ninja" => :build
  depends_on "pkgconf" => :build
  depends_on "bison" => :build # casacore requires bison >= 3; macOS ships 2.3
  depends_on "gcc" => :build # Fortran for the casacore resource
  depends_on "boost"
  depends_on "cfitsio"
  depends_on "fftw"
  depends_on "gsl"
  depends_on "hdf5"
  depends_on "open-mpi"
  depends_on "python@3.15"
  depends_on "ska-sa/tap/casacore-data"

  # casacore 3.8.2: Homebrew core ships 3.4.0, which is too old, so the
  # formula vendors the pinned revision (mirrors scripts/build_deps.sh).
  resource "casacore" do
    url "https://github.com/casacore/casacore/archive/refs/tags/v3.8.2.tar.gz"
    sha256 "aa6cf40aaadc71b85d10718d5140479cce6f889f506f8fdf1a7a4b90fb7dfee5"
  end

  # Upstream sources at the exact pins in upstream/wsclean/CMakeLists.txt.
  # The wsclean-mx patch set (patches/build + patches/mx) is applied to
  # these in #install, mirroring scripts/mx_tree.sh.
  resource "wsclean-src" do
    url "https://gitlab.com/aroffringa/wsclean.git", revision: "2d5c1ed8d7559e5178d243661b408baa288681e6", using: :git
  end
  resource "aocommon-src" do
    url "https://gitlab.com/aroffringa/aocommon.git", revision: "e1b7980e02211ade95eef176a3ac7f9ba3dcc55c", using: :git
  end
  resource "schaapcommon-src" do
    url "https://git.astron.nl/RD/schaapcommon.git", revision: "b47f19dace28ad420c0a7c8ab1014b55b75205e9", using: :git
  end
  resource "radler-src" do
    url "https://git.astron.nl/RD/radler.git", revision: "940e9617a4b3210228a849513752f0732df8104a", using: :git
  end

  def install
    # The casacore resource lives permanently inside this keg (libexec), so
    # the bottled wsclean links it by its keg-absolute path — never by the
    # temporary build directory.
    casacore_prefix = libexec/"casacore"
    resource("casacore").stage do
      mkdir "mx-build" do
        args = %W[
          -DCMAKE_BUILD_TYPE=Release
          -DCMAKE_INSTALL_PREFIX=#{casacore_prefix}
          -DCMAKE_PREFIX_PATH=#{Formula["gcc"].opt_prefix}
          -DCMAKE_Fortran_COMPILER=#{Formula["gcc"].opt_bin}/gfortran
          -DBUILD_PYTHON=OFF -DBUILD_PYTHON3=OFF
          -DBUILD_TESTING=OFF
          -DUSE_OPENMP=OFF -DUSE_THREADS=ON
          -DUSE_FFTW3=ON -DUSE_HDF5=OFF -DUSE_ADIOS2=OFF -DUSE_MPI=OFF
          -DDATA_DIR=#{Formula["ska-sa/tap/casacore-data"].opt_share}/casacore/data
        ]
        system "cmake", "-S", "..", "-G", "Ninja", *args
        system "cmake", "--build", "."
        system "cmake", "--install", "."
      end
    end

    src = {
      "wsclean"      => "wsclean-src",
      "aocommon"     => "aocommon-src",
      "schaapcommon" => "schaapcommon-src",
      "radler"       => "radler-src",
    }.transform_values do |res|
      dest = buildpath/res
      resource(res).stage { cp_r ".", dest }
      dest
    end

    # Apply the patch set in the same order as scripts/mx_tree.sh:
    # build portability fixes first, then the mx optimization stack.
    # (Plain `git apply` runs in each staged source dir; no repo needed.)
    ohai "Applying wsclean-mx patch set"
    {
      "wsclean"      => "2d5c1ed8d755",
      "schaapcommon" => "b47f19dace28",
    }.each do |repo, base12|
      cd src[repo] do
        Dir["#{buildpath}/patches/build/#{repo}/#{base12}/*.patch"].sort.each do |p|
          system "git", "apply", p
        end
      end
    end
    src.each do |repo, dest|
      cd dest do
        Dir["#{buildpath}/patches/mx/#{repo}/*.patch"].sort.each do |p|
          system "git", "apply", p
        end
      end
    end

    mkdir "build" do
      args = %W[
        -DCMAKE_BUILD_TYPE=Release
        -DCMAKE_CXX_FLAGS=-I#{casacore_prefix}/include
        -DCASACORE_ROOT_DIR=#{casacore_prefix}
        -DCMAKE_PREFIX_PATH=#{casacore_prefix};#{HOMEBREW_PREFIX}
        -DBUILD_TESTING=OFF
        -DFETCHCONTENT_SOURCE_DIR_AOCOMMON=#{src["aocommon"]}
        -DFETCHCONTENT_SOURCE_DIR_SCHAAPCOMMON=#{src["schaapcommon"]}
        -DFETCHCONTENT_SOURCE_DIR_RADLER=#{src["radler"]}
      ]
      system "cmake", "-S", src["wsclean"], "-B", ".", "-G", "Ninja", *args
      system "cmake", "--build", ".", "--target", "wsclean"
      bin.install "wsclean"
      # wsclean's threading runtime: a build-tree shared lib the binary loads
      # via @rpath. Upstream forces CMAKE_BUILD_WITH_INSTALL_RPATH=FALSE, so
      # the built binary only knows the build dir; point it at the keg lib
      # the same way bench/snapshot.sh does for frozen snapshots.
      lib.install "libschaapthreading.dylib"
      system "install_name_tool", "-add_rpath", lib, bin/"wsclean"
      system "codesign", "--force", "--sign", "-", bin/"wsclean"
    end
  end

  test do
    assert_match "WSClean version", shell_output("#{bin}/wsclean -version")
  end
end
