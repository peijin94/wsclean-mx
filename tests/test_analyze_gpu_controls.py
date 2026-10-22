"""Synthetic analyzer fixtures; their log strings are NOT GPU execution evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from astropy.io import fits

ROOT=Path(__file__).resolve().parents[1]


class AnalyzeGpuControlsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.plan=[['cpu1',False,'common',{}],['cpu2',False,'common',{}],['gpu1',True,'common',{}]]
        self.runs=[]
        for label,gpu,fixture,env in self.plan:
            tag=self.root/label;directory=tag/'variant';directory.mkdir(parents=True)
            for product in ['dirty','psf','model','image','residual']:
                h=fits.Header();h['WSCTBEAM']=0.001
                fits.writeto(directory/f'img-{product}.fits',np.ones((8,8),dtype=np.float32),h)
            # Deliberately simulated parser input, not measurements.
            (directory/'time.txt').write_text('MX prediction proof: shared_planes=2 submitted=1 completed=1 cpu_fallback=0 grid_memcpy_bytes=0\n' if gpu else '')
            self.runs.append(dict(label=label,gpu=gpu,fixture=fixture,env=env,exit=0,tag=str(tag),command=['bash','bench/run.sh','variant']))

    def invoke(self):
        (self.root/'control-plan.json').write_text(json.dumps({'plan':self.plan}))
        (self.root/'control-runs.json').write_text(json.dumps(self.runs))
        return subprocess.run([sys.executable,str(ROOT/'bench/analyze_gpu_controls.py'),str(self.root),str(self.root/'report')],capture_output=True,text=True,timeout=30)

    def assert_rejected(self):
        result=self.invoke()
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertFalse((self.root/'report/causal.json').exists())

    def test_duplicate_cpu_records_cannot_replace_gpu_control(self):
        self.runs=[copy.deepcopy(self.runs[0]) for _ in self.plan]
        self.assert_rejected()

    def test_unplanned_label_rejected(self):
        self.runs[1]['label']='unplanned';self.assert_rejected()

    def test_changed_fixture_rejected(self):
        self.runs[1]['fixture']='ulp-plus';self.assert_rejected()

    def test_changed_env_rejected(self):
        self.runs[1]['env']={'MX_METAL_NO_PREDICT':'1'};self.assert_rejected()

    def test_changed_gpu_role_rejected(self):
        self.runs[2]['gpu']=False
        (Path(self.runs[2]['tag'])/'variant/time.txt').write_text('')
        self.assert_rejected()

    def test_matching_records_accepted(self):
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(json.loads((self.root/'report/causal.json').read_text())['common_input_pass'])
