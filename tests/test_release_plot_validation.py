# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Parser unit tests with synthetic receipts; these are not release evidence."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = (Path(__file__).resolve().parents[1]
          / 'docs/bench/release-0.1.1/plot_validation.py')
SPEC = importlib.util.spec_from_file_location('release_plot_validation', SCRIPT)
plot_validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plot_validation)


class ReceiptParserUnitTests(unittest.TestCase):
    """Small isolated synthetic receipts only; never write production receipts."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='synthetic-receipt-parser-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def receipt(self, phase='native'):
        products = ('dirty', 'horizon-mask', 'image', 'model', 'psf', 'residual')
        return {
            'phase': phase, 'passed': True, 'input_unchanged': True,
            'runs': [
                {'run': {'phase': phase, 'size': size},
                 'gate': {
                     'label': f'{phase}-{size}', 'expected': 'T0', 'passed': True,
                     'left': str(self.root / 'imaging-baseline' / str(size)),
                     'right': str(self.root / f'imaging-{phase}' / str(size)),
                     'products': [
                         {'name': f'img-{name}.fits', 'T0': True, 'bitwise': True}
                         for name in products]}}
                for size in (3072, 4096)]}

    def write_receipt(self, phase, receipt):
        path = self.root / f'imaging-{phase}' / 'result.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(receipt))

    def run_main(self, artifacts=None):
        with mock.patch('sys.argv', [str(SCRIPT), '--artifacts',
                                     str(artifacts if artifacts is not None else self.root)]):
            plot_validation.main()

    def test_actual_schema_accepted_before_missing_next_phase(self):
        self.write_receipt('native', self.receipt())
        with mock.patch.object(plot_validation.plt, 'subplots') as subplots:
            with self.assertRaises(FileNotFoundError) as error:
                self.run_main()
            self.assertEqual(Path(error.exception.filename),
                             self.root / 'imaging-installed-v2/result.json')
            subplots.assert_not_called()

    def test_rejects_receipts_not_bound_to_phase_size_and_artifact_paths(self):
        changes = [
            (('phase',), 'poured'),
            (('phase',), None),
            (('runs', 0, 'run', 'phase'), 'poured'),
            (('runs', 0, 'run', 'phase'), None),
            (('runs', 0, 'run', 'size'), 4096),
            (('runs', 0, 'gate', 'label'), 'poured-3072'),
            (('runs', 0, 'gate', 'label'), 'native-4096'),
            (('runs', 0, 'gate', 'label'), None),
        ]
        for side in ('left', 'right'):
            for directory in (
                    self.root / 'imaging-baseline/4096',
                    self.root / 'imaging-poured/3072',
                    self.root.parent / 'other-artifacts/imaging-baseline/3072',
                    self.root.parent / 'other-artifacts/imaging-native/3072',
                    self.root / 'imaging-native-extra/3072',
                    self.root / 'imaging-native/3072/../../../outside',
                    None):
                changes.append((('runs', 0, 'gate', side),
                                str(directory) if directory is not None else None))
        changes.extend([
            (('runs', 0, 'gate', 'left'), str(self.root / 'imaging-native/3072')),
            (('runs', 0, 'gate', 'right'), str(self.root / 'imaging-baseline/3072')),
        ])
        original = self.receipt()
        for keys, value in changes:
            with self.subTest(keys=keys, value=value):
                receipt = copy.deepcopy(original)
                target = receipt
                for key in keys[:-1]:
                    target = target[key]
                if value is None:
                    target.pop(keys[-1])
                else:
                    target[keys[-1]] = value
                self.write_receipt('native', receipt)
                with self.assertRaises((ValueError, FileNotFoundError)) as error:
                    self.run_main()
                self.assertIsInstance(error.exception, ValueError,
                                      'Invalid native receipt advanced to next phase')

    def test_plot_loads_from_validated_gate_paths(self):
        # All three receipts here are isolated parser fixtures, not phase evidence.
        for phase in ('native', 'installed-v2', 'poured'):
            self.write_receipt(phase, self.receipt(phase))

        class StopBeforePlotting(Exception):
            pass

        with mock.patch.object(plot_validation.plt, 'subplots',
                               return_value=(mock.Mock(), mock.Mock())), \
                mock.patch.object(plot_validation.fits, 'getdata',
                                  side_effect=[[0], StopBeforePlotting]) as getdata:
            with self.assertRaises(StopBeforePlotting):
                self.run_main(os.path.relpath(self.root))
        self.assertEqual(getdata.call_args_list, [
            mock.call(self.root.resolve() / 'imaging-baseline/3072/img-image.fits'),
            mock.call(self.root.resolve() / 'imaging-poured/3072/img-image.fits')])

    def test_repository_relative_gate_paths_do_not_depend_on_working_directory(self):
        receipt = self.receipt()
        for run in receipt['runs']:
            for side in ('left', 'right'):
                run['gate'][side] = os.path.relpath(run['gate'][side], SCRIPT.parents[3])
        with mock.patch('os.getcwd', return_value=str(self.root)):
            validated = plot_validation.validate_phase(receipt, 'native', self.root)
        for size in (3072, 4096):
            self.assertEqual(validated[size], {
                'left': self.root.resolve() / 'imaging-baseline' / str(size),
                'right': self.root.resolve() / 'imaging-native' / str(size),
                'products': 6})

    def test_invalid_schema_and_non_t0_products_remain_rejected(self):
        changes = [
            (('passed',), False),
            (('input_unchanged',), False),
            (('runs', 0, 'run', 'size'), 3072.0),
            (('runs', 0, 'gate', 'expected'), 'T2'),
            (('runs', 0, 'gate', 'expected'), None),
            (('runs', 0, 'gate', 'passed'), False),
            (('runs', 0, 'gate', 'products', 1, 'name'), 'img-weights.fits'),
            (('runs', 0, 'gate', 'products', 1, 'name'), 'img-dirty.fits'),
        ]
        # Each of the six products must pass both saved verdict checks.
        for index in range(6):
            for flag in ('T0', 'bitwise'):
                changes.append((('runs', 0, 'gate', 'products', index, flag), False))
        for keys, value in changes:
            with self.subTest(keys=keys, value=value):
                receipt = self.receipt()
                target = receipt
                for key in keys[:-1]:
                    target = target[key]
                if value is None:
                    # A legacy tier field must not substitute for expected.
                    target.pop(keys[-1])
                    target['tier'] = 'T0'
                else:
                    target[keys[-1]] = value
                with self.assertRaises(ValueError):
                    plot_validation.validate_phase(receipt, 'native', self.root)


if __name__ == '__main__':
    unittest.main()
