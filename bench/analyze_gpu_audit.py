#!/usr/bin/env python3
"""Summarize the activation-audited run family; never infer missing measurements."""
import argparse
import itertools
import json
import re
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import numpy as np
from astropy.io import fits
from compare_fits import compare, passes

ROOT = Path(__file__).resolve().parents[1]


def one(pattern, text):
    matches = re.findall(pattern, text, re.M)
    if len(matches) != 1:
        raise ValueError(f'expected one {pattern!r}, got {len(matches)}')
    return matches[0]


def gate(a, b, tier='T2'):
    left = {p.name: p for p in a.glob('*.fits')}
    right = {p.name: p for p in b.glob('*.fits')}
    if not left or left.keys() != right.keys():
        raise ValueError(f'product inventory mismatch: {a} / {b}')
    args = SimpleNamespace(tier=tier, max_ulp=4, max_rel_rms=1e-4, max_rel_peak=1e-3)
    rows = []
    for name in sorted(left):
        row = compare(left[name], right[name])
        row['pass'] = bool(passes(row, args))
        rows.append(row)
    return {'reference': str(a.relative_to(ROOT)), 'candidate': str(b.relative_to(ROOT)),
            'tier': tier, 'pass': all(r['pass'] for r in rows), 'products': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=Path, default=ROOT/'bench/out/gpu-audit-20261022-0715')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/bench/gpu-audit-20261022')
    args = parser.parse_args()
    records = json.loads((args.artifact/'final-runs.json').read_text())
    plan = json.loads((args.artifact/'final-plan.json').read_text())
    if len(records) != len(plan['plan']) or len(records) != 13:
        raise ValueError('incomplete run family')
    rows = []
    paths = {}
    for record in records:
        if record['exit'] != 0:
            raise ValueError(f"failed invocation: {record['label']}")
        path = ROOT/'bench/out'/record['tag']/'gpu-audit-final'
        paths[record['label']] = path
        timing = (path/'time.txt').read_text()
        log = (path/'wsclean.log').read_text()
        row = {k: record[k] for k in ('label', 'gpu', 'threads', 'measured', 'load_before', 'swap_before')}
        row['wall'] = float(one(r'^real\s+([0-9]+\.[0-9]+)\s*$', timing))
        row['rss_mib'] = int(one(r'^\s*(\d+)\s+maximum resident set size\s*$', timing))/2**20
        for name in ('inversion', 'prediction', 'deconvolution'):
            h, m, s = one(rf'{name.capitalize() if name == "inversion" else name}: (\d+):(\d+):([0-9.]+)', log)
            row[name] = 3600*int(h)+60*int(m)+float(s)
        for key, label in [('instructions', 'instructions retired'), ('cycles', 'cycles elapsed')]:
            row[key] = int(one(rf'^\s*(\d+)\s+{label}\s*$', timing))
        proof = [tuple(map(int, x)) for x in re.findall(
            r'MX prediction proof: shared_planes=(\d+) submitted=(\d+) completed=(\d+) cpu_fallback=(\d+) grid_memcpy_bytes=(\d+)', timing)]
        if record['gpu']:
            if not proof or any(shared != 2 or submitted <= 0 or submitted != done or fallback or copied
                                for shared, submitted, done, fallback, copied in proof):
                raise ValueError(f"invalid GPU proof: {record['label']} {proof}")
            if 'convolution batches=0 planes=0 singles=0 refused=0' not in timing or 'peak calls=0 submissions=0' not in timing:
                raise ValueError('default unexpectedly used deconvolution offload')
        elif proof:
            raise ValueError('CPU control executed a GPU session')
        row['gpu_planes'] = sum(p[2] for p in proof)
        rows.append(row)
    stats = {}
    for mode in ('cpu', 'gpu'):
        selected = [r for r in rows if r['measured'] and r['gpu'] == (mode == 'gpu')]
        assert len(selected) == 4
        stats[mode] = {key: {'samples': [r[key] for r in selected],
                            'median': median(r[key] for r in selected),
                            'min': min(r[key] for r in selected), 'max': max(r[key] for r in selected)}
                       for key in ('wall', 'inversion', 'prediction', 'deconvolution', 'rss_mib', 'instructions', 'cycles')}
    gains = {key: 100*(1-stats['gpu'][key]['median']/stats['cpu'][key]['median'])
             for key in ('wall', 'inversion', 'prediction', 'deconvolution')}
    measured = {r['label']: r for r in rows if r['measured']}
    ratios = [measured[f'gpu-r{i}']['wall']/measured[f'cpu-r{i}']['wall'] for i in range(1,5)]
    checks = {'deterministic_repeat': gate(paths['cpu-j1a'], paths['cpu-j1b'], 'T0'),
              'deterministic_gpu': gate(paths['cpu-j1a'], paths['gpu-j1'])}
    for i in range(1,5):
        checks[f'gpu-r{i}-strict'] = gate(paths['cpu-r1'], paths[f'gpu-r{i}'])
    for a, b in itertools.combinations(range(1,5), 2):
        checks[f'cpu-r{a}-r{b}'] = gate(paths[f'cpu-r{a}'], paths[f'cpu-r{b}'])
    report = {'plan': plan, 'runs': rows, 'stats': stats, 'median_reduction_percent': gains,
              'paired_gpu_cpu_wall_ratios': ratios, 'gates': checks,
              'limits': ['one Apple M2, one 15-slot MS/configuration', 'four measured repetitions per variant',
                         'non-system dependencies other than schaapthreading remain shared',
                         'strict pixel gates are reported separately from reference-rerun envelopes']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'results.json').write_text(json.dumps(report, indent=2, default=lambda x: x.item()))
    print(json.dumps({'stats': stats, 'reduction_percent': gains, 'pair_ratios': ratios,
                      'gates': {k: v['pass'] for k,v in checks.items()}}, indent=2))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11,4), constrained_layout=True)
    for x, (mode, color) in enumerate([('cpu','#54748e'), ('gpu','#df863c')]):
        values = stats[mode]['wall']['samples']
        axes[0].scatter(np.full(len(values),x), values, color=color, s=45)
        axes[0].plot([x-.22,x+.22],[median(values)]*2,color=color,lw=3)
    for i, ratio in enumerate(ratios,1):
        axes[0].plot([0,1],[measured[f'cpu-r{i}']['wall'], measured[f'gpu-r{i}']['wall']],color='gray',alpha=.35)
    axes[0].set(xticks=[0,1],xticklabels=['CPU','GPU prediction'],ylabel='Wall time (s)',
                title=f"Four AB/BA pairs: {gains['wall']:.1f}% median reduction")
    x = np.arange(3)
    for dx, mode, color in [(-.18,'cpu','#54748e'),(.18,'gpu','#df863c')]:
        values = [stats[mode][k]['median'] for k in ('inversion','prediction','deconvolution')]
        axes[1].bar(x+dx,values,.36,label=mode.upper(),color=color)
    axes[1].set(xticks=x,xticklabels=['Inversion','Prediction','Deconvolution'],ylabel='Stage time (s)',
                title=f"Prediction: {gains['prediction']:.1f}% median reduction")
    axes[1].legend(); fig.suptitle('15-slot LWA · 3072² · 2.7 arcmin · 20,000 multiscale iterations · 8 threads')
    fig.savefig(args.output/'timing.png',dpi=180); plt.close(fig)
    cpu=fits.getdata(paths['cpu-j1a']/'img-image.fits').squeeze()
    gpu=fits.getdata(paths['gpu-j1']/'img-image.fits').squeeze()
    diff=gpu.astype(np.float64)-cpu
    vmax=float(np.percentile(cpu,99.0)); lim=max(float(np.percentile(np.abs(diff),99.0)),np.finfo(float).tiny)
    result=next(p for p in checks['deterministic_gpu']['products'] if p['name']=='img-image.fits')
    fig, ax = plt.subplots(1,2,figsize=(11,5),constrained_layout=True)
    image=ax[0].imshow(cpu,origin='lower',vmin=-.1*vmax,vmax=vmax,cmap='inferno')
    fig.colorbar(image,ax=ax[0],label=f'Jy/beam; vmax={vmax:.4g} (99th percentile)')
    image=ax[1].imshow(diff,origin='lower',vmin=-lim,vmax=lim,cmap='RdBu_r')
    fig.colorbar(image,ax=ax[1],label=f'GPU − CPU (Jy/beam); |limit|={lim:.3g} (99th percentile)')
    ax[0].set_title('Deterministic CPU restored image')
    ax[1].set_title(f"Prediction-only GPU difference: rel RMS {result['rel_rms']:.3g}\nStrict T2 {'PASS' if result['pass'] else 'FAIL'}")
    for a in ax:a.set(xlabel='Pixel',ylabel='Pixel')
    fig.savefig(args.output/'science.png',dpi=180);plt.close(fig)

    # Follow-up source-family evidence stays separate from the timing cohort.
    exits_path=args.artifact/'expanded-source-gate-exits.json'
    if exits_path.exists():
        exits=json.loads(exits_path.read_text())
        if len(exits)!=10 or {r['gpu_run'] for r in exits}!=set(range(1,11)):
            raise ValueError('incomplete expanded source family')
        families={}
        for row in exits:
            n=row['gpu_run']
            source=json.loads((args.artifact/f'sources-expanded-r{n}.json').read_text())
            families[str(n)]={'exit':row['exit'],'products':{
                name:{k:item[k] for k in ('checks','source_summary')}
                for name,item in source.items()}}
        passed=sum(row['exit']==0 for row in exits)
        summary={'cpu_reference_runs':10,'gpu_candidate_runs':10,'passed':passed,
                 'failed':10-passed,'criterion':'max (unchanged)', 'runs':families,
                 'fixed_model_prediction':json.loads((args.artifact/'fixed-prediction-gpu-gate.json').read_text())}
        (args.output/'validation.json').write_text(json.dumps(summary,indent=2))
        fig,ax=plt.subplots(figsize=(10,4),constrained_layout=True)
        metrics=[('img-image.fits','source','Restored source flux'),
                 ('img-model.fits','source','Model source flux'),
                 ('img-model.fits','mad_rms','Model MAD'),
                 ('img-residual.fits','source','Residual source flux'),
                 ('img-residual.fits','peak','Residual peak')]
        for product,metric,label in metrics:
            ratios=[]
            for n in range(1,11):
                item=families[str(n)]['products'][product]
                if metric=='source':
                    s=item['source_summary'];ratios.append(s['flux_ratio_spread']/s['flux_threshold'])
                else:
                    s=item['checks'][metric];ratios.append(s['deviation']/s['threshold'])
            ax.plot(range(1,11),ratios,'.-',label=label,alpha=.8)
        ax.axhline(1,color='black',ls='--',lw=1,label='CPU-family gate limit')
        ax.set(xlabel='GPU candidate run',ylabel='Deviation / reference-family limit',
               xticks=range(1,11),title=f'Threaded source gate: {passed}/10 pass, {10-passed}/10 fail against 10 CPU references')
        ax.legend(fontsize=8,ncol=3);fig.savefig(args.output/'source-envelopes.png',dpi=180);plt.close(fig)
        print(f'Expanded source gates: {passed}/10 pass; {10-passed}/10 fail (not a release acceptance)')


if __name__ == '__main__':
    main()
