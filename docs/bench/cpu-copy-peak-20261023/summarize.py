"""Compact the completed campaign; do not run during timed imaging."""
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bench.analyze_cpu_campaign import validated_runs
sys.path.insert(0, str(ROOT / "docs/bench/cpu-copy-peak-20261023"))
from report_validation import (PRODUCTS, validate_gates, validate_runs, validate_completion,
                               validate_micro, validate_manifests)

ART = ROOT / "bench/out/cpu-next-20261023-1106"
OUT = ROOT / "docs/bench/cpu-copy-peak-20261023"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    plan = json.loads((ART / "performance-plan.json").read_text())
    runs = validated_runs(ART, "performance")
    gates = json.loads((ART / "performance-gates.json").read_text())
    if len(plan) != 17 or len(gates) != len(runs):
        raise ValueError("Incomplete campaign")
    validate_runs(runs)
    required_products = PRODUCTS
    validate_gates(runs, gates)
    for run in runs:
        folder = ROOT / "bench/out" / run["tag"] / run["variant"]
        if {p.name for p in folder.glob("*.fits")} != required_products:
            raise ValueError("Wrong product inventory")
        log = (folder / "wsclean.log").read_text()
        completion = validate_completion(log, run.get("work"))
        run["work"].update(completion)
        run["path"] = str(folder.relative_to(ROOT))
    micro = json.loads((ART / "masked-final-micro-summary.json").read_text())
    validate_micro(micro)
    candidate_provenance = json.loads((ART / "candidate-provenance.json").read_text())
    validate_manifests(ROOT,
        json.loads((ART / "performance-input-before.json").read_text()),
        json.loads((ART / "performance-input-after.json").read_text()),
        json.loads((ART / "performance-binaries-before.json").read_text()),
        json.loads((ART / "performance-binaries-after.json").read_text()), candidate_provenance)
    timed = [r for r in runs if r["phase"] == "timing"]
    if len(timed) != 13:
        raise ValueError("Wrong timing count")
    keyed = {(r["size"], r["repeat"], r["role"]): r for r in timed}
    if len(keyed) != len(timed):
        raise ValueError("Duplicated timing identity")
    statistics_rows = []
    for size in (3072, 4096):
        for role in ("baseline", "candidate", "aa"):
            samples = [r["timing"] for r in timed if r["size"] == size and r["role"] == role]
            statistics_rows.append({"size": size, "role": role, "n": len(samples),
                "metrics": {k: {"median": statistics.median(s[k] for s in samples),
                                  "min": min(s[k] for s in samples),
                                  "max": max(s[k] for s in samples)} for k in samples[0]}})
    pairs = []
    for (size, repeat, role), row in keyed.items():
        if role == "baseline":
            continue
        baseline = keyed[(size, repeat, "baseline")]
        pairs.append({"size": size, "repeat": repeat, "role": role,
                      "baseline": baseline["tag"], "candidate": row["tag"],
                      "ratios": {k: row["timing"][k] / baseline["timing"][k]
                                 for k in ("wall_s", "inversion_s", "prediction_s",
                                           "deconvolution_s", "rss_bytes", "instructions", "cycles")}})
    # Execute the existing tracked mode-assessment block, without rerunning the
    # imaging shell loop or duplicating its classification thresholds.
    source = (ROOT / "bench/ab.sh").read_text()
    marker = "python3 - \"$results\" \"$mode_file\" <<'EOF'\n"
    if source.count(marker) != 1:
        raise ValueError("Cannot identify existing mode classifier")
    classifier, end, remainder = source.split(marker, 1)[1].rpartition("\nEOF")
    if not end or remainder.strip():
        raise ValueError("Malformed mode-classifier block")
    modes = {}
    for size in (3072, 4096):
        tsv = ART / f"performance-{size}-ab.tsv"
        mode = ART / f"performance-{size}-ab.mode.txt"
        with tsv.open("x", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(["variant", "rep", "wall", "inversion", "prediction",
                             "deconvolution", "instructions_G", "cycles_G"])
            for run in timed:
                if run["size"] == size:
                    t = run["timing"]
                    writer.writerow([run["variant"], run["repeat"], t["wall_s"],
                                     t["inversion_s"], t["prediction_s"], t["deconvolution_s"],
                                     t["instructions"] / 1e9, t["cycles"] / 1e9])
        with (ART / f"performance-{size}-mode.log").open("x") as stream:
            subprocess.run([sys.executable, "-", str(tsv), str(mode)], input=classifier,
                           text=True, stdout=stream, stderr=subprocess.STDOUT, check=True)
        text = mode.read_text()
        modes[str(size)] = {"status": text.splitlines()[0], "text": text,
                            "classifier_source_sha256": digest(ROOT / "bench/ab.sh")}
    figures = {}
    for size in (3072, 4096):
        figures[str(size)] = {}
        for role in ("baseline", "candidate"):
            path = ROOT / keyed[(size, 1, role)]["path"] / "img-image.fits"
            figures[str(size)][role] = {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
    compact_runs = [{k: r[k] for k in ["tag", "variant", "size", "repeat", "role", "phase",
                                      "threads", "niter", "work", "timing", "path", "before", "after"]}
                    for r in runs]
    result = {"schema": 1, "configuration": {"niter_cap": 150000, "threads": 8,
                  "cpu_only": True, "memory_percent": 40, "all_products": sorted(required_products)},
              "runs": compact_runs, "statistics": statistics_rows, "pairs": pairs,
              "modes": modes, "gates": gates, "figure_inputs": figures,
              "micro": micro,
              "baseline_provenance": json.loads((ART / "provenance.json").read_text()),
              "candidate_provenance": candidate_provenance,
              "protected_input": {"unchanged": True, "manifest_sha256": digest(ART / "performance-input-before.json")}}
    with (OUT / "results.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"runs": len(runs), "gates": len(gates), "mode": modes,
                      "statistics": statistics_rows, "paired_ratios": pairs}, indent=2))


if __name__ == "__main__":
    main()
