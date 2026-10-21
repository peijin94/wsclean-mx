# exo-pipe-style 4k deep clean: timing reconciliation

Data: LWA 64 MHz, first 4 time slots. Mac `/tmp/lwa-4slot.ms` (247,104 rows),
inti `/data1/users/pz47/lwa-bench/lwa-4slot-flat.ms` (248,512 rows, materialised
775 MB copy — no reference-table indirection).

Parameters (exo-pipe deep template, 4k adaptation):
`-size 4096 4096 -scale 2amin -weight briggs 0 -pol I -multiscale
-multiscale-scale-bias 0.8 -niter 20000 -mgain 0.95 -auto-threshold 0.5
-auto-mask 3 -local-rms -horizon-mask 10deg`

## Corrected table

| machine | inversion | prediction | deconvolution | stage sum | real | gap |
|---|---|---|---|---|---|---|
| Mac CPU (j8) | 8.55 | 3.87 | 12.95 | 25.37 | 26.68 | 1.31 |
| Mac GPU (j8) | 39.57 | 3.98 | 13.40 | 56.95 | 58.28 | 1.33 |
| inti CPU (j24, flat MS) | 17.43 | 6.35 | 77.23 | 101.01 | 107.96 | 6.95 |

All values seconds. 20000 iterations, 2 major iterations → 3 inversions,
2 predictions.

Gap = startup + final PSF/restore/FITS writes (4k images are 67 MB each,
6 products ≈ 400 MB).

## Where the earlier numbers went wrong

The first pass reported Mac wall times of 114 s and 102 s. Those were
**background-process session uptimes** (shell startup, `mkdir`, session
restore), not the wsclean run. Taken from `/usr/bin/time -l`'s `real` line the
true walls are 26.68 s and 58.28 s, and the three wsclean stages then account
for all but ~1.3 s.

## Interpreting the stage split

- **Inversion is 3× per clean.** 8.55 s / 3 = 2.85 s per inversion (CPU),
  39.57 / 3 = 13.19 s (GPU). Matches the dirty-only 2amin numbers (2.74 s CPU,
  10.76 s GPU) plus per-iteration bookkeeping.
- **Prediction is identical on both** (3.87 vs 3.98 s) — pure CPU code, as
  expected.
- **Deconvolution is identical on Mac** (12.95 vs 13.40) and 6× slower on inti
  (77.23 s). The multiscale minor loop with `-local-rms` is single-threaded and
  bound by scalar libm/rms work, where the M-series core beats the inti Xeon by
  roughly that factor. It does not use `-j`.
- inti's inversion is 2× the Mac CPU's despite 3× the threads: 24 older cores
  lose to 8 M-series cores on the ducc0 FFT/vector paths.

## Reference-table trap (fixed)

The first inti run used a `taql ... GIVING` table, which is a *reference* to the
16 GB parent. Every read walked the parent's `table.dat`, so the run took
~17 min for 104 s of actual imaging. `bench/make_4slot_ms.py` now materialises a
standalone copy (127 s, 775 MB); the same job runs in 108 s.

## Equivalence

Restored-image photometry agrees across all three runs to ~1e-3
(646.150 / 366.744 / 233.38 / 208.06 / 191.18 Jy, identical pixel positions).
The residual 0.57% row-count difference comes from a slightly different
time-edge in the two cuts.
