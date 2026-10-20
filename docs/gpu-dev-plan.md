# GPU-dev branch + CPU stream plan (2026-10-19)

## Branch workflow

- `main`: CPU release stream. Patch discipline unchanged (work trees →
  `mx_tree.sh export` → `patches/mx`, replay check, immutable snapshots).
  Metal code on `main` stays exactly where 0.1.0 left it: gated, refusing,
  zero Metal symbols in the default build.
- `gpu-dev` (created, pushed, tracks `origin/gpu-dev`): all Metal development.
  Metal changes land here first; `main` accepts merges only at verified
  milestones (equivalence + speedup + full gates green). Patch renumbering on
  rebase is expected — re-export from the work tree, never hand-edit.
- Benchmarks compare across branches via frozen snapshots (`bench/bin/*`),
  never by rebuilding the other branch's tree.

## Milestones (gpu-dev)

- **M0 — kill the shadow bug.** Apply the 4-line fix
  (`metalinversion.mm:286-289`: drop shadowing decls, resize outers, reset
  min/max), build with `-Wshadow` + ASan, log `w_lambda.size()`, `w_min/max`,
  `nplanes` vs ducc0 `verbosity=1` layout (~125 planes on 3C196). Done when the
  OOB is gone and the layout matches.
- **M1 — plane-level equivalence.** Decisive tests H2–H5: single-visibility
  footprint/degrid phase vs ducc0 at large |u| and w=±10λ; `wWeight` ladder vs
  `x2grid_c` taps (must sum ~1); plane-grid swap (ducc0 grid → Metal extract
  and vice versa); on-axis source and `MX_METAL_DEBUG_NOSCREEN=1` at w=0.
  Done when corr ≥ 0.999 on the w-sweep. H2–H5 may be masked by H1 — re-rank
  after M0.
- **M2 — band-limited transforms, measured bake-off.** Port ducc0's
  `uranges`/`vranges` discipline first (the 4.5× slowdown is full per-plane
  FFTs + per-call MSL recompile — fix the algorithm before the hardware).
  Then CPU-vs-GPU FFT on identical plane grids; proceed only if measured win.
- **M3 — full w-path, gated.** Wire `-mgpu` w-layers behind the refusing gate;
  3C196 + quiet-Sun families must meet T2 before the gate opens. Merge to
  `main` only here.

## FFT-on-GPU / gridding-on-CPU hybrid — verdict: valid, but M2 not M0

- Why it could work here: Apple Silicon unified memory — shared MTLBuffers,
  no PCIe copy; a 1408² complex grid (16 MB) moves in ~0.3 ms. On discrete
  GPUs the transfer alone would kill it.
- Why not now: the hybrid needs exactly what is broken — correct plane layout
  and w-screen. It would build a second correctness surface (FFT twiddles,
  normalization, complex2hartley convention) on an unverified foundation, and
  duplicate the band-limit work M2 must do anyway.
- FFT options, ranked: (1) custom Stockham Metal kernels — real work, must
  match ducc0 bit-plausibly; (2) MPSImageFFT — pow2-only, grid sizes
  (350/378/392…) are not pow2, rejected; (3) Accelerate/vDSP — CPU, already
  measured 3× slower than ducc0, rejected.
- Rule: no GPU-FFT code until M1 passes; at M2 the bake-off decides, measured
  per-plane timings on LOFAR geometry, not assumed. If ducc0's multithreaded
  band-limited FFT wins, the hybrid dies there.

## CPU stream (main) — optimize under equivalence

Constraint: every change gated by T0/T2 + basin re-run; perf work on feature
branches, `main` only when gates pass. Ranked by expected value:

1. **Peak-search oversubscription** (review §1): `DynamicFor` scales ×
   per-scale full-ThreadPool ducc0 FFTs. Benchmark full threads vs
   inner-FFT-at-1-thread; take the win only if T2 holds.
2. **Divisibility guard + mixed-shape test** (`columnblock.h:32`) and
   **NaN median/MAD vectors** (`image.h`) — correctness hardening, cheap.
3. **Kernel-cache thundering-herd** — bounded, minor; stress test + RSS assert.
4. Stop. Profile says ducc0-kernel floor beyond this; further CPU work needs
   new measurements, not new patches.

## Hardening batch (main, before 0.1.1)

Review §3 HIGHs 1–6, each with a regression test: `mx_tree.sh` repo allowlist;
`flake.sh` validators + noclobber + MS-writer guards; pointflux scratch guard;
trim keep-list from plotter constants + trash-dir deletion. Plus
`compare_sources` ≥2-refs requirement and formula CI asserts (sha sync,
revision pins, `test` block images). Small, mechanical, high accident-avoidance
value — do first, it protects everything else.
