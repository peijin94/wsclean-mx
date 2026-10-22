#!/usr/bin/env python3
"""Figures from preserved GPU profiling results; no inferred occupancy counters."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_gpu_profile import ROOT,ART,merge_intervals


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    out=args.directory;data=json.loads((out/'results.json').read_text());runs=data['runs']
    def raw(run):
        path=ROOT/'bench/out'/run['tag']/run['variant']/'time.txt'
        return [json.loads(l[11:]) for l in path.read_text().splitlines() if l.startswith('MX_PROFILE ')]
    modes=['cpu','prediction','peak','convolution','all']
    titles=['CPU','GPU prediction','Prediction + peak','Prediction + convolution','All hooks']
    chosen=[r for m in modes for r in runs if r['phase']=='timing' and not r['warmup'] and r['mode']==m]
    fig,ax=plt.subplots(figsize=(12,5),constrained_layout=True);x=np.arange(len(chosen));bottom=np.zeros(len(chosen))
    for field,label,color in [('inversion_s','CPU inversion','#4978a8'),('deconvolution_s','Deconvolution','#e9a34d'),('prediction_s','Prediction','#4a9f87'),('other_s','Other/startup/I-O','#c9c9c9')]:
        y=np.array([r['times'][field] for r in chosen]);ax.bar(x,y,bottom=bottom,label=label,color=color);bottom+=y
    ax.set_xticks([1,4,7,10,13],titles);ax.set(ylabel='Whole-program seconds',title='Unprofiled 3072² runs: every stack is one actual run, not summed medians')
    for i,m in enumerate(modes):ax.text(i*3+1,max(bottom[i*3:i*3+3])+.3,f"median {data['timing'][m]['wall_s']['median']:.2f}s",ha='center',fontsize=9)
    ax.set_ylim(0,max(bottom)*1.2);ax.legend(ncol=4,fontsize=9,loc='upper left');fig.savefig(out/'stage-times.png',dpi=180);plt.close(fig)

    run=[r for r in runs if r['phase']=='trace' and r['mode']=='prediction'][-1]
    records=raw(run);session=next(s for s in records if s['stage']=='prediction.session');t0=session['start']
    monitor=[json.loads(l) for l in (ART/run['phase']/(run['tag']+'.monitor.jsonl')).read_text().splitlines()];origin=monitor[0]['mach_s']
    fig,axes=plt.subplots(3,1,figsize=(12,10),constrained_layout=True,gridspec_kw={'height_ratios':[1,1.5,1.5]})
    ax=axes[0];ax.plot([r['mach_s']-origin for r in monitor],[r['Device Utilization %'] for r in monitor],label='Device-wide GPU gauge (all apps)',color='#3b9c7d');ax.set(ylabel='GPU gauge (%)',ylim=(0,105),xlabel='Seconds since monitor start',title='GPU use is bursty, not sustained across the whole imaging run')
    cpu=[];ct=[]
    for a,b in zip(monitor,monitor[1:]):
        if all(k in a and k in b for k in ['cpu_user_s','cpu_system_s']):
            cpu.append((b['cpu_user_s']+b['cpu_system_s']-a['cpu_user_s']-a['cpu_system_s'])/(b['mach_s']-a['mach_s']));ct.append(a['mach_s']-origin)
    twin=ax.twinx();twin.plot(ct,cpu,label='WSClean CPU core-equivalents',color='#4978a8',alpha=.7);twin.set(ylabel='CPU core-equivalents',ylim=(0,8.5))
    lines=ax.get_lines()+twin.get_lines();ax.legend(lines,[l.get_label() for l in lines],fontsize=8,loc='upper left')
    ax.axvspan(session['start']-origin,session['end']-origin,color='grey',alpha=.15)
    ax=axes[1];lanes=[('prediction.initialize','CPU plan/setup'),('prediction.prepare','CPU prepare'),('prediction.consume','CPU degrid'),('fft.wait','CPU wait'),('gpu0','GPU slot 0'),('gpu1','GPU slot 1')]
    colors=['#999999','#e9a34d','#4978a8','#cc6666','#3b9c7d','#71ba9f']
    for i,((stage,label),color) in enumerate(zip(lanes,colors)):
        selected=[s for s in records if (s['stage']=='fft.gpu' and s.get('slot')==int(stage[-1]))] if stage.startswith('gpu') else [s for s in records if s['stage']==stage]
        ax.broken_barh([(s['start']-t0,s['end']-s['start']) for s in selected],(i-.35,.7),facecolors=color)
    ax.set(yticks=range(len(lanes)),yticklabels=[x[1] for x in lanes],xlabel='Seconds into prediction session',title='Same-clock timeline: overlapping GPU commands must not be added as wall time');ax.invert_yaxis();ax.set_xlim(0,session['end']-t0)
    ax=axes[2]
    for stage,label,color in [('prediction.prepare','CPU prepare','#e9a34d'),('prediction.consume','CPU degrid','#4978a8'),('fft.gpu','GPU command','#3b9c7d'),('fft.wait','CPU wait','#cc6666')]:
        selected=sorted([s for s in records if s['stage']==stage and 'plane' in s],key=lambda s:s['plane'])
        ax.plot([s['plane'] for s in selected],[(s['end']-s['start'])*1000 for s in selected],label=label,color=color)
    ax.set(xlabel='W-plane index (ordered consumption)',ylabel='Per-plane wall / GPU interval (ms)',title='CPU work varies strongly across planes; dense FFT cost does not disappear on sparse planes');ax.legend(ncol=4,fontsize=8)
    fig.savefig(out/'prediction-timeline.png',dpi=180);plt.close(fig)

    conv=[r for r in runs if r['phase']=='trace' and r['mode']=='convolution'][-1]
    peak=[r for r in runs if r['phase']=='trace' and r['mode']=='peak'][-1]
    fig,axes=plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    labels=['Plan misses','Input copies','GPU completion wait','Output copies','Other'];st=conv['stages'];total=st['convolution.total']['wall_union_s']
    vals=[st['convolution.'+s]['wall_union_s'] for s in ['plan_miss','copy_inputs','wait','copy_output']];vals.append(total-sum(vals))
    axes[0].barh(labels,vals,color=['#999999','#e9a34d','#cc6666','#e9a34d','#c9c9c9']);axes[0].invert_yaxis();axes[0].set(xlabel='Host wall seconds (serial calls)',title='Convolution: copies, plan churn and waiting dominate')
    axes[0].text(.02,.02,f"GPU execution {st['convolution.gpu']['wall_union_s']:.3f}s is INSIDE waiting, not extra.\n{st['convolution.plan_miss']['count']} plan misses / {st['convolution.total']['count']} calls.",transform=axes[0].transAxes,fontsize=9)
    keys=['peak.total','peak.mutex_wait','peak.copy_inputs','peak.wait','peak.gpu'];labels=['Entire hook','Mutex wait','Input copies/fill','Completion wait','GPU command']
    sums=[peak['stages'][k]['call_wall_sum_s'] for k in keys];unions=[peak['stages'][k]['wall_union_s'] for k in keys];yy=np.arange(len(keys))
    axes[1].barh(yy-.18,sums,.35,label='Sum of call latencies');axes[1].barh(yy+.18,unions,.35,label='Interval union');axes[1].set(yticks=yy,yticklabels=labels,xlabel='Seconds',title='Peak calls overlap and serialize on a shared mutex');axes[1].invert_yaxis();axes[1].legend(fontsize=8)
    fig.savefig(out/'deconvolution-budget.png',dpi=180);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    for n in [1,2,4,8]:
        selected=[r for r in runs if (r['phase']=='threads' or (r['phase']=='trace' and r['mode']=='prediction')) and r['threads']==n]
        axes[0].scatter([n]*len(selected),[r['prediction_budget']['session_s'] for r in selected],color='#4978a8')
        axes[1].scatter([n]*len(selected),[100*r['prediction_budget']['residency_fraction'] for r in selected],color='#3b9c7d')
    axes[0].set(xlabel='CPU threads',ylabel='Prediction session seconds',title='Prediction remains strongly CPU-thread dependent',xticks=[1,2,4,8]);axes[1].set(xlabel='CPU threads',ylabel='GPU command residency (%)',title='More CPU supply increases GPU duty cycle',xticks=[1,2,4,8],ylim=(0,100))
    fig.savefig(out/'thread-scaling.png',dpi=180);plt.close(fig)


if __name__=='__main__':main()
