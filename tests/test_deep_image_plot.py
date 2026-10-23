"""The publication renderer reads real FITS pixels, masks and p99 limits."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'docs/bench/exo-deep-150k-20261023/plot_images.py'


class DeepImagePlotTest(unittest.TestCase):
    def renderer(self):
        self.assertTrue(SCRIPT.is_file(), 'Missing tracked deep-image renderer')
        spec = importlib.util.spec_from_file_location('deep_image_plot', SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError('Cannot load publication renderer')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_actual_fits_mask_and_p99_drive_rendered_panels(self):
        renderer = self.renderer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ref, candidate = root / 'ref', root / 'candidate'
            ref.mkdir(); candidate.mkdir()
            image = np.full((10, 10), 2.0, dtype=np.float32)
            image[0, 0] = 1e8  # masked: must not set the colour scale
            mask = np.ones_like(image); mask[0, 0] = 0
            residual = np.full_like(image, 0.125)
            for name, pixels in [('image', image), ('residual', residual), ('horizon-mask', mask)]:
                fits.writeto(ref / f'img-{name}.fits', pixels)
            fits.writeto(candidate / 'img-image.fits', image)
            out = root / 'image.png'
            result = renderer.render_case(ref, candidate, out, 'fixture')
            self.assertEqual(result['restored_p99'], 2.0)
            self.assertEqual(result['residual_abs_p99'], 0.125)
            self.assertEqual(result['repeat_max_abs_difference'], 0.0)
            self.assertEqual(result['kept_pixels'], 99)
            self.assertEqual(out.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')


    def test_rejects_invalid_horizon_masks_before_writing(self):
        renderer = self.renderer()
        for mask in (np.zeros((10, 10)), np.ones((5, 10)), np.full((10, 10), 2.0)):
            with self.subTest(shape=mask.shape, value=mask[0, 0]), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                ref, candidate = root / 'ref', root / 'candidate'
                ref.mkdir(); candidate.mkdir()
                image = np.ones((10, 10), dtype=np.float32)
                for name, pixels in [('image', image), ('residual', image), ('horizon-mask', mask)]:
                    fits.writeto(ref / f'img-{name}.fits', pixels)
                fits.writeto(candidate / 'img-image.fits', image)
                out = root / 'image.png'
                with self.assertRaises(ValueError):
                    renderer.render_case(ref, candidate, out, 'invalid fixture')
                self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
