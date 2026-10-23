# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Synthetic analyzer fixtures only; never substitutes for measured campaign evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits

from bench import analyze_cpu_campaign as analyzer


PRODUCTS = {f'img-{name}.fits' for name in
            ('dirty', 'horizon-mask', 'image', 'model', 'psf', 'residual')}
PLAN = dict(tag='synthetic-run', variant='synthetic-variant', mode='cpu', repeat=1,
            size=3072, threads=1, profile=False, monitor=False, sample=False,
            warmup=False, common=False)
TIME = ('real 10\nuser 8\nsys 1\n1024 maximum resident set size\n'
        '100 instructions retired\n200 cycles elapsed\n')
STAGES = 'Inversion: 00:00:01, prediction: 00:00:02, deconvolution: 00:00:03\n'


class MicroComplete(Exception):
    """Stop main after micro validation, before output/plotting or measured analysis."""


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='synthetic-cpu-analyzer-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(analyzer, 'ROOT', self.root).start()
        self.art = self.root / 'art'
        self.art.mkdir()
        self.left, self.right = self.root / 'left', self.root / 'right'
        self.left.mkdir()
        self.right.mkdir()

    def write_products(self):
        for folder in (self.left, self.right):
            for name in PRODUCTS:
                fits.writeto(folder / name, np.ones((2, 2), dtype=np.float32), overwrite=True)

    def write_runs(self, plan=None, runs=None, time=TIME, stages=STAGES):
        plan = [copy.deepcopy(PLAN)] if plan is None else plan
        runs = [dict(PLAN, exit=0)] if runs is None else runs
        (self.art / 'synthetic-plan.json').write_text(json.dumps(plan))
        (self.art / 'synthetic-runs.json').write_text(json.dumps(runs))
        folder = self.root / 'bench/out' / PLAN['tag'] / PLAN['variant']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'time.txt').write_text(time)
        (folder / 'wsclean.log').write_text(stages)

    def test_valid_synthetic_runs(self):
        self.write_runs()
        runs = analyzer.validated_runs(self.art, 'synthetic')
        self.assertEqual(runs[0]['timing']['wall_s'], 10)

    def test_malformed_or_mismatched_runs_raise_valueerror(self):
        cases = [([], []), ([PLAN], []), ([PLAN, PLAN], [dict(PLAN, exit=0)] * 2),
                 ({'tag': 'wrong-container'}, []), ([None], [None]),
                 ([{}], [dict(exit=0)]), ([PLAN], [None])]
        for key, value in [('tag', 'wrong'), ('variant', 'wrong'), ('size', 4096),
                           ('exit', 1), ('exit', None)]:
            cases.append(([PLAN], [dict(PLAN, exit=0, **{key: value})]
                          if key != 'exit' else [dict(PLAN, exit=value)]))
        for key in ('tag', 'variant', 'exit'):
            receipt = dict(PLAN, exit=0)
            del receipt[key]
            cases.append(([PLAN], [receipt]))
        for plan, runs in cases:
            with self.subTest(plan=plan, runs=runs):
                self.write_runs(plan, runs)
                with self.assertRaises(ValueError):
                    analyzer.validated_runs(self.art, 'synthetic')

    def test_invalid_run_times_and_counters_raise_valueerror(self):
        for time, stages in [(TIME.replace('real 10', 'real 0'), STAGES),
                             (TIME.replace('real 10', 'real NaN'), STAGES),
                             (TIME, STAGES.replace('00:00:03', '00:00:00')),
                             (TIME.replace('1024 maximum', '0 maximum'), STAGES),
                             (TIME.replace('1024 maximum resident set size\n', ''), STAGES),
                             (TIME.replace('100 instructions retired\n', ''), STAGES),
                             (TIME.replace('200 cycles elapsed', '0 cycles elapsed'), STAGES)]:
            with self.subTest(time=time, stages=stages):
                self.write_runs(time=time, stages=stages)
                with self.assertRaises(ValueError):
                    analyzer.validated_runs(self.art, 'synthetic')

    def test_each_side_requires_exact_products_before_comparing(self):
        for sides in ((self.left,), (self.right,), (self.left, self.right)):
            for missing in PRODUCTS:
                with self.subTest(sides=sides, missing=missing):
                    self.write_products()
                    for folder in sides:
                        (folder / missing).unlink()
                    with patch.object(analyzer, 'compare') as compare:
                        with self.assertRaises(ValueError):
                            analyzer.gate(self.left, self.right, 'synthetic', 'T0')
                        compare.assert_not_called()
        self.write_products()
        for folder in (self.left, self.right):
            (folder / 'extra.fits').touch()
        with self.assertRaises(ValueError):
            analyzer.gate(self.left, self.right, 'synthetic', 'T0')

    def test_empty_directories_rejected_under_python_optimized(self):
        code = '''from pathlib import Path
from bench.analyze_cpu_campaign import gate
import sys
try:
    gate(Path(sys.argv[1]), Path(sys.argv[2]), 'synthetic', 'T0')
except ValueError:
    sys.exit(0)
sys.exit(9)
'''
        result = subprocess.run([sys.executable, '-O', '-c', code, str(self.left), str(self.right)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_synthetic_gate_and_original_threshold_failures(self):
        self.write_products()
        self.assertTrue(analyzer.gate(self.left, self.right, 'synthetic', 'T0')['passed'])
        for delta, t0, t2 in [(1e-5, False, True), (2e-4, False, False)]:
            fits.writeto(self.right / 'img-residual.fits',
                         np.full((2, 2), 1 + delta, dtype=np.float32), overwrite=True)
            for tier, expected in [('T0', t0), ('T2', t2)]:
                self.assertEqual(analyzer.gate(self.left, self.right, 'synthetic', tier)['passed'], expected)

    def micro_lines(self, size, checks=10080):
        return [f'weighted differential checks={checks} failures=0'] + [
            f'timing,{size},{mask},{rep},{role},{4 if role == 0 else 1}'
            for mask in (0, 1) for rep in range(9) for role in (0, 1)]

    def run_micro(self, lines):
        for size, label in [(3072, '3k'), (4096, '4k')]:
            (self.art / f'weighted-micro-{label}.log').write_text('\n'.join(lines[size]) + '\n')
        tags = ['cpuaudit-20261022-threads-r1-j1', 'cpuopt-20261022-deterministic',
                'cpuopt-20261022-common-base', 'cpuopt-20261022-common-new',
                'cpuopt-20261022-common-aa']
        for size, reps, roles in [('3k', 3, ('base', 'new', 'aa')), ('4k', 2, ('base', 'new'))]:
            tags.extend(f'cpuopt-20261022-{size}-r{rep}-{role}'
                        for rep in range(1, reps + 1) for role in roles)
        runs = [dict(tag=tag, variant='synthetic', size=0, role='synthetic') for tag in tags]
        with patch.object(sys, 'argv', ['analyzer', '--art', str(self.art), '--out', str(self.root / 'out')]), \
             patch.object(analyzer, 'validated_runs', return_value=runs), \
             patch.object(analyzer, 'gate', return_value={'passed': False}), \
             patch.object(analyzer, 'load', side_effect=MicroComplete):
            analyzer.main()

    def test_valid_synthetic_micro_accepts_original_and_latest_check_counts(self):
        for checks in (10080, 10084):
            with self.subTest(checks=checks), self.assertRaises(MicroComplete):
                self.run_micro({size: self.micro_lines(size, checks) for size in (3072, 4096)})

    def test_invalid_micro_records_raise_valueerror(self):
        mutations = {
            'wrong-size': lambda rows: [s.replace('timing,4096,', 'timing,3072,') for s in rows],
            'duplicate-repetition': lambda rows: rows[:3] + [rows[1]] + rows[4:],
            'wrong-mask': lambda rows: rows[:1] + [rows[1].replace(',0,0,0,', ',2,0,0,')] + rows[2:],
            'wrong-role': lambda rows: rows[:1] + [rows[1].replace(',0,0,0,', ',0,0,2,')] + rows[2:],
            'wrong-repetition': lambda rows: rows[:1] + [rows[1].replace(',0,0,0,', ',0,9,0,')] + rows[2:],
            'missing-row': lambda rows: rows[:-1],
            'extra-row': lambda rows: rows + [rows[1]],
            'truncated-row': lambda rows: rows[:1] + ['timing,4096'] + rows[2:],
            'missing-summary': lambda rows: rows[1:],
            'failed-summary': lambda rows: [rows[0].replace('failures=0', 'failures=1')] + rows[1:],
            'zero-checks': lambda rows: [rows[0].replace('checks=10080', 'checks=0')] + rows[1:],
            'malformed-summary': lambda rows: ['weighted differential checks=oops failures=0'] + rows[1:],
            'duplicate-summary': lambda rows: rows + [rows[0]],
        }
        for duration in ('NaN', 'inf', '-1', '0'):
            mutations['duration-' + duration] = lambda rows, d=duration: rows[:1] + [
                ','.join(rows[1].split(',')[:5] + [d])] + rows[2:]
        for name, mutate in mutations.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.run_micro({3072: self.micro_lines(3072), 4096: mutate(self.micro_lines(4096))})


if __name__ == '__main__':
    unittest.main()
