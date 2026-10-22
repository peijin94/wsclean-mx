#!/usr/bin/env python3
"""Analyze measured command intervals; GPU residency is not shader occupancy."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import statistics

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'bench/out/gpu-profile-20261022-1147'
PHASES=['pilot3','timing','trace','threads','4k','overhead','sample','fullgrid']


def merge_intervals(values):
    result=[]
    for a,b in sorted(values):
        if not math.isfinite(a) or not math.isfinite(b) or b<a:raise ValueError('invalid interval')
        if b==a:continue
        if result and a<=result[-1][1]:result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:result.append((a,b))
    return result


def measure(values):return sum(b-a for a,b in merge_intervals(values))


def intersect(first,second):
    a,b=merge_intervals(first),merge_intervals(second);i=j=0;result=[]
    while i<len(a) and j<len(b):
        low=max(a[i][0],b[j][0]);high=min(a[i][1],b[j][1])
        if high>low:result.append((low,high))
        if a[i][1]<=b[j][1]:i+=1
        else:j+=1
    return result


def subtract(first,second):
    remaining=merge_intervals(first)
    for x,y in merge_intervals(second):
        next_values=[]
        for a,b in remaining:
            if b<=x or a>=y:next_values.append((a,b))
            else:
                if a<x:next_values.append((a,x))
                if b>y:next_values.append((y,b))
        remaining=next_values
    return remaining


def parse_times(timing,log):
    def val(label):
        found=re.findall(r'^'+label+r'\s+([\d.]+)\s*$',timing,re.M)
        if len(found)!=1:raise ValueError('missing/duplicate '+label)
        return float(found[0])
    m=re.findall(r'Inversion:\s*([\d:.]+),\s*prediction:\s*([\d:.]+),\s*deconvolution:\s*([\d:.]+)',log)
    if len(m)!=1:raise ValueError('missing/duplicate stage timings')
    def hms(s):
        h,m,s=map(float,s.split(':'));return 3600*h+60*m+s
    wall,user,system=val('real'),val('user'),val('sys')
    inv,pred,deconv=map(hms,m[0]);rss=re.search(r'(\d+)\s+maximum resident set size',timing)
    return dict(wall_s=wall,user_s=user,system_s=system,inversion_s=inv,prediction_s=pred,
                deconvolution_s=deconv,other_s=wall-inv-pred-deconv,cpu_core_equivalent=(user+system)/wall,
                rss_bytes=int(rss[1]) if rss else None)


def percentile(values,q):
    values=sorted(values)
    if not values:return None
    index=(len(values)-1)*q;low=math.floor(index);high=math.ceil(index)
    return values[low]+(values[high]-values[low])*(index-low)


def monitor_summary(rows,window=None):
    pieces=[]
    for a,b in zip(rows,rows[1:]):
        dt=b['mach_s']-a['mach_s']
        if dt<=0:raise ValueError('monitor clock reversed')
        weight=measure(intersect([(a['mach_s'],b['mach_s'])],window)) if window else dt
        if not weight:continue
        cpu=None
        if all(k in a and k in b for k in ['cpu_user_s','cpu_system_s']):
            cpu=(b['cpu_user_s']+b['cpu_system_s']-a['cpu_user_s']-a['cpu_system_s'])/dt
        pieces.append((weight,a.get('Device Utilization %'),cpu,a))
    def weighted(index):
        valid=[x for x in pieces if x[index] is not None]
        return sum(x[0]*x[index] for x in valid)/sum(x[0] for x in valid) if valid else None
    gauges=[x[1] for x in pieces if x[1] is not None]
    return {'samples':len(pieces),'source_samples':len(rows),'covered_s':sum(x[0] for x in pieces),
            'device_gauge_mean_percent':weighted(1),'cpu_core_equivalent':weighted(2),
            'device_gauge_max_percent':max(gauges) if gauges else None,
            'query_median_us':percentile([(x[3]['query_end_mach_s']-x[3]['mach_s'])*1e6 for x in pieces],.5)}


def analyze_run(run,phase):
    folder=ROOT/'bench/out'/run['tag']/run['variant']
    timing=(folder/'time.txt').read_text();log=(folder/'wsclean.log').read_text()
    spans=[json.loads(l[len('MX_PROFILE '):]) for l in timing.splitlines() if l.startswith('MX_PROFILE ')]
    stages=defaultdict(list)
    for s in spans:stages[s['stage']].append(s)
    result={k:run[k] for k in ['tag','variant','mode','size','threads','profile','monitor','sample','warmup','common']}
    result.update(phase=phase,times=parse_times(timing,log),stages={})
    proof=[list(map(int,x)) for x in re.findall(r'prediction proof: shared_planes=(\d+) submitted=(\d+) completed=(\d+) cpu_fallback=(\d+) grid_memcpy_bytes=(\d+)',timing)]
    if run['mode']!='cpu' and (not proof or any(sh!=2 or n<=0 or n!=done or f or copies for sh,n,done,f,copies in proof)):raise ValueError('GPU execution proof failed '+run['tag'])
    if run['mode']=='cpu' and proof:raise ValueError('GPU work in CPU run')
    if run['profile'] and not spans:raise ValueError('missing profile')
    if not run['profile'] and spans:raise ValueError('unexpected profile')
    result['prediction_proof']=proof
    for stage,values in stages.items():
        durations=[s['end']-s['start'] for s in values];intervals=[(s['start'],s['end']) for s in values]
        stats={'count':len(values),'call_wall_sum_s':sum(durations),'wall_union_s':measure(intervals),
               'median_ms':1000*percentile(durations,.5),'p95_ms':1000*percentile(durations,.95)}
        if 'copy_' in stage:stats['host_storage_bytes']=sum(s['bytes'] for s in values)
        result['stages'][stage]=stats
    intervals=lambda stage:[(s['start'],s['end']) for s in stages.get(stage,[])]
    gpu=[s for s in spans if s['stage'].endswith('.gpu')]
    gpu_ranges=[(s['start'],s['end']) for s in gpu]
    result['gpu']={'commands':len(gpu),'command_interval_sum_s':sum(s['end']-s['start'] for s in gpu),
                   'command_interval_union_s':measure(gpu_ranges),'whole_run_residency_fraction':measure(gpu_ranges)/result['times']['wall_s']}
    command_lookup=defaultdict(dict)
    for s in spans:
        if s['command_id'] and s['stage'].endswith(('.encode_commit','.wait','.gpu')):
            kind=s['stage'].rsplit('.',1)[1];key=(s['id'],s['command_id'])
            if kind in command_lookup[key]:raise ValueError('duplicate command event')
            command_lookup[key][kind]=s
    pending=[];queue=[];commands=[]
    for key,events in command_lookup.items():
        if 'gpu' not in events:continue
        g,e,w=events['gpu'],events['encode_commit'],events['wait']
        if not (e['start']-.001<=g['start']<g['end']<=w['end']+.001):raise ValueError('CPU/GPU clocks not bracketed')
        pending.append((min(e['end'],g['start']),g['end']))
        delay=max(0,g['start']-e['end']);queue.append(delay)
        commands.append({'id':g['id'],'command_id':g['command_id'],'plane':g.get('plane'),
                         'slot':g.get('slot'),'stage':g['stage'],'w':g['w'],'h':g['h'],'batch':g['batch'],
                         'gpu_ms':(g['end']-g['start'])*1000,'queue_ms':delay*1000,
                         'wait_ms':(w['end']-w['start'])*1000})
    result['commands']=commands
    result['gpu']['queue_delay_median_ms']=1000*percentile(queue,.5) if queue else None
    result['gpu']['queue_delay_p95_ms']=1000*percentile(queue,.95) if queue else None
    session=intervals('prediction.session')
    if session:
        busy=intersect(gpu_ranges,session);idle=subtract(session,busy)
        host={stage:measure(intersect(intervals(stage),session)) for stage in ['prediction.initialize','prediction.prepare','prediction.consume','fft.encode_commit','fft.wait']}
        accounted=[x for stage in host for x in intervals(stage)]
        result['prediction_budget']={'session_s':measure(session),'gpu_union_s':measure(busy),
            'residency_fraction':measure(busy)/measure(session),'host_exclusive_wall_s':host,
            'host_unaccounted_s':measure(subtract(session,accounted)),
            'gpu_idle_s':measure(idle),'gpu_idle_with_pending_s':measure(intersect(idle,pending)),
            'gpu_idle_without_pending_s':measure(subtract(idle,pending)),
            'prepare_overlap_gpu_s':measure(intersect(intervals('prediction.prepare'),busy)),
            'consume_overlap_gpu_s':measure(intersect(intervals('prediction.consume'),busy))}
    for stage in ['peak','convolution']:
        total=intervals(stage+'.total')
        if total:
            result[stage+'_budget']={'call_wall_union_s':measure(total),
                'gpu_union_s':measure(intersect(intervals(stage+'.gpu'),total)),
                'plan_shapes':[{'w':s['w'],'h':s['h'],'batch':s['batch'],'seconds':s['end']-s['start']} for s in stages.get('convolution.plan_miss' if stage=='convolution' else 'peak.pipeline_setup',[])]}
    result['hook_proof']=[l for l in timing.splitlines() if '[mx-metal]' in l and ('calls=' in l or 'batches=' in l or 'plans=' in l or 'fallback:' in l)]
    if run['monitor']:
        rows=[json.loads(l) for l in (ART/phase/(run['tag']+'.monitor.jsonl')).read_text().splitlines()]
        result['monitor']=monitor_summary(rows)
        if session:result['monitor_prediction']=monitor_summary(rows,session)
    return result,spans


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args();results=[];completion={}
    for phase in PHASES:
        folder=ART/phase
        if not (folder/'plan.json').exists():
            completion[phase]={'complete':False};continue
        plan=json.loads((folder/'plan.json').read_text())
        runs=json.loads((folder/'runs.json').read_text()) if (folder/'runs.json').exists() else []
        if len(runs)>len(plan):raise ValueError('too many runs')
        for expected,actual in zip(plan,runs):
            if any(actual.get(k)!=v for k,v in expected.items()) or actual['exit']!=0:raise ValueError('plan mismatch')
        completion[phase]={'expected':len(plan),'completed':len(runs),'complete':len(plan)==len(runs)}
        for run in runs:results.append(analyze_run(run,phase)[0])
    if not args.partial and not all(x['complete'] for x in completion.values()):raise ValueError('incomplete campaign')
    groups=defaultdict(list)
    for r in results:
        if r['phase']=='timing' and not r['warmup']:groups[r['mode']].append(r)
    timing={}
    for mode,runs in groups.items():
        timing[mode]={k:{'values':[r['times'][k] for r in runs],
                        'median':statistics.median(r['times'][k] for r in runs),
                        'min':min(r['times'][k] for r in runs),'max':max(r['times'][k] for r in runs)}
                      for k in ['wall_s','inversion_s','prediction_s','deconvolution_s','other_s','rss_bytes','cpu_core_equivalent']}
    args.output.mkdir(parents=True,exist_ok=True)
    summary={'completion':completion,'runs':results,'timing':timing,
             'definitions':{'gpu_residency':'union of completed command-buffer GPUStartTime/GPUEndTime intervals; not shader occupancy',
                            'device_gauge':'device-wide IORegistry sampling; background UI included; driver averaging window unspecified',
                            'call_wall_sum':'sum of host call latencies, may overlap across callers; not CPU core-seconds',
                            'host_storage_bytes':'explicit memcpy/fill bytes for copy stages only; not hardware DRAM traffic'}}
    (args.output/'results.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'completion':completion,'timing_medians':{m:{k:v['median'] for k,v in d.items()} for m,d in timing.items()}},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
