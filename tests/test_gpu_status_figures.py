"""Tests use synthetic arrays only; these are not GPU/science evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]


class TestGpuStatusFigures(unittest.TestCase):
    def test_real_fits_to_full_field_and_requested_zoom(self):
        script = ROOT / 'bench/plot_gpu_status.py'
        self.assertTrue(script.exists(), 'missing reproducible GPU status image renderer')
        spec = importlib.util.spec_from_file_location('gpu_status_plot', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpu_dir, gpu_dir, out = root/'cpu', root/'gpu', root/'out'
            cpu_dir.mkdir(); gpu_dir.mkdir(); out.mkdir()
            cpu = (1 + np.arange(32*48).reshape(32, 48)/1000).astype('float32')
            gpu = (cpu + np.float32(0.01)).astype('float32')
            mask = np.ones_like(cpu); mask[:2] = 0
            for folder, data in [(cpu_dir, cpu), (gpu_dir, gpu)]:
                hdr = fits.Header({'BUNIT': 'Jy/beam'})
                fits.writeto(folder/'img-image.fits', data, hdr)
                fits.writeto(folder/'img-horizon-mask.fits', mask)
            result = module.render_comparison(cpu_dir, gpu_dir, out, 'test-version')
            self.assertEqual(result['shape_yx'], [32, 48])
            self.assertEqual(result['crop']['center_xy'], [12, 19])
            self.assertEqual(result['crop']['bounds_xyxy'], [6, 15, 18, 23])
            self.assertEqual(result['pixel_origin'], 'lower; zero-based x=column, y=row')
            self.assertEqual(result['full']['pixels'], int(np.count_nonzero(mask)))
            self.assertAlmostEqual(result['full']['vmax_cpu_p99'], np.percentile(cpu[mask > 0], 99.0))
            diff = gpu.astype('float64') - cpu.astype('float64')
            expected = np.sqrt(np.mean(diff[mask > 0]**2)) / np.sqrt(np.mean(cpu[mask > 0].astype('float64')**2))
            self.assertAlmostEqual(result['full']['relative_rms'], expected)
            for name in ['restored-full-field.png', 'restored-extended-zoom.png']:
                self.assertTrue((out/name).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))

    def test_missing_receipt_rejected_before_reading_images(self):
        import json
        import sys
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('gpu_status_missing_receipt', ROOT/'bench/plot_gpu_status.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for receipt_count in (0, 1, 3):
            with self.subTest(receipt_count=receipt_count):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    raw = root/'raw'; raw.mkdir()
                    config = {'plan': [{'tag': 'trial-0'}, {'tag': 'trial-1'}],
                              'image_cpu_tag': 'nonexistent-status-test-cpu',
                              'image_gpu_tag': 'nonexistent-status-test-gpu',
                              'source_root_commit': 'test',
                              'crop_center_fraction_xy': [0.25, 0.6],
                              'crop_extent_fraction_xy': [0.25, 0.25]}
                    (raw/'config.json').write_text(json.dumps(config))
                    (raw/'runs.json').write_text(json.dumps(config['plan']))
                    receipts = [{'tag': f'trial-{i}', 'exit': 0} for i in range(receipt_count)]
                    (raw/'receipts.json').write_text(json.dumps(receipts))
                    with patch.object(sys, 'argv', ['plot_gpu_status.py', str(raw), str(root/'out')]):
                        try:
                            module.main()
                        except Exception as error:
                            self.assertIsInstance(error, ValueError,
                                                  'missing receipt must fail before any FITS access')
                            self.assertIn('campaign', str(error))
                        else:
                            self.fail('missing receipt was accepted')


if __name__ == '__main__':
    unittest.main()
