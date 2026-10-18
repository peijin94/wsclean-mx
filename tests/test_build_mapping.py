# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""The native gate must not combine unrelated libraries and work-tree headers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mx-build-map-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.marker = self.build / "tests-started"
        self.python_stub = self.build / "python-test-sentinel"
        self.python_stub.write_text('#!/bin/sh\nprintf started > "$DRIVER_MARKER"\nexit 42\n')
        self.python_stub.chmod(0o755)
        self.mapping = {
            "CMAKE_HOME_DIRECTORY:INTERNAL": ROOT / "work/wsclean",
            "FETCHCONTENT_SOURCE_DIR_AOCOMMON:PATH": ROOT / "work/aocommon",
            "FETCHCONTENT_SOURCE_DIR_SCHAAPCOMMON:PATH": ROOT / "work/schaapcommon",
            "FETCHCONTENT_SOURCE_DIR_RADLER:PATH": ROOT / "work/radler",
        }

    def run_driver(self, mapping):
        (self.build / "CMakeCache.txt").write_text("\n".join(f"{key}={value}" for key, value in mapping.items()) + "\n")
        return subprocess.run(
            ["bash", str(ROOT / "scripts/test.sh"), str(self.build)],
            env=dict(os.environ, PYTHON=str(self.python_stub), DRIVER_MARKER=str(self.marker)),
            text=True, capture_output=True, check=False)

    def test_rejects_each_unrelated_source_before_starting_tests(self):
        for key in self.mapping:
            with self.subTest(key=key):
                bad = dict(self.mapping)
                bad[key] = ROOT / "upstream/wsclean"
                result = self.run_driver(bad)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("source mapping", result.stderr)
                self.assertFalse(self.marker.exists())

    def test_missing_source_mapping_is_rejected(self):
        for key in self.mapping:
            with self.subTest(key=key):
                incomplete = dict(self.mapping)
                del incomplete[key]
                result = self.run_driver(incomplete)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("source mapping", result.stderr)
                self.assertFalse(self.marker.exists())

    def test_matching_source_mapping_reaches_test_phase(self):
        result = self.run_driver(self.mapping)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.marker.read_text(), "started")


if __name__ == "__main__":
    unittest.main()
