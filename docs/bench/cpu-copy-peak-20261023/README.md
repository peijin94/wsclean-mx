# CPU copy/masked-peak evidence

Main report: [CPU copy removal and masked peak](../../cpu-copy-and-masked-peak-2026-10-23.md).

- `results.json`: all 17 campaign receipts (four warmups, 13 measured), bound
  six-product T0 gates, per-run wall/stage/RSS/instruction/cycle metrics and host
  conditions, paired ratios, mode assessments, micro samples and provenance.
- `default-confirmation.json`: two post-commit rebuilt-default runs and their
  twelve bitwise product checks, with final binary/source identities.
- `verification.json`: actual test counts, input protection and raw-log hashes.
- `reviews.json`: approved source/report reviews, retained rejected report review,
  four cleanup findings, and superseded provider-routing failure receipts.
- `patch-replay.json`: all four isolated-index tree comparisons and 77 patch hashes.
- `performance.png`: every measured sample; warmups/default confirmations excluded.
- `masked-microbenchmark.png`: synthetic single-call measurements, not whole-image speedup.
- `image-consistency.png`: full-resolution checked differences; restored images use p99.

Re-render from the committed compact evidence and retained local FITS products:

```sh
.venv/bin/python docs/bench/cpu-copy-peak-20261023/plot_results.py
```

The image paths and hashes are in `results.json`; missing or changed products fail
rather than generating substitutes. `summarize.py` is the tracked one-shot
aggregation entry point. It needs the raw campaign under
`bench/out/cpu-next-20261023-1106/` and deliberately refuses existing summary/mode
outputs; it is not a command to overwrite the retained experiment.

`report_validation.py` contains report-specific fail-closed contracts. The
portable tests import only tracked code and create small synthetic fixtures:

```sh
.venv/bin/python -m unittest discover -s tests -p test_cpu_copy_peak_report.py -v
.venv/bin/python -O -m unittest discover -s tests -p test_cpu_copy_peak_report.py -v
```

Limits: the 3K wall estimate is range-limited, 4K has one A/A sample, RSS reduction
is not established, four native tests remain skipped, and older legacy-reference
failures are not waived. No Metal hardware acceptance or new release is claimed.
