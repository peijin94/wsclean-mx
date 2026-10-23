#!/usr/bin/env python3
"""Native profiling gate; missing runtime Metal work is a failure, not a skip."""
import json
import os
from pathlib import Path
import subprocess
import sys


def check(text):
    spans=[json.loads(line[len('MX_PROFILE '):]) for line in text.splitlines() if line.startswith('MX_PROFILE ')]
    required={'fusion.copy_inputs','fusion.encode_commit','fusion.wait','fusion.gpu'}
    assert required <= {s['stage'] for s in spans},'missing fusion copy/command spans'
    copies=[s for s in spans if s['stage']=='fusion.copy_inputs']
    assert any(s['bytes']>0 for s in copies),'RMS/mask uploads not accounted'
    commands={}
    for span in spans:
        if span['stage'] in {'fusion.encode_commit','fusion.wait','fusion.gpu'} and span['command_id']:
            commands.setdefault((span['id'],span['command_id']),{})[span['stage']]=span
    positive=0
    for events in commands.values():
        assert {'fusion.encode_commit','fusion.wait','fusion.gpu'}<=events.keys()
        e,w,g=(events[k] for k in ('fusion.encode_commit','fusion.wait','fusion.gpu'))
        if g['end']>g['start']>0:
            assert e['start']-0.001<=g['start']<g['end']<=w['end']+0.001
            positive+=1
    assert positive>0,'no completed timed GPU commands'
    return {'commands':len(commands),'positive_gpu_intervals':positive,'copied_bytes':sum(s['bytes'] for s in copies)}


def main():
    binary=Path(sys.argv[1]).resolve();folder=Path(sys.argv[2]);folder.mkdir(exist_ok=False)
    env={k:v for k,v in os.environ.items() if not k.startswith('MX_METAL_')}
    env.update(MX_METAL_PROFILE='1',MX_METAL_DEBUG_TIMING='1')
    p=subprocess.run([str(binary)],env=env,capture_output=True,text=True,timeout=180)
    (folder/'stdout.log').write_text(p.stdout);(folder/'stderr.log').write_text(p.stderr)
    assert p.returncode==0,f'native probe failed: {p.returncode}'
    result=check(p.stderr)
    (folder/'result.json').write_text(json.dumps(result,indent=2))
    print('PASS runtime fusion copy/command profile',result)

if __name__=='__main__':main()
