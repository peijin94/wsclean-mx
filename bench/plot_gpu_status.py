#!/usr/bin/env python3
"""Publishable GPU benchmark figures from real, explicitly selected run products.

Pixel coordinates are zero-based, x=column/y=row, origin='lower'. Image panels
share the CPU p99 scale; the zoom uses its own CPU p99 and is labeled separately.
No interpolation, smoothing, registration or normalization is applied to pixels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

import numpy as np
from astropy.io import fits
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import SymLogNorm
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]


def crop_bounds(shape, center=(0.25, 0.6), fraction=0.25):
    ny, nx = shape
    if not (0 < fraction <= 1) or any(not 0 <= p < 1 for p in center):
        raise ValueError('invalid crop fraction or center')
    cx, cy = min(nx-1, round(center[0]*nx)), min(ny-1, round(center[1]*ny))
    width, height = max(1, round(nx*fraction)), max(1, round(ny*fraction))
    x0 = max(0, min(nx-width, cx-width//2))
    y0 = max(0, min(ny-height, cy-height//2))
    return {'requested_center_fraction_xy': list(center), 'center_xy': [cx, cy],
            'requested_center_xy_float': [center[0]*nx, center[1]*ny],
            'bounds_xyxy': [x0, y0, x0+width, y0+height],
            'shape_yx': [height, width]}


def image_stats(cpu, gpu, mask):
    a, b = cpu[mask].astype(np.float64), gpu[mask].astype(np.float64)
    if not a.size or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError('selected region must have finite, nonempty image coverage')
    d = b-a
    vmax = float(np.percentile(a, 99.0))
    if vmax <= 0:
        raise ValueError('positive CPU p99 required for this image display')
    rms_a = float(np.sqrt(np.mean(a*a)))
    rms_d = float(np.sqrt(np.mean(d*d)))
    correlation = float(np.corrcoef(a, b)[0, 1]) if np.std(a) and np.std(b) else None
    return {'pixels': int(a.size), 'vmax_cpu_p99': vmax,
            'vmin': -0.02*vmax, 'difference_abs_p99': float(np.percentile(np.abs(d), 99.0)),
            'cpu_peak': float(np.max(a)), 'gpu_peak': float(np.max(b)),
            'max_abs_difference': float(np.max(np.abs(d))), 'difference_rms': rms_d,
            'cpu_rms': rms_a, 'relative_rms': rms_d/rms_a,
            'relative_peak': float(np.max(np.abs(d))/np.max(np.abs(a))),
            'pearson_r': correlation}


def render_comparison(cpu_dir, gpu_dir, out, version, center=(0.25, 0.6), fraction=0.25,
                      gpu_label='GPU prediction'):
    cpu_dir, gpu_dir, out = map(Path, (cpu_dir, gpu_dir, out))
    cpu, ch = fits.getdata(cpu_dir/'img-image.fits', header=True)
    gpu, gh = fits.getdata(gpu_dir/'img-image.fits', header=True)
    cpu, gpu = np.squeeze(cpu), np.squeeze(gpu)
    if cpu.ndim != 2 or cpu.shape != gpu.shape:
        raise ValueError('expected matching 2-D restored image planes')
    if ch.get('BUNIT') != gh.get('BUNIT'):
        raise ValueError('image brightness units differ')
    for key in ('CTYPE1', 'CTYPE2', 'CUNIT1', 'CUNIT2', 'CRPIX1', 'CRPIX2',
                'CRVAL1', 'CRVAL2', 'CDELT1', 'CDELT2'):
        if ch.get(key) != gh.get(key):
            raise ValueError('image WCS differs: '+key)
    cm = np.squeeze(fits.getdata(cpu_dir/'img-horizon-mask.fits'))
    gm = np.squeeze(fits.getdata(gpu_dir/'img-horizon-mask.fits'))
    if cm.shape != cpu.shape or not np.array_equal(cm, gm) or not np.all(np.isfinite(cm)):
        raise ValueError('horizon masks differ or do not match the images')
    mask = cm > 0
    bounds = crop_bounds(cpu.shape, center, fraction)
    x0, y0, x1, y1 = bounds['bounds_xyxy']
    full = image_stats(cpu, gpu, mask)
    zoom = image_stats(cpu[y0:y1, x0:x1], gpu[y0:y1, x0:x1], mask[y0:y1, x0:x1])
    result = {'version': version, 'gpu_label': gpu_label,
              'cpu_directory': str(cpu_dir), 'gpu_directory': str(gpu_dir),
              'shape_yx': list(cpu.shape), 'pixel_origin': 'lower; zero-based x=column, y=row',
              'crop': bounds, 'percentile': 99.0, 'mask': 'common stored horizon mask > 0',
              'brightness_unit': ch.get('BUNIT', 'unknown'), 'full': full, 'zoom': zoom,
              'input_sha256': {},
              'fits_metadata': {key: ch.get(key) for key in
                                ('CRVAL1','CRVAL2','CRVAL3','BMAJ','BMIN','BPA','DATE-OBS','WSCVERSI','WSCVDATE')}}
    for role, folder in [('cpu', cpu_dir), ('gpu', gpu_dir)]:
        for name in ('img-image.fits', 'img-horizon-mask.fits'):
            with (folder/name).open('rb') as stream:
                result['input_sha256'][role+'/'+name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    for is_zoom, stats, filename in [(False, full, 'restored-full-field.png'),
                                      (True, zoom, 'restored-extended-zoom.png')]:
        if is_zoom:
            a, b, selected = cpu[y0:y1,x0:x1], gpu[y0:y1,x0:x1], mask[y0:y1,x0:x1]
            extent = [x0-0.5,x1-0.5,y0-0.5,y1-0.5]
        else:
            a, b, selected = cpu, gpu, mask
            extent = [-0.5,cpu.shape[1]-0.5,-0.5,cpu.shape[0]-0.5]
        diff = b.astype(np.float64)-a.astype(np.float64)
        fig, axes = plt.subplots(1,3,figsize=(16,6))
        cmap = plt.get_cmap('inferno').copy(); cmap.set_bad('#dce1e5')
        for ax, data, title in zip(axes[:2], [a,b], ['CPU restored (reference)',f'{gpu_label} restored (-mgpu)']):
            im=ax.imshow(np.ma.array(data,mask=~selected),origin='lower',extent=extent,
                         cmap=cmap,interpolation='nearest',vmin=stats['vmin'],vmax=stats['vmax_cpu_p99'])
            ax.set_title(title,fontsize=12)
            fig.colorbar(im,ax=ax,fraction=.046,pad=.025,
                         label=f"{result['brightness_unit']}; CPU p99 vmax={stats['vmax_cpu_p99']:.4g}")
            if not is_zoom:
                ax.add_patch(Rectangle((x0-.5,y0-.5),x1-x0,y1-y0,fill=False,edgecolor='#40e4df',linewidth=1.2))
                ax.plot(*bounds['center_xy'],marker='+',color='#40e4df',markersize=8)
        dcmap=plt.get_cmap('RdBu_r').copy(); dcmap.set_bad('#dce1e5')
        dmax=max(stats['difference_abs_p99'],np.finfo(np.float32).tiny)
        dnorm=SymLogNorm(linthresh=dmax*.01,vmin=-dmax,vmax=dmax,base=10)
        im=axes[2].imshow(np.ma.array(diff,mask=~selected),origin='lower',extent=extent,
                          cmap=dcmap,norm=dnorm,interpolation='nearest')
        axes[2].set_title(f"GPU - CPU (independent difference scale)\nrelative RMS={stats['relative_rms']:.3g}; max |diff|={stats['max_abs_difference']:.3g}",fontsize=11)
        fig.colorbar(im,ax=axes[2],fraction=.046,pad=.025,
                     label=f"{result['brightness_unit']}; symlog, +/-p99={dmax:.3g}")
        for ax in axes:
            ax.set_xlabel('x pixel (column)'); ax.set_ylabel('y pixel (row)')
        region=f"Zoom x=[{x0},{x1}), y=[{y0},{y1}); requested center=(0.25 Nx, 0.60 Ny)" if is_zoom else f"Full field {cpu.shape[1]} x {cpu.shape[0]}; cyan box marks the requested extended-structure patch"
        fig.suptitle(f'gpu-dev {version[:7]} | 15-slot OVRO-LWA | CPU vs {gpu_label}\n{region}',fontsize=14,y=.98)
        fig.text(.5,.055,f"Origin lower, zero-based pixels. Only common horizon-mask pixels shown/statistically compared ({stats['pixels']:,} pixels).",ha='center',fontsize=10)
        fig.text(.5,.025,'Same linear CPU p99 stretch for CPU/GPU; zoom has its own p99. Differences use a separate amplified symlog scale. No smoothing.',ha='center',fontsize=10)
        fig.tight_layout(rect=(0,.15,1,.89))
        fig.savefig(out/filename,dpi=170)
        plt.close(fig)
    return result


def plot_timings(runs, out, version):
    chosen=[r for r in runs if r['phase']=='timing' and not r['warmup']]
    if len(chosen)!=6 or any(sum(r['mode']==m for r in chosen)!=3 for m in ('cpu','prediction')):
        raise ValueError('expected three CPU and three GPU timing measurements')
    summary={mode:{field:{'median':statistics.median(r['times'][field] for r in chosen if r['mode']==mode),
                          'min':min(r['times'][field] for r in chosen if r['mode']==mode),
                          'max':max(r['times'][field] for r in chosen if r['mode']==mode)}
                   for field in ('wall_s','inversion_s','prediction_s','deconvolution_s','rss_bytes')}
             for mode in ('cpu','prediction')}
    fig,ax=plt.subplots(figsize=(11,5.5),constrained_layout=True)
    x=np.arange(len(chosen)); bottom=np.zeros(len(chosen))
    for field,label,color in [('inversion_s','CPU inversion','#4978a8'),('deconvolution_s','CPU deconvolution','#e9a34d'),
                              ('prediction_s','Prediction','#4a9f87'),('other_s','Other / startup / I-O','#c9c9c9')]:
        values=np.array([r['times'][field] for r in chosen])
        if np.any(values<0):raise ValueError('negative timing stage')
        ax.bar(x,values,bottom=bottom,label=label,color=color);bottom+=values
    for i,r in enumerate(chosen):ax.text(i,bottom[i]+.15,f"{r['times']['wall_s']:.2f}s",ha='center')
    labels=[]; counts={'cpu':0,'prediction':0}
    for r in chosen:
        counts[r['mode']]+=1;labels.append(('CPU' if r['mode']=='cpu' else 'GPU')+str(counts[r['mode']]))
    ax.set_xticks(x,labels);ax.set_ylabel('Whole-program wall seconds')
    ax.set_ylim(0,max(bottom)*1.20)
    ax.set_title(f'gpu-dev {version[:7]} | 3072², 15 slots, -j 8 | chronological AB / BA / AB\n'
                 f"Median wall CPU {summary['cpu']['wall_s']['median']:.2f}s / GPU {summary['prediction']['wall_s']['median']:.2f}s; two warmups and trace excluded")
    ax.legend(loc='upper left',ncol=4,fontsize=9)
    fig.savefig(out/'benchmark-timing.png',dpi=170);plt.close(fig)
    return summary


def plot_profile(run, raw, out, version):
    folder=ROOT/'bench/out'/run['tag']/run['variant']
    spans=[json.loads(line[len('MX_PROFILE '):]) for line in (folder/'time.txt').read_text().splitlines() if line.startswith('MX_PROFILE ')]
    sessions=[s for s in spans if s['stage']=='prediction.session']
    if len(sessions)!=1:raise ValueError('profile figure requires one prediction session')
    session=sessions[0];t0=session['start']
    monitor=[json.loads(line) for line in (raw/'trace'/(run['tag']+'.monitor.jsonl')).read_text().splitlines()]
    origin=monitor[0]['mach_s']
    fig,axes=plt.subplots(3,1,figsize=(12,10),constrained_layout=True,gridspec_kw={'height_ratios':[1,1.5,1.3]})
    ax=axes[0];ax.plot([r['mach_s']-origin for r in monitor],[r['Device Utilization %'] for r in monitor],color='#3b9c7d',label='GPU gauge (device-wide, all apps)')
    ax.set(ylabel='Device gauge (%)',ylim=(0,105),xlabel='Seconds since monitor start')
    times=[];cores=[]
    for a,b in zip(monitor,monitor[1:]):
        if all(k in a and k in b for k in ('cpu_user_s','cpu_system_s')):
            times.append(a['mach_s']-origin)
            cores.append((b['cpu_user_s']+b['cpu_system_s']-a['cpu_user_s']-a['cpu_system_s'])/(b['mach_s']-a['mach_s']))
    twin=ax.twinx();twin.plot(times,cores,color='#4978a8',alpha=.7,label='WSClean CPU core-equivalents');twin.set(ylabel='CPU core-equivalents',ylim=(0,8.5))
    handles=ax.get_lines()+twin.get_lines();ax.legend(handles,[l.get_label() for l in handles],fontsize=8)
    ax.axvspan(session['start']-origin,session['end']-origin,color='gray',alpha=.15)
    ax.set_title(f'gpu-dev {version[:7]} | separate instrumented run, not timing evidence')
    lanes=[('prediction.initialize','CPU plan/setup'),('prediction.prepare','CPU prepare'),('prediction.consume','CPU degrid'),('fft.wait','CPU wait'),('gpu0','GPU slot 0'),('gpu1','GPU slot 1')]
    for i,((stage,label),color) in enumerate(zip(lanes,['#999999','#e9a34d','#4978a8','#cc6666','#3b9c7d','#71ba9f'])):
        selected=[s for s in spans if s['stage']=='fft.gpu' and s.get('slot')==int(stage[-1])] if stage.startswith('gpu') else [s for s in spans if s['stage']==stage]
        axes[1].broken_barh([(s['start']-t0,s['end']-s['start']) for s in selected],(i-.35,.7),facecolors=color)
    budget=run['prediction_budget']
    axes[1].set(yticks=range(len(lanes)),yticklabels=[p[1] for p in lanes],xlabel='Seconds into prediction session',
                title=f"GPU command union {budget['gpu_union_s']:.3f}s / session {budget['session_s']:.3f}s = {100*budget['residency_fraction']:.1f}% residency (not shader occupancy)",xlim=(0,session['end']-t0))
    axes[1].invert_yaxis()
    for stage,label,color in [('prediction.prepare','CPU prepare','#e9a34d'),('prediction.consume','CPU degrid','#4978a8'),('fft.gpu','GPU command','#3b9c7d'),('fft.wait','CPU wait','#cc6666')]:
        selected=sorted([s for s in spans if s['stage']==stage and 'plane' in s],key=lambda s:s['plane'])
        axes[2].plot([s['plane'] for s in selected],[(s['end']-s['start'])*1000 for s in selected],label=label,color=color)
    axes[2].set(xlabel='W-plane index',ylabel='Per-plane interval (ms)',title='CPU supply and completion waiting vary by plane; overlapping intervals are not additive')
    axes[2].legend(ncol=4,fontsize=8)
    fig.savefig(out/'prediction-profile.png',dpi=170);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    config=json.loads((args.raw/'config.json').read_text())
    runs=json.loads((args.raw/'runs.json').read_text())
    receipts=json.loads((args.raw/'receipts.json').read_text())
    if not len(receipts)==len(runs)==len(config['plan']) or any(r['exit']!=0 for r in receipts):raise ValueError('incomplete or failed campaign')
    for planned,receipt,run in zip(config['plan'],receipts,runs):
        if any(receipt.get(k)!=v for k,v in planned.items()) or run['tag']!=planned['tag']:raise ValueError('campaign identity mismatch')
    cpu=ROOT/'bench/out'/config['image_cpu_tag']/'gpu-profile-delivered'
    gpu=ROOT/'bench/out'/config['image_gpu_tag']/'gpu-profile-delivered'
    images=render_comparison(cpu,gpu,args.output,config['source_root_commit'],tuple(config['crop_center_fraction_xy']),config['crop_extent_fraction_xy'][0])
    timing=plot_timings(runs,args.output,config['source_root_commit'])
    trace=[r for r in runs if r['phase']=='trace']
    if len(trace)!=1:raise ValueError('expected one separately profiled run')
    plot_profile(trace[0],args.raw,args.output,config['source_root_commit'])
    result={'config':config,'timing':timing,'image_comparison':images,'trace':trace[0],
            'runs':runs,'receipts':receipts,'image_pair_selection':config['image_pair_policy']}
    (args.output/'results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'timing':timing,'images':images,'profile':trace[0]['prediction_budget']},indent=2))


if __name__=='__main__':main()
