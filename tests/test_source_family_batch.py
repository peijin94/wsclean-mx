"""Synthetic fixtures validate cached/uncached gate equivalence, not GPU results."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
import numpy as np
from astropy.io import fits
from bench import compare_sources, source_family_batch
from tests.test_compare_sources import synthetic_image


class SourceFamilyBatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        image = synthetic_image()
        self.paths = {}
        for label, factor in [('a', 1.0), ('b', 0.9), ('outside', 1.5)]:
            p = self.root / label; p.mkdir()
            fits.writeto(p/'img-dirty.fits', image*np.float32(factor))
            self.paths[label] = str(p)
        self.config = {'groups': [{'name': 'fixture', 'references': [self.paths['a'],self.paths['b']],
                                   'candidates': self.paths.copy()}]}

    def test_cache_matches_independent_cli_logic_and_preserves_failures(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = source_family_batch.run(self.config, self.root/'batch')
        self.assertEqual(rc, 1)
        summary = json.loads((self.root/'batch/summary.json').read_text())
        self.assertEqual(summary['unique_products_read'], 3)
        self.assertEqual([r['exit'] for r in summary['records']], [0,0,1])
        for label in self.paths:
            output = self.root/(label+'.json')
            args = ['compare_sources.py','--candidate',self.paths[label],self.paths['a'],self.paths['b'],'--json',str(output)]
            with patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()):
                compare_sources.main()
            self.assertEqual(json.loads(output.read_text()),json.loads((self.root/f'batch/fixture-{label}.json').read_text()))

    def test_missing_product_rejected_before_creating_output(self):
        fits.writeto(Path(self.paths['a'])/'img-model.fits',np.ones((8,8),dtype=np.float32))
        with self.assertRaises(ValueError):source_family_batch.run(self.config,self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_colliding_flat_output_names_rejected_before_writes(self):
        refs=[self.paths['a'],self.paths['b']]
        config={'groups':[
            {'name':'a-b','references':refs,'candidates':{'c':self.paths['a']}},
            {'name':'a','references':refs,'candidates':{'b-c':self.paths['b']}}]}
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            source_family_batch.run(config,self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_bad_output_label_rejected(self):
        self.config['groups'][0]['name']='../escape'
        with self.assertRaises(ValueError):source_family_batch.run(self.config,self.root/'out')
        self.assertFalse((self.root/'out').exists())
