#!/usr/bin/env python3
"""Real CLI regression for malformed cached beams and unequal-channel MFS metadata."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np
from astropy.io import fits

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant')
    parser.add_argument('tag')
    parser.add_argument('artifact',type=Path)
    args=parser.parse_args()
    args.artifact.mkdir(parents=True,exist_ok=False)
    seed=ROOT/'bench/out/gpu-beam-reference/gpu-followup-beam'
    ms='bench/out/gpu-audit-20261022-0715/input-15.ms'
    records=[]
    for label,value in [('invalid-string','invalid'),('undefined',None),('negative',-1.0)]:
        fixture=args.artifact/label;fixture.mkdir()
        with fits.open(seed/'img-psf.fits',memmap=False) as hdus:
            hdus[0].header['WSCTBEAM']=value
            hdus.writeto(fixture/'img-psf.fits')
        tag=args.tag+'-'+label
        cmd=['bash','bench/run.sh',args.variant,tag,'-j','1','-size','3072','3072','-scale','2.7amin','-niter','1','-reuse-psf',str(fixture/'img'),'-reuse-dirty',str(seed/'img'),'-reorder',ms]
        result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=180)
        run=ROOT/'bench/out'/tag/args.variant
        log=(run/'wsclean.log').read_text()+(run/'time.txt').read_text()
        ok=result.returncode!=0 and 'Invalid WSCTBEAM' in log
        records.append({'case':label,'pass':ok,'exit':result.returncode,'command':cmd})
        print(label,'PASS' if ok else 'FAIL',flush=True)
    tag=args.tag+'-mfs'
    cmd=['bash','bench/run.sh',args.variant,tag,'-j','4','-size','512','512','-scale','2.7amin','-channels-out','2','-niter','1','-reorder',ms]
    result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=180)
    run=ROOT/'bench/out'/tag/args.variant
    channels=sorted(run.glob('img-????-psf.fits'))
    ok=False;values=[];mfs=None
    if result.returncode==0 and len(channels)==2:
        values=[float(fits.getheader(f)['WSCTBEAM']) for f in channels]
        mfs=float(fits.getheader(run/'img-MFS-psf.fits')['WSCTBEAM'])
        ok=values[0]!=values[1] and np.isclose(mfs,min(values),rtol=1e-12,atol=0)
    records.append({'case':'mfs','pass':bool(ok),'exit':result.returncode,'channels':values,'mfs':mfs,'command':cmd})
    (args.artifact/'results.json').write_text(json.dumps(records,indent=2))
    print('MFS','PASS' if ok else 'FAIL',values,mfs,flush=True)
    return 0 if all(r['pass'] for r in records) else 1


if __name__=='__main__':raise SystemExit(main())
