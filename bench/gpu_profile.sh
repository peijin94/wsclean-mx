#!/bin/bash
# Detailed GPU-vs-CPU inversion benchmark on the LWA 4-slot MS.
# Runs N GPU passes (stage timing) + 1 CPU pass, prints a per-element table.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BINARY="$(python3 "$ROOT/scripts/wsclean_binary.py" --build "$ROOT/build-mx-metal")" || exit 2
N=${1:-3}
MS=/tmp/lwa-4slot.ms
ARGS="-j 8 -size 1024 1024 -scale 10amin -weight briggs 0 -niter 0 -pol I -horizon-mask 10deg"
OUT=/tmp/gpubench
rm -rf $OUT; mkdir -p $OUT

echo "=== CPU reference (1x) ==="
/usr/bin/time -l "$BINARY" $ARGS -name $OUT/cpu $MS > $OUT/cpu.log 2>&1
grep -E "Inversion" $OUT/cpu.log | head -1
grep -E "maximum resident" $OUT/cpu.log | head -1

echo "=== GPU passes (${N}x) ==="
for i in $(seq 1 $N); do
  MX_METAL_DEBUG_TIMING=1 /usr/bin/time -l "$BINARY" -mgpu $ARGS -name $OUT/gpu$i $MS > $OUT/gpu$i.log 2>&1
  echo "--- pass $i ---"
  grep -E "Inversion" $OUT/gpu$i.log | head -1
done

echo ""
echo "=== stage means across GPU passes (ms) ==="
.venv/bin/python - "$OUT" "$N" <<'EOF'
import re, sys, glob
out, n = sys.argv[1], int(sys.argv[2])
stages = {}
for i in range(1, n+1):
    for line in open(f"{out}/gpu{i}.log"):
        m = re.search(r"chunk phase (\S+) ([\d.]+)ms", line)
        if m:
            stages.setdefault("phase:"+m.group(1), []).append(float(m.group(2)))
        m = re.search(r"batch host prep=([\d.]+)ms encode=([\d.]+)ms gpu_exec=([\d.]+)ms", line)
        if m:
            stages.setdefault("batch:prep", []).append(float(m.group(1)))
            stages.setdefault("batch:encode", []).append(float(m.group(2)))
            stages.setdefault("batch:gpu_exec", []).append(float(m.group(3)))
        m = re.search(r"batched \d+ planes gpu_total=([\d.]+)ms wall=([\d.]+)ms host=([\d.]+)ms", line)
        if m:
            stages.setdefault("batched:gpu_total", []).append(float(m.group(1)))
            stages.setdefault("batched:wall", []).append(float(m.group(2)))
            stages.setdefault("batched:host", []).append(float(m.group(3)))
        m = re.search(r"plane \d+ roll_fft=([\d.]+)ms", line)
        if m:
            stages.setdefault("roll_fft", []).append(float(m.group(1)))
for k in sorted(stages):
    v = stages[k]
    print(f"{k:28s} n={len(v):4d} mean={sum(v)/len(v):9.1f} min={min(v):9.1f} max={max(v):9.1f}")
EOF
echo ""
echo "=== peak RSS ==="
grep -h "maximum resident" $OUT/gpu*.log $OUT/cpu.log
