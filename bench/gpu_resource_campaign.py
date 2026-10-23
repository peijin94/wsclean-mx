#!/usr/bin/env python3
"""Predeclared resource-residency experiments using the protected benchmark runner."""
import argparse
import json
import re
from pathlib import Path
from bench import gpu_profile_campaign as runner

BASELINE='gpu-profile-delivered'
BUDGET={'MX_METAL_MEMORY_MB':'1024'}
RESIDENT={**BUDGET,'MX_METAL_FUSE':'0'}
FUSED={**BUDGET,'MX_METAL_FUSE':'1'}


def make_plan(phase,candidate,label):
    for value in (candidate,label):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',value):raise ValueError('invalid experiment identifier')
    cases={
        'baseline-default':('prediction',BASELINE,{}),
        'baseline-convolution':('convolution',BASELINE,{}),
        'candidate-default':('prediction',candidate,BUDGET),
        'resident':('convolution',candidate,RESIDENT),
        'fused':('convolution',candidate,FUSED),
        'baseline-cpu':('cpu',BASELINE,{}),
        'baseline-cpu-aa':('cpu',BASELINE,{}),
        'candidate-cpu':('cpu',candidate,{}),
        'no-plans':('convolution',candidate,{**RESIDENT,'MX_METAL_NO_PLAN_CACHE':'1'}),
        'no-kernels':('convolution',candidate,{**RESIDENT,'MX_METAL_NO_KERNEL_CACHE':'1'}),
        'serial':('prediction',candidate,{**BUDGET,'MX_METAL_PREDICT_SERIAL':'1'}),
        'overlapped':('prediction',candidate,{**BUDGET,'MX_METAL_PREDICT_SERIAL':'0'}),
        'disabled':('convolution',candidate,{**FUSED,'MX_METAL_NO_FUSE':'1','MX_METAL_NO_CONVOLVE':'1','MX_METAL_NO_PREDICT':'1'}),
        'budget-refusal':('convolution',candidate,{**FUSED,'MX_METAL_MEMORY_MB':'1'}),
    }
    phases={
        'timing':(['baseline-default','baseline-convolution','candidate-default','resident','fused'],4,True),
        'ablation':(['resident','no-plans','no-kernels','fused'],3,True),
        'overlap':(['overlapped','serial'],4,True),
        'deterministic':(['baseline-cpu','baseline-cpu-aa','candidate-cpu','baseline-convolution','resident','fused','disabled','budget-refusal'],1,False),
        'common':(['baseline-cpu','baseline-convolution','resident','fused'],3,False),
        'trace':(['baseline-convolution','resident','fused','overlapped','serial'],1,False),
        'stress':(['baseline-cpu','fused','budget-refusal'],1,False),
    }
    if phase not in phases:raise ValueError('unknown phase')
    names,repeats,warm=phases[phase]
    plan=[]
    def add(name,repeat,warmup=False):
        mode,variant,env=cases[name]
        size=1024 if phase=='deterministic' else 4096 if phase=='stress' else 3072
        plan.append(dict(case=name,mode=mode,variant=variant,env_overrides=dict(env),repeat=repeat,
                         size=size,threads=1 if phase=='deterministic' else 8,
                         profile=phase=='trace',monitor=phase=='trace',sample=False,
                         warmup=warmup,common=phase in ('common','ablation'),
                         extra=['-scale','8.1amin'] if phase=='deterministic' else [],
                         expected_gpu=mode!='cpu' and name not in ('disabled','budget-refusal')))
    if warm:
        for name in names:add(name,0,True)
    for rep in range(1,repeats+1):
        for name in names if rep%2 else reversed(names):add(name,rep)
    for i,job in enumerate(plan):job['tag']=f'gpuopt-{label}-{phase}-{i:02d}-{job["case"]}'
    return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['timing','ablation','overlap','deterministic','common','trace','stress'])
    p.add_argument('--candidate',required=True)
    p.add_argument('--label',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--plan-only',action='store_true')
    args=p.parse_args()
    plan=make_plan(args.phase,args.candidate,args.label)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'plan.json').write_text(json.dumps(plan,indent=2))
    if args.plan_only:return 0
    results=[]
    for job in plan:
        results.append(runner.run_job(job,args.output))
        (args.output/'runs.json').write_text(json.dumps(results,indent=2))
    if len(results)!=len(plan):raise RuntimeError('incomplete experiment')
    return 0

if __name__=='__main__':raise SystemExit(main())
