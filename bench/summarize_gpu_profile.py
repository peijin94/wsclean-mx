#!/usr/bin/env python3
"""Derive auditable report tables from actual traces and profiling ablations."""
import json,re,statistics
from pathlib import Path
from collections import defaultdict
from typing import Any
from analyze_gpu_profile import ROOT,ART

OUT=ROOT/'docs/bench/gpu-profile-20261022'
x=json.loads((OUT/'results.json').read_text());runs=x['runs']
summary: dict[str,Any]={'completed_runs':sum(v['completed'] for v in x['completion'].values()),'excluded_timing_warmups':sum(r['warmup'] for r in runs)}
summary['existing_pipeline_reductions_percent']={k:100*(1-x['timing']['prediction'][k]['median']/x['timing']['cpu'][k]['median']) for k in ['wall_s','prediction_s']}
summary['default_trace']=[]
for r in runs:
 if r['phase']=='trace' and r['mode']=='prediction':
  b=r['prediction_budget'];summary['default_trace'].append({'tag':r['tag'],**b,'whole_run_gpu_fraction':r['gpu']['whole_run_residency_fraction'],'device_gauge_prediction_percent':r['monitor_prediction']['device_gauge_mean_percent'],
   'cpu_prediction_cores':r['monitor_prediction']['cpu_core_equivalent'],'empty_fraction_of_gpu_idle':b['gpu_idle_without_pending_s']/b['gpu_idle_s']})
summary['thread_sweep']={}
for n in [1,2,4,8]:
 rows=[r for r in runs if r['threads']==n and (r['phase']=='threads' or (r['phase']=='trace' and r['mode']=='prediction'))]
 summary['thread_sweep'][n]={'session_s':[r['prediction_budget']['session_s'] for r in rows],'gpu_fraction':[r['prediction_budget']['residency_fraction'] for r in rows]}
summary['convolution']=[]
for r in runs:
 if r['phase']=='trace' and r['mode']=='convolution':
  commands=[c for c in r['commands'] if c['stage']=='convolution.gpu'];s=r['stages']
  summary['convolution'].append({'tag':r['tag'],'calls':len(commands),'plan_misses':s['convolution.plan_miss']['count'],
    'plan_shapes':r['convolution_budget']['plan_shapes'],
    'input_bytes':s['convolution.copy_inputs']['host_storage_bytes'],'output_bytes':s['convolution.copy_output']['host_storage_bytes'],
    'queue_delay_ms':[c['queue_ms'] for c in commands],
    'gpu_ms':[c['gpu_ms'] for c in commands],'wait_ms':[c['wait_ms'] for c in commands],
    'service_s':s['convolution.total']['wall_union_s'],'gpu_s':s['convolution.gpu']['wall_union_s']})
summary['overhead_pairs']=[]
o=[r for r in runs if r['phase']=='overhead']
for a,b in zip(o[::2],o[1::2]):
 on=a if a['profile'] else b;off=b if a['profile'] else a
 summary['overhead_pairs'].append({'on_s':on['times']['wall_s'],'off_s':off['times']['wall_s'],
  'difference_s':on['times']['wall_s']-off['times']['wall_s'],
  'fraction':on['times']['wall_s']/off['times']['wall_s']-1})
summary['health']={}
for phase in ['timing','trace','threads','4k','overhead','sample','fullgrid']:
 for run in json.loads((ART/phase/'runs.json').read_text()):
  def counts(text):return {k:int(re.search(re.escape(k)+r':\s*(\d+)',text)[1]) for k in ['Swapins','Swapouts','Pageins','Pageouts']}
  a,b=counts(run['before']['vm']),counts(run['after']['vm']);summary['health'][run['tag']]={'before_swap':run['before']['swap'],'after_swap':run['after']['swap'],'page_deltas':{k:b[k]-a[k] for k in a}}
summary['samples']={}
for f in sorted((ART/'sample').glob('*.sample.txt')):
 text=f.read_text();block=text.split('Sort by top of stack, same collapsed (when >= 5):',1)[1].split('Binary Images:',1)[0];top=[]
 for line in block.splitlines():
  parts=line.strip().rsplit(maxsplit=1)
  if len(parts)==2 and parts[1].isdigit():top.append({'symbol':parts[0],'samples':int(parts[1])})
 ids=defaultdict(int)
 for count,tid in re.findall(r'^\s+(\d+) Thread_(\d+):',text,re.M):ids[tid]+=int(count)
 summary['samples'][f.name]={'thread_id_sample_counts':dict(ids),'top_of_stack':top[:25],
  'caution':'All-thread sampled stacks include parked workers and kernel waits. Counts are not CPU-time percentages or inclusive-hotspot percentages.'}
rows=json.loads((ART/'micro2-results.json').read_text());assert len(rows)==63 and all(r['passed'] and r['gpu_s']>0 for r in rows)
micro=[]
for b in [1,4,8]:
 for mode in ['fresh-convolution','reused-convolution','reused-inverse']:
  v=[r for r in rows if r['batch']==b and r['mode']==mode and not r['warmup']];assert len(v)==6
  micro.append({'batch':b,'mode':mode,'samples':6,
   'init_median_ms':1000*statistics.median(r['init_s'] for r in v),
   'submit_wait_median_ms':1000*statistics.median(r['submit_wait_s'] for r in v),
   'init_plus_submit_wait_median_ms':1000*statistics.median(r['init_s']+r['submit_wait_s'] for r in v),
   'gpu_median_ms':1000*statistics.median(r['gpu_s'] for r in v),
   'max_relative_rms':max(r['relative_rms'] for r in v),'max_rel_peak':max(r['max_rel_peak'] for r in v)})
summary['micro_v2']={'calls':63,'measured':54,'excluded_warmups':9,'values':micro,
 'limits':'Synthetic dense spectrum, delta kernels, all real cells validated. CPU inverse preparation, output validation and fresh teardown excluded. GPU-time differences are ablations, not exact individual-encoder timings. Earlier v1 retained; v2 removes repeated getter overhead from excluded CPU preparation.'}
(OUT/'derived.json').write_text(json.dumps(summary,indent=2))
print(json.dumps({'reductions':summary['existing_pipeline_reductions_percent'],'overhead':summary['overhead_pairs'],'micro':micro},indent=2))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
fig,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
for i,mode in enumerate(['fresh-convolution','reused-convolution','reused-inverse']):
 values=[r for r in micro if r['mode']==mode];positions=np.arange(3)+(i-1)*.25
 axes[0].bar(positions,[r['init_plus_submit_wait_median_ms'] for r in values],.24,label=mode)
 axes[1].bar(positions,[r['gpu_median_ms'] for r in values],.24,label=mode)
for ax in axes:ax.set(xticks=range(3),xticklabels=['1 plane','4 planes','8 planes'],ylabel='Median ms, six measured calls');ax.legend(fontsize=8)
axes[0].set_title('Same production FFT code: reuse removes host overhead');axes[1].set_title('GPU intervals change far less than host service time')
fig.suptitle('3072² synthetic, fully validated ablation; not an end-to-end speedup')
fig.savefig(OUT/'reuse-ablation.png',dpi=180);plt.close(fig)
