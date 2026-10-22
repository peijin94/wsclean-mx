"""Synthetic interval arithmetic tests, not performance measurements."""
import unittest
from bench.analyze_gpu_profile import merge_intervals,measure,intersect,subtract,parse_times,monitor_summary

class ProfileMathTest(unittest.TestCase):
    def test_union_not_sum_of_overlapping_gpu_commands(self):
        self.assertEqual(measure([(1,3),(2,4)]),3)
        self.assertEqual(merge_intervals([(3,4),(1,2),(2,3)]),[(1,4)])
    def test_intersection(self):
        self.assertEqual(measure(intersect([(1,2),(3,4)],[(1.5,3.5)])),1)
    def test_subtraction(self):
        self.assertEqual(subtract([(1,5)],[(2,3),(4,7)]),[(1,2),(3,4)])
    def test_empty_and_invalid(self):
        self.assertEqual(measure([]),0)
        with self.assertRaises(ValueError):merge_intervals([(3,2)])
    def test_window_statistics_exclude_outside_samples(self):
        rows=[{'mach_s':i,'query_end_mach_s':i+.001,'Device Utilization %':gpu,
               'cpu_user_s':i,'cpu_system_s':0} for i,gpu in [(1,5),(2,10),(3,99),(4,99)]]
        result=monitor_summary(rows,[(1,2)])
        self.assertEqual(result['device_gauge_max_percent'],5)
        self.assertEqual(result['samples'],1)

    def test_timing_requires_all_stages(self):
        with self.assertRaises(ValueError):parse_times('real 1.0','Inversion: 00:00:01.0')
        d=parse_times('real 10.0\nuser 20.0\nsys 2.0\n100 maximum resident set size','Inversion: 00:00:04.0, prediction: 00:00:02.0, deconvolution: 00:00:03.0')
        self.assertEqual(d['other_s'],1)
        self.assertEqual(d['cpu_core_equivalent'],2.2)
