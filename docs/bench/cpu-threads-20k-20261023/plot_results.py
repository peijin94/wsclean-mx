#!/usr/bin/env python3
"""Render the recorded quick 20k sweep; no new measurements or extrapolation."""
import json
from pathlib import Path
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / 'results.json').read_text())
RUNS = [r for r in DATA['runs'] if not r['warmup']]
THREADS = [8, 4, 12, 16]
if len(RUNS) != 8 or any(r['niter'] != 20000 or r['exit'] != 0 for r in RUNS):
    raise ValueError('Expected eight successful measured runs at the explicit 20k cap')
if sorted((r['threads'], r['repeat']) for r in RUNS) != sorted((j, rep) for j in THREADS for rep in (1, 2)):
    raise ValueError('Missing or duplicated thread/repeat')

figure, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
for axis, key, title, ylabel, color in [
        (axes[0], 'wall_s', 'Wall time: two opposite-order passes', 'Wall time (s)', '#4c72b0'),
        (axes[1], 'machine_cpu_percent', 'Average CPU use over the whole run', 'CPU time / eight logical CPUs (%)', '#16847d')]:
    medians = []
    for index, threads in enumerate(THREADS):
        values = [r['times'][key] for r in RUNS if r['threads'] == threads]
        medians.append(statistics.median(values))
        axis.scatter(index + np.array([-0.05, 0.05]), values, color='black', s=25, zorder=3,
                     label='individual runs' if index == 0 else None)
    axis.bar(range(len(THREADS)), medians, color=color, alpha=0.6, width=0.55, label='median')
    for index, value in enumerate(medians):
        axis.text(index, max(r['times'][key] for r in RUNS if r['threads'] == THREADS[index]) + (0.6 if key == 'wall_s' else 2),
                  f'{value:.2f}' if key == 'wall_s' else f'{value:.1f}%', ha='center', fontsize=10)
    axis.set(xticks=range(len(THREADS)), xticklabels=[f'-j {j}' for j in THREADS],
             xlabel='Requested worker threads', ylabel=ylabel, title=title)
    axis.set_ylim(0, 34 if key == 'wall_s' else 100)
    axis.grid(axis='y', alpha=0.2)
    axis.set_axisbelow(True)
handles, labels = axes[0].get_legend_handles_labels()
figure.legend(handles, labels, loc='lower center', ncol=2, frameon=False)
figure.suptitle('M2 CPU-only: 3072 square, 15 integrations, explicit niter=20,000', fontsize=13)
figure.tight_layout(rect=(0, 0.07, 1, 0.94))
figure.savefig(HERE / 'thread-sweep.png', dpi=150)
plt.close(figure)
print(HERE / 'thread-sweep.png')
