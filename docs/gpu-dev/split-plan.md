# gpu-dev precision split: what runs where, and why

Status: w-layer inversion matches ducc0 (`rel_rms ~1.3e-05` at w = 0–200).
This plan exploits Apple Silicon unified memory (empirically confirmed:
11.5 GB/s GPU read of Shared buffers, zero sync calls in the codebase)
with a hard rule from the hardware: **MSL rejects `double` entirely**,
so GPU stages must be provably float-safe and double stays on CPU.

## The split

| Stage | Where | Precision | Why |
|---|---|---|---|
| Cost model / `chooseKernel` | CPU | double | ranking maths, negligible cost |
| `nm1` scan, `planeLayout` (dw, nplanes, wmin) | CPU | double | `sqrt(1-l²-m²)-1` cancels on-axis; 1% dw error visibly drifts w-interpolation |
| w-ladder (`w_λ`, `wsign`, `plane_items`, `wWeight`) | CPU | double | `z = 2·((w_plane−w_vis)/dw − nth)+(W−1)` cancels nearby plane distances |
| uvw/λ, flips, signs | CPU | double | at \|w\| ~ 1e4 λ, float32 λ error becomes ~1e-3 rad phase error |
| Screen phases + sincos, correction map | CPU | double → float32 out | phase argument reaches ~300 rad; ducc0 does the same (range-reduce in double, then cast) |
| **Handoff** | Shared buffers, zero copies | float32 / uint32 | per-plane visibilities (4×f32), bucket start/items (u32), coeffs (f32), correction map, sincos map |
| Grid accumulation (`poly-hoisted-split/columns`) | GPU | float32 + CAS atomics | gate `rel_max/rms ≤ 5e-5`; measured 1.8e-5 grid, 1.4e-5 adjoint |
| Per-plane FFT | GPU (MPS or custom; open) | complex float32 | the plane loop's biggest remaining CPU share; reference is itself `<float,float>`, so relative precision is preserved |
| Roll, screen apply, global corrections | CPU for now | float32 | elementwise screen/correction maps are the obvious next GPU kernels after FFT |

## Numerical-consistency rule (non-negotiable)

The Metal backend may run **only** maths that performs exactly the same
computation as the ducc0 call it replaces. Reference is
`ms2dirty_bda<float,float>`; if it ever moves to `<double,double>`,
the plane-loop accumulation and FFT must be re-gated. Every refusal
must say why. Gates per stage: kernel eval abs/rel 4.5e-6, grid
`rel_max/rms ≤ 5e-5` + structural-zero checks, roundtrip degrid ≤ 5e-5,
adjoint ≤ 1e-5, image vs reference via `bench/metal/wlayer_check.cpp`.

## What to measure (prove the win, don't assert it)

- Per-plane `gpu_seconds` (`GPUEndTime−GPUStartTime`) vs `wall` vs `host`
  from `GridAccumResult`; `throughput_Mvis_s` (66 Mvis/s at 256² today).
- CPU `c2c`-per-plane time (the FFT share that justifies a GPU FFT).
- End-to-end wall vs ducc0 `ms2dirty_bda<float,float>`
  (`build-mx-metal/cpu-ducc0-baseline.txt`).
- Next profiling target: host bucketing/alloc already dominates small
  runs (`host_ms=0.99 > gpu_ms=0.30` at 20k vis/256²) — GPU port or
  CPU/GPU overlap before FFT work.

See `split-diagram.html` (same directory) for the visual version.
