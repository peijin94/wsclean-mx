#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Peijin Zhang
"""Source-level comparison of cleaned images against reference reruns.

Pixel RMS is not a science gate: multiscale cleaning is chaotic, so a candidate
can differ from the reference by more than the reference differs from itself
while still producing scientifically equivalent sources. This tool measures the
quantities that matter (total flux, peak, matched-source flux ratios, source
positions, PSF shape) for a candidate and for a set of reference reruns, so the
candidate can be judged against the reference's own run-to-run envelope.

    bench/compare_sources.py --candidate DIR REFERENCE_DIR [REFERENCE_DIR ...]

All products common to every directory are compared. Exit status is non-zero if
any product's candidate deviation exceeds the reference envelope, so it can be
used as a gate rather than a report.
"""

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from astropy.io import fits

PRODUCT_METRICS = ('total_flux', 'peak', 'peak_x', 'peak_y', 'mad_rms', 'second_moment')
MIN_PEAK_SIGMA = 6.0          # source detection: peak above this many MAD rms
MIN_PEAK_FRACTION = 0.01      # ... and above this fraction of the image peak, so
                              # near-zero clean components of a sparse model image
                              # cannot dominate the source statistics
MATCH_RADIUS_PX = 3.0         # source association radius
POSITION_RADIUS_PX = 4        # centroid window; wide enough that the profile is
                              # essentially complete inside it, so truncation on one
                              # side cannot bias the position by a fraction of a pixel
NUMERICAL_FLOOR = 1.0e-5      # predeclared float32 storage floor (see docs/science-gates.md):
                              # FITS products are 32-bit, so sums over ~4M pixels carry
                              # ~1e-6 relative rounding before any algorithmic difference
POSITION_FLOOR_PX = 0.01      # positions are sub-pixel centroids now, so exact equality is
                              # not the right bar when the reference envelope is zero;
                              # 1/100 pixel is far below any physical positional error



def read_image(path):
    with fits.open(path, memmap=False) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float64)
    data = np.squeeze(data)
    if data.ndim != 2:
        raise ValueError(f'{path}: expected a 2-D image, got shape {data.shape}')
    if not np.isfinite(data).all():
        raise ValueError(f'{path}: image contains non-finite pixels')
    return data


def mad_rms(data):
    median = np.median(data)
    return float(1.4826 * np.median(np.abs(data - median)))


def second_moment(data, centre):
    """Size proxy: sqrt(sum(r^2 I) / sum(I)) about a centre, in pixels."""
    yy, xx = np.indices(data.shape, dtype=np.float64)
    weight = np.clip(data, 0.0, None)
    total = weight.sum()
    if total <= 0:
        return 0.0
    dy = yy - centre[0]
    dx = xx - centre[1]
    return float(math.sqrt((weight * (dx * dx + dy * dy)).sum() / total))


def detect_sources(data, rms):
    """Brightest local maxima, non-maximum suppressed, with sub-pixel positions.

    A source must exceed both MIN_PEAK_SIGMA * rms and MIN_PEAK_FRACTION of the
    image peak. Its position is the flux-weighted centroid of the window around
    the maximum: sparse model images store components as delta-like peaks whose
    argmax flips between neighbouring pixels for sub-pixel differences, which
    would otherwise register as a positional disagreement.
    """
    peak_value = float(data.max())
    threshold = max(MIN_PEAK_SIGMA * rms, MIN_PEAK_FRACTION * peak_value)
    if not math.isfinite(threshold) or threshold <= 0:
        return np.empty((0, 3))
    peak = data.max()
    if peak <= threshold:
        return np.empty((0, 3))
    candidates = np.argwhere(data > threshold)
    order = np.argsort(data[candidates[:, 0], candidates[:, 1]])[::-1]
    found = []
    for index in order:
        y, x = candidates[index]
        centre_y, centre_x = source_position(data, int(y), int(x))
        # Suppress on the stored quantity: comparing candidate pixels against
        # stored centroids mixes two coordinate systems and lets the same peak be
        # reported many times through neighbouring flank pixels.
        if any((centre_y - fy) ** 2 + (centre_x - fx) ** 2 <= MATCH_RADIUS_PX ** 2
               for fy, fx, _ in found):
            continue
        found.append((centre_y, centre_x, float(data[y, x])))
        if len(found) >= 50:
            break
    return np.array(found, dtype=np.float64).reshape(-1, 3)


def source_position(data, y, x, radius=POSITION_RADIUS_PX):
    """Flux-weighted centroid of the window around a detected maximum."""
    y0, y1 = max(0, y - radius), min(data.shape[0], y + radius + 1)
    x0, x1 = max(0, x - radius), min(data.shape[1], x + radius + 1)
    window = np.clip(data[y0:y1, x0:x1], 0.0, None)
    total = float(window.sum())
    if total <= 0.0:
        return float(y), float(x)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    return float((window * yy).sum() / total), float((window * xx).sum() / total)


