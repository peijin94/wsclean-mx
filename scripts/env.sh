# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
# Shared build environment. Source, don't execute.
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BREW="$(brew --prefix)"
# MacPorts cmake (/opt/local/bin) is first on PATH and too old; pin Homebrew's.
CMAKE="$BREW/bin/cmake"
DEPS_PREFIX="$ROOT/deps/install"
export ROOT BREW CMAKE DEPS_PREFIX
export PATH="$BREW/bin:$PATH"
