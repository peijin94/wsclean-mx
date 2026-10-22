#!/usr/bin/env python3
"""Check that a fresh/reused PSF keeps the actual automatic scale configuration."""
import argparse
from pathlib import Path
import re
from astropy.io import fits


def check(reference, reused):
    first = fits.getheader(reference/'img-psf.fits')
    second = fits.getheader(reused/'img-psf.fits')
    assert first.get('WSCTBEAM', 0) > 0, 'reference PSF omitted theoretical beam WSCTBEAM'
    assert second.get('WSCTBEAM', 0) == first['WSCTBEAM'], 'theoretical beam not restored'
    def scales(directory):
        return re.findall(r'^- Scale .*kernel peak=.*$', (directory/'wsclean.log').read_text(), re.M)
    a, b = scales(reference), scales(reused)
    assert a and a == b, f'automatic scale configuration changed: {a} -> {b}'
    print(f'PASS: WSCTBEAM={first["WSCTBEAM"]:.17g} rad; {len(a)} identical scale/kernel/bias records')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('reused', type=Path)
    args = parser.parse_args()
    check(args.reference, args.reused)
