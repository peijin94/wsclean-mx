#!/usr/bin/env python3
"""Sequential profiling campaign; preserves every command and separates timing.

Existing bench/run.sh enforces protected inputs and fresh output directories.
The monitor reports device-wide gauges, never shader occupancy.
"""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import signal
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from wsclean_binary import resolve_variant

ART=ROOT/'bench/out/gpu-profile-20261022-1147'
MS=ROOT/'bench/out/gpu-audit-20261022-0715/input-15.ms'
DEFAULT_NITER=150000
RUN_TIMEOUT_S=1800
MODES={'cpu':{},'prediction':{},'convolution':{'MX_METAL_CONVOLVE':'1'},
       'peak':{'MX_METAL_PEAK':'1'},'all':{'MX_METAL_CONVOLVE':'1','MX_METAL_PEAK':'1'}}


def validate_niter(niter):
    if type(niter) is not int or niter<0:
        raise ValueError('niter must be a non-negative integer')
    return niter


def make_plan(phase,*,niter=DEFAULT_NITER):
    niter=validate_niter(niter)
    jobs=[]
    def add(mode,repeat=1,*,size=3072,threads=8,profile=False,monitor=False,sample=False,warmup=False,common=False,variant=None):
        jobs.append(dict(mode=mode,repeat=repeat,size=size,threads=threads,profile=profile,niter=niter,
                         monitor=monitor,sample=sample,warmup=warmup,common=common,
                         variant=variant or ('gpu-profile-v1' if phase!='timing' else 'gpu-followup-delivered')))
    if phase=='pilot':add('prediction',profile=True,monitor=True)
    elif phase=='timing':
        for mode in MODES:add(mode,warmup=True)
        for rep in range(1,4):
            for mode in (list(MODES) if rep%2 else list(reversed(MODES))):add(mode,rep)
    elif phase=='trace':
        for rep in range(1,3):
            for mode in (['prediction','convolution','peak','all'] if rep%2 else ['all','peak','convolution','prediction']):add(mode,rep,profile=True,monitor=True)
    elif phase=='threads':
        for rep in range(1,3):
            for n in ([1,2,4] if rep%2 else [4,2,1]):add('prediction',rep,threads=n,profile=True,monitor=True)
    elif phase=='4k':
        for rep in range(1,3):
            for mode in (['cpu','prediction'] if rep%2 else ['prediction','cpu']):add(mode,rep,size=4096,variant='gpu-followup-delivered')
        for rep in range(1,3):add('prediction',rep,size=4096,profile=True,monitor=True)
        add('all',size=4096,profile=True,monitor=True)
    elif phase=='fullgrid':
        add('prediction',size=4096,profile=True,monitor=True)
        jobs[-1]['extra']=['-no-min-grid-resolution']
    elif phase=='sample':
        for mode in ['cpu','prediction','all']:add(mode,profile=mode!='cpu',monitor=True,sample=True)
    elif phase=='overhead':
        for rep in range(1,4):
            for prof in ([False,True] if rep%2 else [True,False]):add('prediction',rep,profile=prof,common=True)
    else:raise ValueError('unknown phase')
    for i,j in enumerate(jobs):j['tag']=f'gpuprof-{phase}-{i:02d}-{j["mode"]}-{j["size"]}-j{j["threads"]}'
    assert len({j['tag'] for j in jobs})==len(jobs)
    return jobs


def health():
    commands={'swap':['sysctl','vm.swapusage'],'vm':['vm_stat'],'thermal':['pmset','-g','therm']}
    return {'unix_s':time.time(),'load':os.getloadavg(),**{k:subprocess.check_output(v,text=True).strip() for k,v in commands.items()}}


def matching_pids(text,needle,executable):
    found=[]
    for line in text.splitlines():
        parts=line.split(maxsplit=2)
        # macOS truncates comm to 16 columns even with -ww. Match full argv0.
        if len(parts)==3 and parts[2].startswith(str(executable)+' ') and needle in parts[2]:
            found.append(int(parts[0]))
    return found


def find_target(process,needle,executable):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and process.poll() is None:
        text=subprocess.check_output(['ps','-axww','-o','pid=,comm=,args='],text=True)
        found=matching_pids(text,needle,executable)
        if len(found)==1:return found[0]
        if len(found)>1:raise RuntimeError('ambiguous profiling target')
    raise RuntimeError('target executable not found; no substitute process sampled')


