#!/usr/bin/env python3
"""Fail if a configured Metal executable omits its hook registration code."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wsclean_binary import mx_binary

build = Path(sys.argv[1]).resolve()
commands = json.loads((build / 'compile_commands.json').read_text())
main = [c for c in commands if c['file'].endswith('/main/main.cpp')]
assert len(main) == 1, 'Expected exactly one main.cpp compilation'
assert '-DWSCLEAN_MX_METAL=1' in main[0]['command'], 'Metal hooks compiled out of main.cpp'
symbols = subprocess.check_output(['nm', '-C', str(mx_binary(build))], text=True)
for name in ('_mx_peak_find', '_mx_convolve_c2r', '_mx_convolve_many',
             '_mx_predict_register', '_mx_prediction_create'):
    assert name in symbols, f'{name} implementation absent from executable'
print('PASS: Metal entrypoint compiled and hook implementations linked; runtime counters still required')
