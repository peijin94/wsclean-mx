# GPU resource-residency evidence

Implementation: WSClean `ff01a434`, Radler `ea55b61`; frozen candidate
`bench/bin/gpu-resource-v1/wsclean`. Baseline: `gpu-profile-delivered`.

Full report: `../../gpu-resource-optimization-2026-10-22.md`.

## Read these together

- `results.json`: 79 planned runs, complete commands/environments, raw timing
  samples, resource counters, budget receipts and profile-stage aggregates.
- `summary.json`: per-phase medians, ranges and samples; warmups excluded.
- `delivery.json`: verification inventory and explicit failed science gates.
- `delivered-provenance.json`, `patch-replay.json`: source/binary/library identity
  and exact reproduction of every component's exported patch stack.
- `*-comparisons.json`: unchanged full-product T0/T2 results, including failures.
  `optimization-comparisons.json` compares new paths with old GPU convolution;
  that does not replace the failed CPU-reference checks.
- `timing-counter-summary.txt`: existing hardware-counter mode assessment,
  reported as comparable but not proof that a small wall delta is resolved.
- `cpu-feed.json`: CPU/GPU interval accounting and monitor data summaries.
- `image-metrics.json`: first matched-input CPU/fused pair, p99 display settings,
  common horizon mask, crop coordinates and image hashes. Its masked statistics
  do not replace full-product scientific gates.

## Figures

`resources.png` shows four measured timing trials per mode plus separate traced
copy counts and owned-buffer/RSS measurements. `overlap.png` compares normal
bounded two-slot scheduling with immediate waits. The two restored-image figures
use the first predeclared matched-input pair and retain the strict T2 failure.

Render resources/overlap from the repository root:

```sh
.venv/bin/python -m bench.plot_gpu_resources \
  docs/bench/gpu-resource-20261022/results.json \
  docs/bench/gpu-resource-20261022
```

The image renderer is `bench.plot_gpu_status.render_comparison`; directories,
source version, `gpu_label` and crop are preserved in `image-metrics.json`.
Raw logs, RED/GREEN evidence and immutable input manifests are preserved in
`bench/out/gpu-opt-20261022-153051/` (not substituted with synthetic results).

**Conclusion:** resource and operation-level gates pass; no dependable whole-run
speedup is demonstrated, and GPU-convolution CPU-equivalence remains unresolved.
Deconvolution stays opt-in. The cap concerns owned buffer capacities, not total
physical unified memory, driver overhead, or process RSS.
