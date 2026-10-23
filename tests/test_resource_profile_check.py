"""Synthetic parser tests only; these fixtures are not native GPU evidence."""
import json
import unittest
from resource_profile_check import check


def synthetic_trace(aggregate=True,command_id=7):
    """Synthetic public-probe-shaped trace including non-command spans."""
    def span(stage,cid,start,end,byte_count=0):
        return 'MX_PROFILE '+json.dumps(dict(stage='fusion.'+stage,id=42,
            command_id=cid,start=start,end=end,bytes=byte_count))
    lines=[span('copy_inputs',0,1,1.1,32),
           span('encode_commit',command_id,1.1,1.2),
           span('wait',command_id,1.2,2),span('gpu',command_id,1.3,1.8)]
    if aggregate:
        lines.extend([span('copy_output',0,2,2.1,64),span('total',0,1,2.2)])
    return '\n'.join(lines)


class SyntheticResourceProfileTest(unittest.TestCase):
    def test_synthetic_public_probe_aggregate_spans_are_not_commands(self):
        self.assertEqual(check(synthetic_trace()),
            {'commands':1,'positive_gpu_intervals':1,'copied_bytes':32})

    def test_synthetic_zero_command_ids_do_not_prove_gpu_commands(self):
        with self.assertRaisesRegex(AssertionError,'no completed timed GPU commands'):
            check(synthetic_trace(aggregate=False,command_id=0))

    def test_synthetic_command_still_requires_all_three_events(self):
        for missing in ('encode_commit','wait','gpu'):
            text='\n'.join(line for line in synthetic_trace().splitlines()
                           if 'fusion.'+missing not in line)
            with self.subTest(missing=missing),self.assertRaises(AssertionError):
                check(text)

    def test_synthetic_command_clock_bracketing_is_preserved(self):
        text=synthetic_trace().replace('"end": 1.8','"end": 3')
        with self.assertRaises(AssertionError):check(text)

    def test_synthetic_command_without_aggregates_remains_valid(self):
        self.assertEqual(check(synthetic_trace(aggregate=False))['commands'],1)


if __name__=='__main__':unittest.main()
