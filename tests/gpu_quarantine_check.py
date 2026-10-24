#!/usr/bin/env python3
"""Binary-level quarantine regression; no imaging, MS access, or GPU dispatch.

Usage: python3 tests/gpu_quarantine_check.py BUILD [--cpu-only]
Run against freshly rebuilt production binaries, with archive both OFF and ON.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wsclean_binary import mx_binary


def check(build, cpu_only=False):
    binary = mx_binary(build.resolve())
    failures = []
    symbols = subprocess.check_output(['nm', '-C', str(binary)], text=True)
    retired = ('mx::metal::inversion(', 'mx::metal::inversionSupported(',
               'mx::metal::cpuGridPlane(', 'mx::metal::gridAccumulate(',
               'mx::metal::gridDegrid(', 'mx::metal::evalEsKernel(',
               'mx::metal::deviceInfo(', 'mx::metal::variantName(')
    for name in retired:
        if name in symbols:
            failures.append(f'retired symbol linked: {name}')
    for engine in (None, '', 'metal', 'cpu-vkfft', 'unknown', ' '):
        env = os.environ.copy()
        env.pop('MX_METAL_ENGINE', None)
        if engine is not None:
            env['MX_METAL_ENGINE'] = engine
        # -version returns during parsing: even the pre-quarantine binary
        # cannot reach science I/O or GPU dispatch with these arguments.
        result = subprocess.run([str(binary), '-mgpu', '-version'], env=env,
                                capture_output=True, text=True, timeout=15)
        output = result.stdout + result.stderr
        expected = ('-mgpu requires a build with WSCLEAN_MX_METAL=ON' if cpu_only
                    else 'MX_METAL_ENGINE is retired' if engine else None)
        print(f'engine={engine!r} rc={result.returncode}\n{output}')
        if expected:
            if result.returncode == 0 or expected not in output:
                failures.append(f'engine={engine!r}: expected nonzero and {expected!r}')
        elif result.returncode != 0:
            failures.append(f'engine={engine!r}: plain -mgpu -version failed')
        # The environment must not affect CPU-only operation without -mgpu.
        result = subprocess.run([str(binary), '-version'], env=env,
                                capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or 'MX_METAL_ENGINE is retired' in result.stdout + result.stderr:
            failures.append(f'engine={engine!r}: CPU -version affected')
    for failure in failures:
        print(f'FAIL: {failure}', file=sys.stderr)
    if failures:
        return 1
    print('PASS: production binary excludes retired symbols and enforces CLI quarantine')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('--cpu-only', action='store_true')
    args = parser.parse_args()
    sys.exit(check(args.build, args.cpu_only))
