"""SIMULATED trace inputs only: these tests are not GPU measurements."""
import json
import unittest
from gpu_profile_check import validate


def span(stage, **overrides):
    record = dict(type='span', stage=stage, id='simulated-1',
                  start=100.0, end=101.0, ok=True)
    record.update(overrides)
    return 'MX_PROFILE ' + json.dumps(record)


def prediction_trace():
    # Deliberately overlapping CPU/GPU intervals; do not require serialization.
    return '\n'.join(span(stage) for stage in
                     ('prediction.prepare', 'fft.gpu', 'prediction.consume'))


class SimulatedTraceTests(unittest.TestCase):
    def test_simulated_prediction_overlap(self):
        self.assertEqual(len(validate(prediction_trace())), 3)

    def test_real_numerical_text_without_trace_is_insufficient(self):
        with self.assertRaisesRegex(ValueError, 'no MX_PROFILE'):
            validate('PASS numerical probe\nMX prediction proof: completed=2\n')

    def test_simulated_cpu_fallback_does_not_establish_gpu(self):
        trace = '\n'.join(span(s) for s in
                          ('prediction.prepare', 'prediction.fallback', 'prediction.consume'))
        with self.assertRaisesRegex(ValueError, 'no completed GPU'):
            validate(trace)

    def test_simulated_missing_prediction_stages(self):
        for missing in ('prediction.prepare', 'prediction.consume'):
            trace = '\n'.join(line for line in prediction_trace().splitlines() if missing not in line)
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, missing):
                validate(trace)

    def test_simulated_peak_only_requires_explicit_mode(self):
        self.assertEqual(len(validate(span('peak.gpu'), prediction=False)), 1)
        with self.assertRaises(ValueError):
            validate(span('peak.gpu'))

    def test_disabled_negative_control(self):
        self.assertEqual(validate('normal stderr\n', disabled=True), [])
        with self.assertRaisesRegex(ValueError, 'disabled profile'):
            validate(prediction_trace(), disabled=True)

    def test_simulated_bad_intervals_cpu_and_gpu(self):
        for stage in ('prediction.prepare', 'fft.gpu'):
            for overrides in ({'start': float('nan')}, {'end': float('inf')},
                              {'start': -1}, {'end': 0}, {'start': True},
                              {'end': '101'}, {'end': 99}, {'start': 10**400}):
                with self.subTest(stage=stage, overrides=overrides), self.assertRaises(ValueError):
                    validate(prediction_trace() + '\n' + span(stage, **overrides))

    def test_simulated_incomplete_or_zero_gpu_interval(self):
        for overrides in ({'ok': False}, {'ok': None}, {'end': 100}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate(prediction_trace() + '\n' + span('fft.gpu', **overrides))

    def test_simulated_malformed_records(self):
        for text in ('MX_PROFILE not-json', 'MX_PROFILE []',
                     span('fft.gpu', id=''), span('fft.gpu', type='unknown'),
                     span('fft.gpu', bytes=-1), span('fft.gpu', plane=True),
                     span('fft.gpu', ok=1)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate(text)

    def test_zero_duration_cpu_event_is_valid(self):
        validate(prediction_trace() + '\n' + span('prediction.prepare', end=100))


if __name__ == '__main__':
    unittest.main()
