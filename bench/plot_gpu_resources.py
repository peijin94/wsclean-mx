#!/usr/bin/env python3
"""Plot measured resource-optimization results; never fill missing data with zero."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

LABELS={'baseline-default':'Old prediction','baseline-convolution':'Old convolution',
        'candidate-default':'New prediction','resident':'Resident kernels','fused':'Resident + peak',
        'overlapped':'Two-slot overlap','serial':'Serial diagnostic'}
COLORS=['#64748b','#a1a1aa','#0284c7','#16a34a','#9333ea']


def copy_totals(run):
    """Return byte totals, requiring the plotted case's actual copy receipts."""
    import math

    case=run['case']
    if case not in ('baseline-convolution','resident','fused'):
        raise ValueError('unsupported copy-accounting case: '+case)
    stages=run['stages']

    def byte_value(receipt,key,label,optional=False):
        if key not in receipt:
            if optional:return 0
            raise ValueError(case+': missing '+label)
        value=receipt[key]
        if (type(value) not in (int,float) or value<0 or
                (isinstance(value,float) and not math.isfinite(value))):
            raise ValueError(case+': invalid nonnegative bytes for '+label)
        return value

    def stage_bytes(stage,optional=False):
        if stage not in stages and optional:return 0
        return byte_value(stages.get(stage,{}),'bytes',stage)

    image=stage_bytes('convolution.copy_inputs')
    # Legacy input spans already include kernels; candidates report them separately.
    kernel=byte_value(run['convolution'],'kernel_bytes','kernel_bytes',
                      optional=case=='baseline-convolution')
    rms=stage_bytes('fusion.copy_inputs',optional=case!='fused')
    out=(stage_bytes('fusion.copy_output',optional=case!='fused')+
         stage_bytes('convolution.copy_output',optional=case=='fused'))
    return image+kernel,rms,out


def sampled_bars(ax,summary,cases,metric,title,ylabel):
    for i,case in enumerate(cases):
        data=summary[case]['times'][metric];values=data['samples']
        ax.bar(i,data['median'],color=COLORS[i%len(COLORS)],alpha=.75,width=.65)
        ax.scatter(i+np.linspace(-.12,.12,len(values)),values,s=20,c='black',zorder=3)
        ax.annotate(f"{data['median']:.3f}",(i,max(values)),xytext=(0,6),textcoords='offset points',ha='center',fontsize=9)
    ax.set_xticks(range(len(cases)),[LABELS[c] for c in cases],rotation=20,ha='right')
    ax.set_title(title);ax.set_ylabel(ylabel);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.margins(y=.2)


def render(data,output):
    phases={p['phase']:p for p in data}
    timing=phases['timing'];trace=phases['trace'];overlap=phases['overlap']
    cases=['baseline-default','baseline-convolution','candidate-default','resident','fused']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    sampled_bars(axes[0,0],timing['summary'],cases,'wall_s','Whole imaging run','Seconds')
    sampled_bars(axes[0,1],timing['summary'],cases,'deconvolution_s','Deconvolution stage','Seconds')
    selected=['baseline-convolution','resident','fused']
    profile={r['case']:r for r in trace['runs']}
    categories=[[],[],[]]
    for case in selected:
        for values,n in zip(categories,copy_totals(profile[case])):values.append(n/2**30)
    bottom=np.zeros(len(selected))
    for values,label,color in zip(categories,['Image + kernel uploads','RMS / mask uploads','Full-image readbacks'],['#0284c7','#f59e0b','#64748b']):
        axes[1,0].bar(range(len(selected)),values,bottom=bottom,label=label,color=color);bottom+=values
    axes[1,0].set_xticks(range(len(selected)),[LABELS[c] for c in selected],rotation=15,ha='right')
    axes[1,0].set_ylabel('GiB copied');axes[1,0].set_title('Explicit backend host copies (traced)')
    axes[1,0].legend(fontsize=8)
    memory_cases=['candidate-default','resident','fused'];owned=[];rss=[]
    for case in memory_cases:
        records=[r for r in timing['runs'] if not r['warmup'] and r['case']==case]
        owned.append(max(r['budget']['peak'] for r in records)/2**30)
        rss.append(timing['summary'][case]['times']['rss_bytes']['median']/2**30)
    x=np.arange(len(memory_cases))
    axes[1,1].bar(x-.18,owned,.36,label='Peak owned buffer charge',color='#16a34a')
    axes[1,1].bar(x+.18,rss,.36,label='Median peak process RSS',color='#a1a1aa')
    axes[1,1].axhline(1,color='#dc2626',linestyle='--',label='Owned-buffer cap: 1 GiB')
    axes[1,1].set_xticks(x,[LABELS[c] for c in memory_cases],rotation=15,ha='right')
    axes[1,1].set_ylabel('GiB');axes[1,1].set_title('Buffer budget is not a process RSS cap');axes[1,1].legend(fontsize=8)
    fig.suptitle('3072 x 3072 deep imaging: bounded reuse and resident peak processing\n15 integrations; -j 8; niter 20000; warmups excluded',fontsize=14)
    fig.supxlabel('Dots: all four timing trials. Copy accounting excludes CPU CLEAN internals and driver traffic. Deconvolution remains opt-in.',fontsize=9)
    output.mkdir(parents=True,exist_ok=True)
    fig.savefig(output/'resources.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    sampled_bars(axes[0],overlap['summary'],['overlapped','serial'],'prediction_s','Prediction scheduling diagnostic','Seconds')
    sampled_bars(axes[1],overlap['summary'],['overlapped','serial'],'wall_s','Whole imaging run','Seconds')
    fig.suptitle('Same arithmetic and two-slot limit; only wait timing changes',fontsize=13)
    fig.savefig(output/'overlap.png',dpi=160);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('data',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();render(json.loads(args.data.read_text()),args.output)

if __name__=='__main__':main()
