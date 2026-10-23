# Quick CPU thread sweep - 20k override

- Fixed workload: protected real 15-integration MS, 3072 square / 2.7 arcmin,
  current CPU-only `mx` binary, otherwise the existing exo-pipe-style settings.
- User-requested explicit override: `-niter 20000` for this test only. The
  repository's deep benchmark default stays 150000.
- One excluded j8 warmup; measured order j8/j4/j12/j16, then j16/j12/j4/j8.
  Two repeats per setting reduce first/last order effects without a long sweep.
- No sampling profiler, GPU monitor, builds, or heavy tests during the batch.
  Before/after load, swap and thermal status are captured for every run.
- Average occupied cores = (user CPU seconds + system CPU seconds) / wall seconds,
  from the actual WSClean `/usr/bin/time` receipt. Divide by the live logical CPU
  count (8 on this host) for a whole-machine CPU-time percentage. This is not a
  frequency/IPC-weighted measure of compute capacity or an instantaneous peak.
- Compare all six products: T0 between same-j repeats; strict T2 for each j4,
  j12 and j16 run against the same-repeat j8 baseline. Keep every failure.
- Verify equal completed iterations and major cycles before interpreting timings.
- Check protected-input hashes/modes and executable hash before/after. Fresh
  output names only; 300-second per-run deadline with normal runner cleanup.
- This is a short workload-specific diagnostic, not a new default, a full-depth
  performance guarantee, or permission to publish another issue update.
