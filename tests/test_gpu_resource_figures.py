"""Synthetic parser fixtures only: no GPU/science evidence or plot rendering."""
import ast
from copy import deepcopy
from pathlib import Path
import unittest

from bench.analyze_gpu_resources import summarize_spans


# Load only the pure helper, without importing/initializing plotting libraries.
SOURCE = Path(__file__).resolve().parents[1] / 'bench/plot_gpu_resources.py'
TREE = ast.parse(SOURCE.read_text())
HELPER = next(node for node in TREE.body
              if isinstance(node, ast.FunctionDef) and node.name == 'copy_totals')
NAMESPACE = {}
exec(compile(ast.Module(body=[HELPER], type_ignores=[]), str(SOURCE), 'exec'), NAMESPACE)
copy_totals = NAMESPACE['copy_totals']

CASES = ('baseline-convolution', 'resident', 'fused')


def required_stages(case):
    return ('convolution.copy_inputs', 'fusion.copy_inputs', 'fusion.copy_output') if case == 'fused' else (
        'convolution.copy_inputs', 'convolution.copy_output')


def synthetic_parser_fixture(case):
    """Invented byte counts parsed by the production trace summarizer."""
    stages = required_stages(case)
    spans = [dict(stage=stage, start=float(i), end=i + 0.5, bytes=size)
             for i, (stage, size) in enumerate(zip(stages, (100, 20, 40) if case == 'fused' else (100, 40)))]
    trace, _ = summarize_spans(spans)
    return dict(case=case, stages=trace,
                convolution={} if case == 'baseline-convolution' else {'kernel_bytes': 30})


class CopyTotalsTest(unittest.TestCase):
    def test_synthetic_baseline_resident_and_fused_totals(self):
        for case, expected in zip(CASES, ((100, 0, 40), (130, 0, 40), (130, 20, 40))):
            with self.subTest(case=case):
                run = synthetic_parser_fixture(case)
                before = deepcopy(run)
                self.assertEqual(copy_totals(run), expected)
                self.assertEqual(run, before)

    def test_each_required_stage_and_byte_counter_must_exist(self):
        for case in CASES:
            for stage in required_stages(case):
                for missing in ('stage', 'bytes'):
                    with self.subTest(case=case, stage=stage, missing=missing):
                        run = synthetic_parser_fixture(case)
                        if missing == 'stage':
                            del run['stages'][stage]
                        else:
                            del run['stages'][stage]['bytes']
                        with self.assertRaisesRegex(ValueError, stage):
                            copy_totals(run)

    def test_candidate_kernel_counter_must_exist(self):
        for case in ('resident', 'fused'):
            with self.subTest(case=case):
                run = synthetic_parser_fixture(case)
                del run['convolution']['kernel_bytes']
                with self.assertRaisesRegex(ValueError, 'kernel_bytes'):
                    copy_totals(run)

    def test_wrong_output_stage_is_not_a_readback_receipt(self):
        for case in CASES:
            with self.subTest(case=case):
                run = synthetic_parser_fixture(case)
                expected = required_stages(case)[-1]
                other = 'convolution.copy_output' if case == 'fused' else 'fusion.copy_output'
                run['stages'][other] = run['stages'].pop(expected)
                run['convolution']['output_copy_bytes'] = 40
                with self.assertRaisesRegex(ValueError, expected):
                    copy_totals(run)

    def test_invalid_byte_values_are_rejected_individually(self):
        invalid = (-1, -0.5, float('nan'), float('inf'), -float('inf'), None, '40', True)
        for case in CASES:
            for field in (*required_stages(case), 'kernel_bytes'):
                for value in invalid:
                    with self.subTest(case=case, field=field, value=value):
                        run = synthetic_parser_fixture(case)
                        target = run['convolution'] if field == 'kernel_bytes' else run['stages'][field]
                        target['kernel_bytes' if field == 'kernel_bytes' else 'bytes'] = value
                        with self.assertRaisesRegex(ValueError, field):
                            copy_totals(run)

    def test_explicit_zero_receipts_are_valid(self):
        for case in CASES:
            with self.subTest(case=case):
                run = synthetic_parser_fixture(case)
                for receipt in run['stages'].values():
                    receipt['bytes'] = 0
                run['convolution']['kernel_bytes'] = 0
                self.assertEqual(copy_totals(run), (0, 0, 0))

    def test_present_legacy_kernel_counter_is_counted(self):
        run = synthetic_parser_fixture('baseline-convolution')
        run['convolution']['kernel_bytes'] = 30
        self.assertEqual(copy_totals(run), (130, 0, 40))


if __name__ == '__main__':
    unittest.main()
