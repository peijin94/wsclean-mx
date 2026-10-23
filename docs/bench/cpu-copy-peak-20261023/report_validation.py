"""Evidence contracts for this one CPU report (no benchmark execution)."""

PRODUCTS = {f"img-{name}.fits" for name in
            ("dirty", "horizon-mask", "image", "model", "psf", "residual")}
VARIANTS = {"baseline": "cpu-next-base-20261023",
            "candidate": "cpu-next-candidate-20261023", "aa": "cpu-next-aa-20261023"}


def run_path(run):
    return f"bench/out/{run['tag']}/{run['variant']}"


def validate_gates(runs, gates):
    """Return gates indexed by exact run label, after binding their evidence."""
    if not isinstance(gates, list) or len(gates) != len(runs):
        raise ValueError("Incomplete numerical gates")
    by_tag = {run["tag"]: run for run in runs}
    checked = {}
    for gate in gates:
        if not isinstance(gate, dict):
            raise ValueError("Malformed numerical gate")
        label = gate.get("label")
        if not isinstance(label, str) or label not in by_tag or label in checked:
            raise ValueError("Duplicate or unrelated numerical gate")
        run = by_tag[label]
        reference = f"bench/out/cpu-next-profile-20261023-{run['size']}/{VARIANTS['baseline']}"
        if (gate.get("passed") is not True or gate.get("expected") != "T0"
                or gate.get("left") != reference or gate.get("right") != run_path(run)):
            raise ValueError(f"{label}: failed gate or wrong tier/directory identity")
        products = gate.get("products")
        if (not isinstance(products, list) or len(products) != 6
                or any(not isinstance(p, dict) or not isinstance(p.get("name"), str)
                       for p in products)
                or {p["name"] for p in products} != PRODUCTS):
            raise ValueError(f"{label}: expected six distinct named products")
        for product in products:
            if (product.get("T0") is not True or product.get("bitwise") is not True
                    or "error" in product or type(product.get("nan_mismatch")) is not int
                    or product["nan_mismatch"] != 0 or type(product.get("n_diff")) is not int
                    or product["n_diff"] != 0 or type(product.get("max_abs")) not in (int, float)
                    or product["max_abs"] != 0):
                raise ValueError(f"{label}: inconsistent T0 product evidence")
        checked[label] = gate
    return checked


def validate_runs(runs, *, compact=False):
    expected = {(s, 0, r, "preflight") for s in (3072, 4096)
                for r in ("baseline", "candidate")}
    expected |= {(s, n, r, "timing") for s, ns in ((3072, (1, 2, 3)), (4096, (1, 2)))
                 for n in ns for r in ("baseline", "candidate")}
    expected |= {(3072, n, "aa", "timing") for n in (1, 2)} | {(4096, 1, "aa", "timing")}
    if not isinstance(runs, list) or len(runs) != len(expected):
        raise ValueError("Incomplete measured inventory")
    seen = set()
    for run in runs:
        if (not isinstance(run, dict)
                or any(type(run.get(k)) is not int for k in ("size", "repeat", "threads", "niter"))
                or any(not isinstance(run.get(k), str) for k in ("role", "phase"))):
            raise ValueError("Malformed run identity")
        identity = (run["size"], run["repeat"], run["role"], run["phase"])
        if identity not in expected or identity in seen:
            raise ValueError("Duplicate or unexpected run identity")
        seen.add(identity)
        size, repeat, role, phase = identity
        tag = f"cpu-next-v1-20261023-{phase}-{size}-r{repeat}-{role}"
        if (run.get("tag") != tag or run.get("variant") != VARIANTS[role]
                or run["threads"] != 8 or run["niter"] != 150000):
            raise ValueError("Run label/variant/configuration mismatch")
        flags = dict(mode="cpu", profile=False, monitor=False, sample=False, common=False,
                     warmup=phase == "preflight")
        for key, value in flags.items():
            if (not compact or key in run) and (type(run.get(key)) is not type(value) or run[key] != value):
                raise ValueError("Run mode/measurement configuration mismatch")
        if compact and run.get("path") != run_path(run):
            raise ValueError("Run output directory identity mismatch")


def validate_report(data):
    """Validate compact evidence and return the gates for each figure pair."""
    configuration = dict(niter_cap=150000, threads=8, cpu_only=True, memory_percent=40,
                         all_products=sorted(PRODUCTS))
    if (type(data.get("schema")) is not int or data["schema"] != 1
            or not isinstance(data.get("configuration"), dict)
            or any(type(data["configuration"].get(k)) is not type(v)
                   or data["configuration"][k] != v for k, v in configuration.items())):
        raise ValueError("Report configuration mismatch")
    validate_micro(data.get("micro"))
    runs = data.get("runs")
    validate_runs(runs, compact=True)
    gates = validate_gates(runs, data.get("gates"))
    figures = data.get("figure_inputs")
    if not isinstance(figures, dict) or set(figures) != {"3072", "4096"}:
        raise ValueError("Missing figure evidence")
    figure_gates = {}
    for size in (3072, 4096):
        pair = figures[str(size)]
        if not isinstance(pair, dict) or set(pair) != {"baseline", "candidate"}:
            raise ValueError("Missing figure pair")
        figure_gates[str(size)] = {}
        for role in ("baseline", "candidate"):
            run = next(r for r in runs if r["size"] == size and r["repeat"] == 1 and r["role"] == role)
            item = pair[role]
            if not isinstance(item, dict) or item.get("path") != run_path(run) + "/img-image.fits":
                raise ValueError("Figure input does not match gated run")
            figure_gates[str(size)][role] = gates[run["tag"]]
    return figure_gates


