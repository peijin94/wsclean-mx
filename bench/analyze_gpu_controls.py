#!/usr/bin/env python3
"""Report causal GPU/CPU controls without turning sensitivity failures into passes."""
import argparse
import json
from pathlib import Path
import re
from types import SimpleNamespace
import numpy as np
from astropy.io import fits
from compare_fits import compare, passes

ROOT = Path(__file__).resolve().parents[1]


def validate_runs(plan, runs):
    """Reject incomplete or changed controls before inspecting any products."""
    entries=plan.get('plan') if isinstance(plan,dict) else None
    if not isinstance(entries,list) or not entries:
        raise ValueError('missing or empty causal plan')
    planned_labels=set()
    for entry in entries:
        if not isinstance(entry,list) or len(entry)!=4:
            raise ValueError('incomplete causal plan entry')
        label,gpu,fixture,env=entry
        if (not isinstance(label,str) or not label or type(gpu) is not bool
                or not isinstance(fixture,str) or not fixture or not isinstance(env,dict)):
            raise ValueError('invalid causal plan roles')
        if label in planned_labels:
            raise ValueError('duplicate planned label')
        planned_labels.add(label)
    if 'cpu1' not in planned_labels:
        raise ValueError('missing planned CPU reference')
    if not isinstance(runs,list) or len(runs)!=len(entries):
        raise ValueError('incomplete causal runs')
    actual_labels=set()
    for entry,run in zip(entries,runs):
        if not isinstance(run,dict) or not {'label','gpu','fixture','env','exit'}<=run.keys():
            raise ValueError('incomplete causal run entry')
        label=run['label']
        if not isinstance(label,str) or label in actual_labels:
            raise ValueError('invalid or duplicate actual label')
        actual_labels.add(label)
        if (type(run['gpu']) is not bool or not isinstance(run['env'],dict)
                or [run[key] for key in ('label','gpu','fixture','env')]!=entry):
            raise ValueError('causal run order or roles differ from plan')
        if type(run['exit']) is not int or run['exit']!=0:
            raise ValueError('unsuccessful causal run')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    plan=json.loads((args.artifact/'control-plan.json').read_text())
    runs=json.loads((args.artifact/'control-runs.json').read_text())
    validate_runs(plan,runs)
    directories={r['label']:ROOT/'bench/out'/r['tag']/r['command'][2] for r in runs}
    reference=directories['cpu1']
    inventory={p.name:p for p in reference.glob('*.fits')}
    if not {'img-model.fits','img-image.fits','img-residual.fits','img-psf.fits','img-dirty.fits'}<=inventory.keys():
        raise ValueError('missing reference products')
    thresholds=SimpleNamespace(tier='T2',max_rel_rms=1e-4,max_rel_peak=1e-3,max_ulp=4)
    report={}
    for run in runs:
        label=run['label'];directory=directories[label]
        candidate={p.name:p for p in directory.glob('*.fits')}
        if candidate.keys()!=inventory.keys():raise ValueError('product mismatch')
        rows=[]
        for name,path in inventory.items():
            row=compare(path,candidate[name]);row['pass']=bool(passes(row,thresholds));rows.append(row)
        log=(directory/'time.txt').read_text()
        proof=[tuple(map(int,p)) for p in re.findall(r'prediction proof: shared_planes=(\d+) submitted=(\d+) completed=(\d+) cpu_fallback=(\d+) grid_memcpy_bytes=(\d+)',log)]
        expects_gpu=run['gpu'] and not run['env'].get('MX_METAL_NO_PREDICT')
        if expects_gpu:
            if not proof or any(shared!=2 or sent<=0 or sent!=done or fallback or copied for shared,sent,done,fallback,copied in proof):
                raise ValueError('GPU execution proof failed')
        elif proof:raise ValueError('GPU work in CPU/null control')
        report[label]={'products':rows,'all_T2':all(r['pass'] for r in rows),'gpu_proof':proof,
                       'theoretical_beam_rad':fits.getheader(directory/'img-psf.fits').get('WSCTBEAM')}
        print(label,'T2',report[label]['all_T2'],'model bitwise',next(r['bitwise'] for r in rows if r['name']=='img-model.fits'))
    # A perturbation is a measured sensitivity experiment, not an accepted GPU comparison.
    accepted=[r for r in runs if r['fixture']=='common']
    all_common=all(report[r['label']]['all_T2'] and next(p['bitwise'] for p in report[r['label']]['products'] if p['name']=='img-model.fits') for r in accepted)
    summary={'plan':plan,'results':report,'common_input_pass':all_common,
             'common_input_runs':len(accepted),'scope':'correctness controls, not a timing benchmark'}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'causal.json').write_text(json.dumps(summary,indent=2,default=lambda x:x.item()))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4),constrained_layout=True)
    labels=[r['label'] for r in runs if r['label']!='cpu1'];x=np.arange(len(labels));width=.26
    for dx,product,title in [(-width,'img-dirty.fits','Input dirty image'),(0,'img-model.fits','CLEAN model'),(width,'img-image.fits','Restored image')]:
        values=[next(p['rel_rms'] for p in report[label]['products'] if p['name']==product) for label in labels]
        ax.bar(x+dx,np.maximum(values,1e-12),width,label=title)
    ax.axhline(1e-4,color='black',ls='--',label='Unchanged T2 relative-RMS limit')
    ax.set(yscale='log',ylim=(1e-12,1),xticks=x,xticklabels=labels,ylabel='Relative RMS vs common CPU reference',
           title='Same inputs and automatic scales: GPU controls vs CPU one-ULP sensitivity')
    ax.legend(fontsize=8,ncol=2)
    ax.text(.01,.02,'Zero/bitwise differences shown at plotting floor 1e-12',transform=ax.transAxes,fontsize=8)
    fig.savefig(args.output/'causal.png',dpi=180);plt.close(fig)
    return 0 if all_common else 1


if __name__=='__main__':
    raise SystemExit(main())
