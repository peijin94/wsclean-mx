#!/usr/bin/env python3
"""Require real completed GPU work for every supported differential case.

Usage: prediction_gpu_check.py <mx-prediction-gpu-probe> [width [height]]
A correct CPU fallback is not sufficient for this GPU acceptance gate.
"""
import os
import re
import subprocess
import sys


def verify(stdout, stderr):
    cases = re.findall(r'^float .*wgrid=1 mode=0 .* PASS$', stdout, re.M)
    proofs = re.findall(
        r'MX prediction proof: shared_planes=(\d+) submitted=(\d+) '
        r'completed=(\d+) cpu_fallback=(\d+) grid_memcpy_bytes=(\d+)', stderr)
    executed = [tuple(map(int, row)) for row in proofs if int(row[1]) > 0]
    if not cases or len(executed) != len(cases):
        raise ValueError(f'{len(cases)} supported cases but {len(executed)} executed GPU sessions')
    for shared, submitted, completed, fallback, copied in executed:
        if shared != 2 or completed != submitted or fallback or copied:
            raise ValueError(f'invalid execution proof: {(shared, submitted, completed, fallback, copied)}')
    return len(cases), sum(row[2] for row in executed)


def main():
    env = os.environ.copy()
    env['MX_METAL_DEBUG_TIMING'] = '1'
    env.pop('MX_METAL_NO_PREDICT', None)
    result = subprocess.run(sys.argv[1:], env=env, capture_output=True, text=True)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    if result.returncode:
        return result.returncode
    try:
        cases, planes = verify(result.stdout, result.stderr)
    except ValueError as exc:
        print(f'FAIL: GPU execution proof: {exc}', file=sys.stderr)
        return 1
    print(f'PASS: {cases} differential cases, {planes} completed GPU planes, zero fallback/copy bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