def run_job(job,folder):
    variant,tag=job['variant'],job['tag']
    niter=validate_niter(job.get('niter',DEFAULT_NITER))
    extra=job.get('extra',[])
    if not isinstance(extra,(list,tuple)) or not all(isinstance(x,str) for x in extra):
        raise ValueError('extra arguments must be a sequence of strings')
    if any(x.startswith('-') and x.lstrip('-').split('=',1)[0]=='niter' for x in extra):
        raise ValueError('set the niter job field, not an extra niter argument')
    size=job['size'];scale='2.7amin' if size==3072 else '2amin'
    cmd=['bash','bench/run.sh',variant,tag]
    if job['mode']!='cpu':cmd+=['-mgpu']
    cmd+=['-j',str(job['threads']),'-size',str(size),str(size),'-scale',scale,'-weight','briggs','0','-pol','I','-multiscale','-multiscale-scale-bias','0.8','-niter',str(niter),'-mgain','0.95','-auto-threshold','0.5','-auto-mask','3','-local-rms','-horizon-mask','10deg','-mem','40','-reorder']
    if job['common']:
        prefix=ROOT/'bench/out/gpu-followup-20261022-0945/beam-controls/common/img'
        cmd+=['-reuse-psf',str(prefix),'-reuse-dirty',str(prefix)]
    auxiliary_logs=job['sample'] or (job['profile'] and not job['common'])
    if auxiliary_logs:cmd+=['-log-time']
    cmd+=extra
    cmd+=[str(MS)]
    selected={'MX_METAL_DEBUG_TIMING':'1',**MODES[job['mode']]}
    overrides=job.get('env_overrides',{})
    if not isinstance(overrides,dict):raise ValueError('feature overrides must be a dictionary')
    reserved={'MX_METAL_PROFILE','MX_METAL_DEBUG_TIMING'}
    for key,value in overrides.items():
        if (not isinstance(key,str) or not re.fullmatch(r'MX_METAL_[A-Z0-9_]+',key)
                or key in reserved or not isinstance(value,str) or '\0' in value):
            raise ValueError('invalid or reserved feature override')
    selected.update(overrides)
    if job['profile']:selected['MX_METAL_PROFILE']='1'
    if auxiliary_logs:selected['MX_WGRIDDER_VERBOSE']='1'
    env={k:v for k,v in os.environ.items() if not k.startswith(('MX_METAL_','MX_WGRIDDER_'))};env.update(selected)
    result={**job,'niter':niter,'command':cmd,'env':selected,'start_unix_s':time.time()}
    process=monitor=sampler=None;monitor_file=None
    original_error=None;finalization_errors=[]
    def error_info(error):
        return {'type':type(error).__name__,'text':str(error)}
    def finalize(action):
        try:action()
        except BaseException as error:
            finalization_errors.append(error)
            result.setdefault('cleanup_errors',[]).append(error_info(error))
    def stop_process():
        try:
            if process.poll() is None or original_error is not None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
        finally:result['exit']=process.returncode
    def stop_auxiliary(child,key):
        try:result[key]=child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:result[key]=child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill();result[key]=child.wait(timeout=10)
        finally:result[key]=child.returncode
    try:
        result['before']=health()
        with (folder/(tag+'.runner.log')).open('x') as f:
            process=subprocess.Popen(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            if job['monitor'] or job['sample']:
                pid=find_target(process,f'/{tag}/{variant}/img',resolve_variant(ROOT,variant));result['target_pid']=pid
                if job['monitor']:
                    monitor_file=(folder/(tag+'.monitor.jsonl')).open('x')
                    monitor=subprocess.Popen([str(ART/'gpu-monitor'),'100',str(RUN_TIMEOUT_S*1000),str(pid)],stdin=subprocess.PIPE,stdout=monitor_file,stderr=f)
                if job['sample']:
                    sampler=subprocess.Popen(['/usr/bin/sample',str(pid),str(RUN_TIMEOUT_S),'1','-mayDie','-file',str(folder/(tag+'.sample.txt'))],stdout=f,stderr=subprocess.STDOUT)
            result['exit']=process.wait(timeout=RUN_TIMEOUT_S)
    except BaseException as error:
        original_error=error
        result['exception']=error_info(error)
        raise
    finally:
        if process is not None:finalize(stop_process)
        else:result['exit']=None
        if monitor is not None:
            if monitor.stdin is not None:finalize(monitor.stdin.close)
            finalize(lambda:stop_auxiliary(monitor,'monitor_exit'))
        if monitor_file is not None:finalize(monitor_file.close)
        if sampler is not None:finalize(lambda:stop_auxiliary(sampler,'sample_exit'))
        result['end_unix_s']=time.time()
        try:result['after']=health()
        except BaseException as error:
            result['after_error']=error_info(error)
            finalization_errors.append(error)
        (folder/(tag+'.receipt.json')).write_text(json.dumps(result,indent=2))
        if original_error is None and finalization_errors:raise finalization_errors[0]
    if result.get('exit')!=0:raise RuntimeError(f'{tag} failed; evidence retained')
    if job['monitor'] and result['monitor_exit']!=0:raise RuntimeError('monitor failed')
    if job['sample'] and result['sample_exit']!=0:raise RuntimeError('sample failed')
    print(tag,'exit',result['exit'],flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['pilot','timing','trace','threads','4k','sample','overhead','fullgrid'])
    parser.add_argument('--label',help='fresh output label; never overwrites an earlier phase')
    parser.add_argument('--niter',type=int,default=DEFAULT_NITER,
                        help='CLEAN iteration budget (default: %(default)s)')
    args=parser.parse_args();plan=make_plan(args.phase,niter=args.niter)
    label=args.label or args.phase
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',label):raise ValueError('invalid label')
    for job in plan:job['tag']=job['tag'].replace('gpuprof-'+args.phase+'-','gpuprof-'+label+'-',1)
    folder=ART/label;folder.mkdir(exist_ok=False)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2))
    result=[]
    for job in plan:
        result.append(run_job(job,folder));(folder/'runs.json').write_text(json.dumps(result,indent=2))
    assert len(result)==len(plan)
    return 0


if __name__=='__main__':raise SystemExit(main())
