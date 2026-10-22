#!/usr/bin/env python3
"""Validate saved MX_PROFILE stderr; this does not run or establish GPU work.

Spans use mach-absolute seconds, including Metal GPUStartTime/GPUEndTime.
IDs identify sessions/plans/calls; command_id joins encode/wait/GPU records.
Intervals may overlap and are never summed here. bytes means touched/copied or
allocated bytes for the named event, not measured memory bandwidth. For GPU
spans bytes is workspace size, not measured traffic. parent_id/buffer_id are
numeric IDs in the process namespace (the suffix of id); zero means absent.
direction is -1 forward, +1 inverse, 0 unspecified. No occupancy is reported.

Stages:
 prediction.{initialize,session,prepare,consume,fallback}
 fft.{initialize,allocate_zero,planner_mutex_wait,planner,encode_commit,wait,gpu}
 convolution.{total,plan_miss,batch_mutex_wait,shader_compile,allocate_inputs,
              copy_inputs,encode_commit,wait,gpu,copy_output}
 peak.{total,pipeline_setup,mutex_wait,allocate_scratch,copy_inputs,encode_commit,
       wait,gpu,final_reduce_return}

Copy inputs counts image plus kernel bytes for convolution, image plus mask
storage writes for peak. peak.copy_inputs additionally separates copied_bytes
from filled_bytes (all-ones mask fill for absent per-plane masks).
A failed command emits an unsuccessful wait, without inventing a GPU interval.
"""
import argparse
import json
import math
import sys
from pathlib import Path


def validate(text, prediction=True, disabled=False):
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith('MX_PROFILE '):
            continue
        try:
            record = json.loads(line[len('MX_PROFILE '):])
        except (ValueError, TypeError) as exc:
            raise ValueError(f'line {number}: invalid JSON: {exc}') from exc
        if not isinstance(record, dict):
            raise ValueError(f'line {number}: expected JSON object')
        records.append(record)
        if record.get('type') != 'span':
            raise ValueError(f'line {number}: unsupported record type')
        for field in ('stage', 'id'):
            if not isinstance(record.get(field), str) or not record[field]:
                raise ValueError(f'line {number}: missing {field}')
        for field in ('start', 'end'):
            value = record.get(field)
            try:
                valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                         and math.isfinite(value) and value > 0)
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f'line {number}: invalid {field}')
        if record['end'] < record['start']:
            raise ValueError(f'line {number}: reversed interval')
        for field in ('bytes', 'copied_bytes', 'filled_bytes', 'w', 'h', 'batch', 'slot', 'plane'):
            if field in record and (type(record[field]) is not int or record[field] < 0):
                raise ValueError(f'line {number}: invalid {field}')
        if 'ok' in record and type(record['ok']) is not bool:
            raise ValueError(f'line {number}: invalid ok')
        if record['stage'].endswith('.gpu'):
            if record.get('ok') is not True or record['end'] <= record['start']:
                raise ValueError(f'line {number}: missing successful GPU completion/timestamps')
    if disabled:
        if records:
            raise ValueError('disabled profile produced MX_PROFILE records')
        return records
    if not records:
        raise ValueError('no MX_PROFILE records')
    if not any(r['stage'].endswith('.gpu') and r.get('ok') is True for r in records):
        raise ValueError('no completed GPU command interval (CPU fallback is not GPU evidence)')
    if prediction:
        for stage in ('prediction.prepare', 'prediction.consume'):
            if not any(r['stage'] == stage for r in records):
                raise ValueError(f'missing {stage}')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--no-prediction', action='store_true', help='accept convolution/peak-only logs')
    parser.add_argument('--disabled', action='store_true', help='negative control: require zero records')
    args = parser.parse_args()
    try:
        records = validate(args.log.read_text(), not args.no_prediction, args.disabled)
    except (OSError, ValueError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    print(f'PASS: {len(records)} spans ({"disabled negative control" if args.disabled else "trace structure only; provenance must be checked separately"})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