def metrics(data):
    rms = mad_rms(data)
    peak_index = np.unravel_index(int(np.argmax(data)), data.shape)
    result = {
        'total_flux': float(data.sum()),
        'peak': float(data[peak_index]),
        'peak_x': float(peak_index[1]),
        'peak_y': float(peak_index[0]),
        'mad_rms': rms,
        'second_moment': second_moment(data, peak_index),
        'shape': list(data.shape),
    }
    sources = detect_sources(data, rms)
    result['n_sources'] = int(len(sources))
    result['_sources'] = sources
    return result


def compare_sources(reference, candidate):
    """Flux ratios and position offsets for sources matched between two images.

    `unmatched` counts reference-side sources with no candidate counterpart;
    `unmatched_candidate` counts the reverse, so a source that appears only in
    one of the two images is visible whether or not anything else matched.
    """
    if len(reference) == 0 or len(candidate) == 0:
        return {'matched': 0, 'unmatched': int(len(reference)),
                'unmatched_candidate': int(len(candidate))}
    ratios, offsets, unmatched = [], [], 0
    for y, x, value in reference:
        distance = np.hypot(candidate[:, 0] - y, candidate[:, 1] - x)
        nearest = int(np.argmin(distance))
        if distance[nearest] > MATCH_RADIUS_PX:
            unmatched += 1
            continue
        other = candidate[nearest, 2]
        if value != 0:
            ratios.append(other / value)
        offsets.append(float(distance[nearest]))
    unmatched_candidate = sum(
        1 for y, x, _ in candidate
        if np.hypot(reference[:, 0] - y, reference[:, 1] - x).min() > MATCH_RADIUS_PX)
    if not ratios:
        return {'matched': 0, 'unmatched': unmatched,
                'unmatched_candidate': int(unmatched_candidate)}
    ratios = np.asarray(ratios)
    return {
        'matched': int(len(ratios)),
        'unmatched': unmatched,
        'unmatched_candidate': int(unmatched_candidate),
        'flux_ratio_median': float(np.median(ratios)),
        'flux_ratio_spread': float(np.max(np.abs(ratios - 1.0))),
        'position_offset_median_px': float(np.median(offsets)),
        'position_offset_max_px': float(np.max(offsets)),
    }


def product_files(directory):
    return {path.name: path for path in sorted(directory.glob('*.fits'))
            if path.name.startswith('img-')}


