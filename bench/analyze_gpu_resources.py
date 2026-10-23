#!/usr/bin/env python3
"""Read real timing, resource and GPU-work receipts; fail closed on incomplete runs."""
import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from bench.analyze_gpu_profile import parse_times,measure
ROOT=Path(__file__).resolve().parents[1]


def validate_inventory(plan,runs):
    if len(plan)!=len(runs) or len({r['tag'] for r in runs})!=len(runs):
        raise ValueError('incomplete or duplicate trials')
    for expected,actual in zip(plan,runs):
        for key,value in expected.items():
            if actual.get(key)!=value:raise ValueError('trial identity/configuration mismatch: '+key)


def parse_resources(text,expected_gpu,*,case=None,env_overrides=None):
    proof=re.findall(r'prediction proof: shared_planes=(\d+) submitted=(\d+) completed=(\d+) cpu_fallback=(\d+) grid_memcpy_bytes=(\d+)',text)
    proof=[list(map(int,row)) for row in proof]
    completed=sum(p[2] for p in proof)
    if expected_gpu and (not proof or any(s!=2 or n<=0 or n!=d or f or b for s,n,d,f,b in proof)):
        raise ValueError('missing or incomplete GPU prediction work')
    if not expected_gpu and any(p[1] or p[2] for p in proof):
        raise ValueError('unexpected GPU work in CPU/fallback control')
    def last_line(prefix):
        lines=[line for line in text.splitlines() if line.startswith(prefix)]
        return {k:int(v) for k,v in re.findall(r'([a-z_]+)=(\d+)(?=\s|$)',lines[-1])} if lines else {}
    budget=last_line('[mx-metal] budget ')
    env=env_overrides or {}
    configured_budget='MX_METAL_MEMORY_MB' in env
    if (budget or configured_budget) and not {'owned_buffer_used','peak','limit','reservations','evictions','refusals'}<=budget.keys():
        raise ValueError('missing or incomplete budget receipt')
    if configured_budget:
        requested=str(env['MX_METAL_MEMORY_MB'])
        if not re.fullmatch(r'[0-9]+',requested):raise ValueError('invalid configured memory budget')
        if budget['limit']!=int(requested)*1048576:
            raise ValueError('reported budget limit differs from configured budget')
    if budget and not 0<=budget['owned_buffer_used']<=budget['peak']<=budget['limit']:
        raise ValueError('owned buffer budget exceeded')
    convolution=last_line('[mx-metal] convolution batches=')
    if not expected_gpu and any(convolution.get(key,0) for key in ('batches','planes','fused_calls','fused_planes')):
        raise ValueError('unexpected GPU convolution in CPU/fallback control')
    if expected_gpu and case in ('resident','no-plans','no-kernels','baseline-convolution','fused'):
        if convolution.get('batches',0)<=0 or convolution.get('planes',0)<=0:
            raise ValueError('missing or incomplete GPU convolution work')
        if case=='fused' and convolution.get('fused_calls',0)<=0:
            raise ValueError('fusion not executed')
        cache_counter={'no-plans':'pool_hits','no-kernels':'kernel_hits'}.get(case)
        if cache_counter and convolution.get(cache_counter)!=0:
            raise ValueError('ablation requires zero '+cache_counter)
    waits=list(map(int,re.findall(r'serial_waits=(\d+)(?=\s|$)',text)))
    if expected_gpu and case in ('serial','overlapped'):
        if not waits or sum(waits)!=(completed if case=='serial' else 0):
            raise ValueError('serial_waits do not match prediction schedule')
    return {'prediction_proof':proof,'prediction_completed':completed,
            'serial_waits':sum(waits),
            'convolution':convolution,
            'fallback_reasons':last_line('[mx-metal] convolution fallback_reasons '),
            'budget':budget}


def summarize_spans(spans):
    stages=defaultdict(list)
    for span in spans:stages[span['stage']].append(span)
    trace={}
    for stage,items in stages.items():
        intervals=[(i['start'],i['end']) for i in items]
        measure(intervals)  # Validate finite, ordered intervals even for CPU spans.
        trace[stage]={'count':len(items),'bytes':sum(i.get('bytes',0) for i in items),
                      'host_s':sum(end-start for start,end in intervals)}
    gpu=[(s['start'],s['end']) for s in spans if s['stage'].endswith('.gpu')]
    return trace,measure(gpu) if gpu else None


def analyze_folder(folder):
    plan=json.loads((folder/'plan.json').read_text())
    runs=json.loads((folder/'runs.json').read_text())
    validate_inventory(plan,runs)
    result=[]
    for run in runs:
        if run.get('exit')!=0:raise ValueError('failed run '+run['tag'])
        target=ROOT/'bench/out'/run['tag']/run['variant']
        timing=(target/'time.txt').read_text();log=(target/'wsclean.log').read_text()
        resources=parse_resources(timing,run['expected_gpu'],case=run['case'],
                                  env_overrides=run.get('env_overrides',{}))
        spans=[json.loads(line[len('MX_PROFILE '):]) for line in timing.splitlines() if line.startswith('MX_PROFILE ')]
        if bool(spans)!=run['profile']:raise ValueError('profiling contract mismatch')
        trace,gpu_union=summarize_spans(spans)
        result.append({**run,'times':parse_times(timing,log),**resources,'stages':trace,
                       'gpu_union_s':gpu_union,
                       'output_dir':str(target)})
    groups=defaultdict(list)
    for run in result:
        if not run['warmup']:groups[run['case']].append(run)
    summary={case:{'n':len(values),'times':{metric:{'samples':[v['times'][metric] for v in values],
                      'median':statistics.median(v['times'][metric] for v in values),
                      'min':min(v['times'][metric] for v in values),'max':max(v['times'][metric] for v in values)}
                for metric in ('wall_s','inversion_s','prediction_s','deconvolution_s','rss_bytes')}}
             for case,values in groups.items()}
    return {'phase':folder.name,'runs':result,'summary':summary}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('folders',nargs='+',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();data=[analyze_folder(folder) for folder in args.folders]
    args.output.write_text(json.dumps(data,indent=2))
    for phase in data:
        print(phase['phase'])
        for case,summary in phase['summary'].items():
            print(case,summary['n'],'wall',summary['times']['wall_s']['median'],'deconv',summary['times']['deconvolution_s']['median'])
    return 0

if __name__=='__main__':raise SystemExit(main())
