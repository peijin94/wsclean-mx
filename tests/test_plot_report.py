# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Regressions for the benchmark report's mode awareness.

bench/plot_report.py must not present a wall ratio as a variant cost unless
bench/ab.sh's mode file says the comparison is `comparable`, and must say so
when a comparison has no mode file at all.
"""

import tempfile
import unittest
from pathlib import Path

from bench import plot_report


class ModeAwarenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def write_mode(self, tag, text):
        path = self.out / f'{tag}-ab.mode.txt'
        path.write_text(text)
        return path

    def test_absent_when_no_mode_file(self):
        self.assertEqual(plot_report.mode_status('p1', self.out), 'absent')
        self.assertEqual(plot_report.ratio_note('p1', self.out),
                         ' [no mode file: wall-clock only]')

    def test_comparable(self):
        self.write_mode('t', 'comparable\nvariant: wall 1.0-1.1s | counters\n')
        self.assertEqual(plot_report.mode_status('t', self.out), 'comparable')
        self.assertEqual(plot_report.ratio_note('t', self.out), '')

    def test_stall_mode_mismatch(self):
        self.write_mode('t', 'stall mode mismatch between a and b: similar instructions, '
                             'cycles differ\nmore detail\n')
        self.assertEqual(plot_report.mode_status('t', self.out), 'stall mode mismatch')
        self.assertEqual(plot_report.ratio_note('t', self.out), ' [stall mode mismatch]')

    def test_unclassified_variants(self):
        for text in ('hardware counters unavailable, incomplete or invalid: wall comparison '
                     'is unclassified',
                     'container variant(s) linc: host counters measure the container CLI, not '
                     'guest execution, so the wall comparison is unclassified',
                     'host mode present within a: repeats span several cycle levels, so the '
                     'wall comparison is unclassified',
                     'counter scope differs between a and b: instruction counts differ by more '
                     'than 20%, so the wall comparison is unclassified',
                     'single variant: nothing to compare'):
            self.write_mode('t', text + '\n')
            self.assertEqual(plot_report.mode_status('t', self.out), 'unclassified', text)
            self.assertEqual(plot_report.ratio_note('t', self.out), ' [unclassified]')

    def test_unrecognised_first_line_is_not_treated_as_comparable(self):
        self.write_mode('t', 'something new the plotter has never seen\n')
        self.assertEqual(plot_report.mode_status('t', self.out), 'unrecognised')
        self.assertEqual(plot_report.ratio_note('t', self.out), ' [unrecognised]')

    def test_blank_leading_lines_are_skipped(self):
        self.write_mode('t', '\n\n comparable \n')
        self.assertEqual(plot_report.mode_status('t', self.out), 'comparable')

    def test_figure_note_names_every_unverified_comparison(self):
        self.write_mode('a', 'comparable\n')
        self.assertEqual(plot_report.figure_mode_note(['a'], self.out),
                         'mode-verified: hardware counters comparable for every comparison')
        note = plot_report.figure_mode_note(['a', 'b', 'c'], self.out)
        self.assertIn('b=absent', note)
        self.assertIn('c=absent', note)
        self.assertNotIn('a=', note)

    def test_figure_note_reports_a_stall_mismatch_by_name(self):
        self.write_mode('a', 'comparable\n')
        self.write_mode('b', 'stall mode mismatch between a and b: similar instructions, '
                             'cycles differ\n')
        note = plot_report.figure_mode_note(['a', 'b'], self.out)
        self.assertIn('b=stall mode mismatch', note)


if __name__ == '__main__':
    unittest.main()