def jsonable(value):
    """Report data only: drop internal arrays and convert numpy scalars in place."""
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items() if not key.startswith('_')}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def relative_deviation(a, b):
    scale = max(abs(a), abs(b), 1e-30)
    return abs(a - b) / scale


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('references', nargs='+', type=Path,
                        help='reference rerun directories (at least two for an envelope)')
    parser.add_argument('--json', type=Path, help='also write the full comparison here')
    args = parser.parse_args()

    names = set(product_files(args.references[0]))
    for reference in args.references[1:]:
        names &= set(product_files(reference))
    names &= set(product_files(args.candidate))
    if not names:
        sys.exit('bench: no common product names across the given directories')

    report, failures = {}, []
    print(f"candidate: {args.candidate}")
    print(f"references: {', '.join(str(r) for r in args.references)}")
    print()
    header = (f"{'product':<18}{'metric':<26}{'reference':>14}{'env_med':>11}{'envelope':>12}"
              f"{'candidate':>14}{'deviation':>12}  result")
    print(header)
    print('-' * len(header))

    for name in sorted(names):
        reference_metrics = [metrics(read_image(product_files(r)[name])) for r in args.references]
        candidate_metrics = metrics(read_image(product_files(args.candidate)[name]))
        entry = {'references': reference_metrics, 'candidate': candidate_metrics, 'checks': {}}
        for key in PRODUCT_METRICS:
            values = [m[key] for m in reference_metrics]
            centre = float(np.median(values))
            deviations = [relative_deviation(a, b) for i, a in enumerate(values)
                          for b in values[i + 1:]]
            envelope = max(deviations, default=0.0)
            # The median says how tightly the reference family itself clusters;
            # the max is what the gate uses, so a single wild rerun cannot be
            # hidden behind a tight median.
            envelope_median = float(np.median(deviations)) if deviations else 0.0
            deviation = relative_deviation(centre, candidate_metrics[key])
            passed = deviation <= max(envelope, NUMERICAL_FLOOR)
            entry['checks'][key] = {'reference_median': centre, 'envelope': envelope,
                                    'envelope_median': envelope_median,
                                    'candidate': candidate_metrics[key], 'deviation': deviation,
                                    'threshold': max(envelope, NUMERICAL_FLOOR),
                                    'passed': bool(passed)}
            if not passed:
                failures.append(f'{name}: {key} deviation {deviation:.3e} > envelope {envelope:.3e}')
            print(f"{name:<18}{key:<26}{centre:>14.6g}{envelope_median:>11.3g}{envelope:>12.6g}"
                  f"{candidate_metrics[key]:>14.6g}{deviation:>12.3e}  "
                  f"{'PASS' if passed else 'FAIL'}")

        # Matched sources. The envelope comes from reference-versus-reference
        # pairs, never from the candidate itself, and the candidate is compared
        # against every reference rerun (worst case wins).
        candidate_checks = [compare_sources(m['_sources'], candidate_metrics['_sources'])
                            for m in reference_metrics]
        paired = [c for c in candidate_checks if c['matched']]
        pair_checks = [compare_sources(first['_sources'], second['_sources'])
                       for index, first in enumerate(reference_metrics)
                       for second in reference_metrics[index + 1:]]
        reference_pairs = [c for c in pair_checks if c['matched']]
        flux_envelope = max((c['flux_ratio_spread'] for c in reference_pairs), default=0.0)
        offset_envelope = max((c['position_offset_max_px'] for c in reference_pairs), default=0.0)
        entry['source_checks'] = {'candidate_vs_references': candidate_checks,
                                  'reference_pairs': pair_checks}
        if paired:
            worst_flux = max(c['flux_ratio_spread'] for c in paired)
            worst_offset = max(c['position_offset_max_px'] for c in paired)
            flux_ok = worst_flux <= max(flux_envelope, NUMERICAL_FLOOR)
            offset_ok = worst_offset <= max(offset_envelope, POSITION_FLOOR_PX) + 1e-9
            # A source seen by one image and not the other is a difference even
            # when everything else matched, so unmatched counts are checked too.
            unmatched_envelope = max((c['unmatched'] + c.get('unmatched_candidate', 0)
                                      for c in reference_pairs), default=0)
            unmatched_candidate = max(c['unmatched'] + c.get('unmatched_candidate', 0)
                                      for c in candidate_checks)
            unmatched_ok = unmatched_candidate <= unmatched_envelope
            entry['source_summary'] = {'matched': max(c['matched'] for c in paired),
                                       'flux_ratio_spread': worst_flux,
                                       'flux_ratio_envelope': flux_envelope,
                                       'position_offset_max_px': worst_offset,
                                       'position_offset_envelope_px': offset_envelope,
                                       'unmatched': unmatched_candidate,
                                       'unmatched_envelope': unmatched_envelope,
                                       'flux_passed': bool(flux_ok), 'position_passed': bool(offset_ok),
                                       'unmatched_passed': bool(unmatched_ok)}
            if not flux_ok:
                failures.append(f'{name}: source flux ratio spread {worst_flux:.3e} '
                                f'> reference envelope {flux_envelope:.3e}')
            if not offset_ok:
                failures.append(f'{name}: source position offset {worst_offset:.3f} px '
                                f'> reference envelope {offset_envelope:.3f} px')
            if not unmatched_ok:
                failures.append(f'{name}: {unmatched_candidate} unmatched source(s) '
                                f'> reference envelope {unmatched_envelope}')
            print(f"{name:<18}{'matched source flux':<26}{'':>14}{flux_envelope:>12.3e}"
                  f"{worst_flux:>14.3e}{'':>12}  {'PASS' if flux_ok else 'FAIL'}")
            print(f"{name:<18}{'source position max (px)':<26}{'':>14}{offset_envelope:>12.6g}"
                  f"{worst_offset:>14.6g}{'':>12}  {'PASS' if offset_ok else 'FAIL'}")
            print(f"{name:<18}{'unmatched sources':<26}{'':>14}{unmatched_envelope:>12d}"
                  f"{unmatched_candidate:>14d}{'':>12}  {'PASS' if unmatched_ok else 'FAIL'}")
        else:
            # Sources in one image that never match the other are a real
            # difference, not an absent measurement.
            if any(len(m['_sources']) for m in reference_metrics) or len(candidate_metrics['_sources']):
                failures.append(f'{name}: sources detectable but none matched within '
                                f'{MATCH_RADIUS_PX:g} px between candidate and reference')
                print(f"{name:<18}{'matched sources':<26}{'':>14}{'':>12}{'':>14}{'':>12}  FAIL (unmatched)")
            else:
                label = (f'none detectable above {MIN_PEAK_SIGMA:g} sigma')
                print(f"{name:<18}{'matched sources':<26}{label:>42}")
        report[name] = entry

    print()
    if failures:
        print('GATE FAILED:')
        for failure in failures:
            print('  -', failure)
    else:
        print('GATE PASSED: every measured quantity is within the reference run-to-run envelope.')
    if args.json:
        args.json.write_text(json.dumps(jsonable(report), indent=2) + '\n')
        print('wrote', args.json)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
