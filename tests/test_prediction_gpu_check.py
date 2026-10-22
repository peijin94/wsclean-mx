"""Unit fixtures for the execution-proof parser, not scientific results."""
import unittest
from prediction_gpu_check import verify


class PredictionProofTest(unittest.TestCase):
    case = 'float 192x252 threads=3 shift=1 wgrid=1 mode=0 rel_rms=1e-7 max/peak=2e-7 PASS\n'

    @staticmethod
    def proof(submitted=8, completed=8, fallback=0, copied=0):
        return (f'MX prediction proof: shared_planes=2 submitted={submitted} '
                f'completed={completed} cpu_fallback={fallback} grid_memcpy_bytes={copied}\n')

    def test_completed_sessions_match_supported_cases(self):
        self.assertEqual(verify(self.case * 2, self.proof() * 2), (2, 16))

    def test_preflight_only_is_not_gpu_validation(self):
        with self.assertRaises(ValueError):
            verify(self.case, self.proof(submitted=0, completed=0))

    def test_no_case_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            verify('', self.proof())

    def test_missing_session_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            verify(self.case * 2, self.proof())

    def test_partial_failure_and_copies_fail(self):
        for proof in (self.proof(completed=7), self.proof(fallback=1), self.proof(copied=1024)):
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                verify(self.case, proof)