def validate_completion(log, work):
    """Bind the last printed iteration to the receipt and completed components."""
    import re

    termination = "Cleaning finished because the final threshold was reached."
    iterations = list(re.finditer(r"\bIteration (\d+),", log))
    major = list(re.finditer(r"\b(\d+) major iterations were performed\.", log))
    reasons = list(re.finditer(r"Cleaning finished[^\n]+", log))
    summaries = list(re.finditer(r"Multi-scale cleaning summary:", log))
    totals = list(re.finditer(r"^Total: (\d+) components\b", log, re.M))
    scales = re.findall(r"^- Scale (\d+) px, nr of components cleaned: (\d+)\b", log, re.M)
    if (not iterations or len(major) != 1 or not reasons
            or reasons[-1].group() != termination
            or len(summaries) != 1 or len(totals) != 1
            or not scales or len({scale for scale, count in scales}) != len(scales)):
        raise ValueError("Missing/duplicate completed-work metadata")
    # Earlier cycles can reach a threshold before more iterations are printed.
    # Only one termination may follow the last iteration, before global metadata.
    if (not (iterations[-1].end() < reasons[-1].start() < major[0].start()
             < summaries[0].start() < totals[0].start())
            or any(reason.start() > iterations[-1].end() for reason in reasons[:-1])):
        raise ValueError("Out-of-order/duplicate final completion metadata")
    final, cycles, total = (int(iterations[-1].group(1)), int(major[0].group(1)),
                            int(totals[0].group(1)))
    counts = [int(count) for scale, count in scales]
    if (not isinstance(work, dict) or type(work.get("final_iteration")) is not int
            or type(work.get("major_cycles")) is not int
            or final <= 0 or final > 150000 or cycles <= 0
            or final != work["final_iteration"] or cycles != work["major_cycles"]
            or work.get("termination") != termination or final != total or total != sum(counts)):
        raise ValueError("Inconsistent last iteration/receipt/component completion")
    return dict(component_total=total, components_per_scale=counts)


def validate_micro(rows):
    import math
    import statistics

    expected = {(s, stride, negative) for s in (3072, 4096)
                for stride in (1, 3, 16) for negative in (False, True)}
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("Incomplete masked microbenchmark")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("size")) is not int
                or type(row.get("mask_stride")) is not int
                or type(row.get("allow_negative")) is not bool):
            raise ValueError("Malformed microbenchmark setting")
        identity = (row["size"], row["mask_stride"], row["allow_negative"])
        if identity not in expected or identity in seen:
            raise ValueError("Duplicate or unexpected microbenchmark setting")
        seen.add(identity)
        samples = row.get("samples_ms")
        if not isinstance(samples, dict) or set(samples) != {"before", "final"}:
            raise ValueError("Missing microbenchmark implementations")
        medians = {}
        for role, values in samples.items():
            if (not isinstance(values, list) or len(values) != 8
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values)):
                raise ValueError("Expected eight finite positive samples per implementation")
            medians[role] = statistics.median(values)
        aggregates = dict(baseline_ms=medians["before"], candidate_ms=medians["final"],
                          speedup=medians["before"] / medians["final"])
        for key, computed in aggregates.items():
            stored = row.get(key)
            if (type(stored) not in (int, float) or not math.isfinite(stored) or stored <= 0
                    or stored != computed):
                raise ValueError("Stored microbenchmark median/speedup disagrees with samples")


def validate_manifests(root, input_before, input_after, binaries_before, binaries_after, provenance):
    if not isinstance(input_before, dict) or not input_before or input_before != input_after:
        raise ValueError("Input mutation or missing manifest")
    if not isinstance(binaries_before, dict) or binaries_before != binaries_after:
        raise ValueError("Snapshot/dependency mutation or missing manifest")
    snapshot = provenance.get("snapshot") if isinstance(provenance, dict) else None
    if not isinstance(snapshot, dict) or set(snapshot) != {"wsclean", "libschaapthreading.dylib"}:
        raise ValueError("Missing candidate snapshot provenance")
    for name, value in snapshot.items():
        path = str(root / "bench/bin" / VARIANTS["candidate"] / name)
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
                or binaries_before.get(path) != value):
            raise ValueError("Candidate snapshot does not match reviewed provenance")
