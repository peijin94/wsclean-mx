#!/usr/bin/env python3
"""Render the measured 150k-budgeted exo-pipe benchmark, without extrapolation."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
data=json.loads((HERE/'results.json').read_text())
runs=sorted(data['runs'],key=lambda r:(r['size'],r['repeat']))
fig,axes=plt.subplots(1,2,figsize=(12,4.6),constrained_layout=True)
x=np.arange(len(runs));bottom=np.zeros(len(runs))
for key,label,color in [('inversion_s','Inversion','#3576ad'),
                        ('prediction_s','Prediction','#8868b5'),
                        ('clean_s','CLEAN','#d99530'),
                        ('other_s','Other / I/O','#9aa1aa')]:
    values=np.array([r[key] for r in runs])
    axes[0].bar(x,values,bottom=bottom,label=label,color=color)
    bottom+=values
for i,run in enumerate(runs):
    axes[0].text(i,run['wall_s']+2,f"{run['wall_s']:.2f}s",ha='center',fontsize=9)
axes[0].set(xticks=x,xticklabels=[f"{r['size']}\nrun {r['repeat']}" for r in runs],
            ylabel='Wall time (seconds)',title='Every measured run, actual stage times')
axes[0].set_ylim(0,max(bottom)*1.18);axes[0].legend(fontsize=8)
components=[data['summary'][str(s)]['components'][0] for s in (3072,4096)]
axes[1].bar([0,1],components,color=['#167a83','#398ca5'],width=.55)
axes[1].axhline(150000,color='#ba4b3b',ls='--',label='Requested maximum: 150,000')
for i,n in enumerate(components):axes[1].text(i,n+3000,f'{n:,}',ha='center')
axes[1].set(xticks=[0,1],xticklabels=['3072 square','4096 square'],ylim=(0,170000),
            ylabel='Completed CLEAN iterations',title='Both reached the final threshold before the cap')
axes[1].legend(fontsize=8,loc='upper center')
fig.suptitle('15-slot exo-pipe-style deep imaging · M2 · 8 CPU threads · GPU off',fontsize=13)
fig.savefig(HERE/'timing-and-convergence.png',dpi=170)
plt.close(fig)
print(HERE/'timing-and-convergence.png')
