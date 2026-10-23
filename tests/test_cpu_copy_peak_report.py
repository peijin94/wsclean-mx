"""Small synthetic evidence fixtures; never read or render campaign products."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/bench/cpu-copy-peak-20261023"
SUMMARY = REPORT / "summarize.py"
PRODUCTS = [f"img-{name}.fits" for name in
            ("dirty", "horizon-mask", "image", "model", "psf", "residual")]
VARIANTS = {"baseline": "cpu-next-base-20261023",
            "candidate": "cpu-next-candidate-20261023", "aa": "cpu-next-aa-20261023"}
TERMINATION = "Cleaning finished because the final threshold was reached."
LOG = ("Iteration 2, scale 0 px : 1 Jy\nIteration 5, scale 9 px : 1 Jy\n"
       + TERMINATION + "\n2 major iterations were performed.\n"
       "Multi-scale cleaning summary:\n"
       "- Scale 0 px, nr of components cleaned: 2 (1 Jy)\n"
       "- Scale 9 px, nr of components cleaned: 3 (1 Jy)\n"
       "Total: 5 components (2 Jy)\n"
       "Inversion: 00:00:01, prediction: 00:00:01, deconvolution: 00:00:01\n")


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class CompletionValidationTests(unittest.TestCase):
    def test_accepts_threshold_messages_from_earlier_major_cycles(self):
        validation = module("copy_peak_validation", REPORT / "report_validation.py")
        for earlier_cycles in (1, 3):
            with self.subTest(earlier_cycles=earlier_cycles):
                earlier = "".join(
                    f"Iteration {n}, scale 0 px : 1 Jy\n{TERMINATION}\n"
                    for n in range(1, earlier_cycles + 1))
                final = LOG[LOG.index("Iteration 5,"):].replace(
                    "2 major iterations", f"{earlier_cycles + 1} major iterations")
                work = dict(final_iteration=5, major_cycles=earlier_cycles + 1,
                            termination=TERMINATION)
                self.assertEqual(
                    dict(component_total=5, components_per_scale=[2, 3]),
                    validation.validate_completion(earlier + final, work))

    def test_rejects_misplaced_or_duplicate_final_completion(self):
        validation = module("copy_peak_validation", REPORT / "report_validation.py")
        work = dict(final_iteration=5, major_cycles=2, termination=TERMINATION)
        major = "2 major iterations were performed.\n"
        summary = "Multi-scale cleaning summary:\n"
        total = "Total: 5 components (2 Jy)\n"
        invalid = {
            "duplicate_final_termination": LOG + TERMINATION + "\n",
            "duplicate_before_major": LOG.replace(TERMINATION, (TERMINATION + "\n") * 2),
            "termination_before_last_iteration": LOG.replace(TERMINATION + "\n", "")
                .replace("Iteration 5,", TERMINATION + "\nIteration 5,"),
            "major_before_termination": LOG.replace(major, "")
                .replace(TERMINATION, major + TERMINATION),
            "summary_before_major": LOG.replace(summary, "").replace(major, summary + major),
            "total_before_summary": LOG.replace(total, "").replace(summary, total + summary),
        }
        for name, log in invalid.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                validation.validate_completion(log, work)


def fixture_runs():
    identities = [(s, 0, r, "preflight") for s in (3072, 4096)
                  for r in ("baseline", "candidate")]
    identities += [(s, n, r, "timing") for s, repeats in ((3072, 3), (4096, 2))
                   for n in range(1, repeats + 1) for r in ("baseline", "candidate")]
    identities += [(3072, n, "aa", "timing") for n in (1, 2)] + [(4096, 1, "aa", "timing")]
    return [dict(tag=f"cpu-next-v1-20261023-{phase}-{size}-r{repeat}-{role}",
                 variant=VARIANTS[role], size=size, repeat=repeat, role=role, phase=phase,
                 mode="cpu", threads=8, niter=150000, profile=False, monitor=False,
                 sample=False, warmup=phase == "preflight", common=False)
            for size, repeat, role, phase in identities]


def fixture_gate(run):
    return dict(label=run["tag"], expected="T0", passed=True,
                left=f"bench/out/cpu-next-profile-20261023-{run['size']}/{VARIANTS['baseline']}",
                right=f"bench/out/{run['tag']}/{run['variant']}",
                products=[dict(name=name, T0=True, T2=True, bitwise=True, nan_mismatch=0,
                               n_diff=0, max_abs=0.0) for name in PRODUCTS])


def fixture_micro():
    return [dict(size=size, mask_stride=stride, allow_negative=negative,
                 samples_ms=dict(before=[float(n) for n in range(1, 9)],
                                 final=[n / 2 for n in range(1, 9)]),
                 baseline_ms=4.5, candidate_ms=2.25, speedup=2.0)
            for size in (3072, 4096) for stride in (1, 3, 16) for negative in (False, True)]


def micro_mutations():
    return {
        "duplicate_setting": lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
        "unexpected_setting": lambda rows: rows[0].update(mask_stride=2),
        "nonboolean_setting": lambda rows: rows[0].update(allow_negative=0),
        "missing_sample_before": lambda rows: rows[0]["samples_ms"]["before"].pop(),
        "missing_sample_final": lambda rows: rows[0]["samples_ms"]["final"].pop(),
        "infinite_before": lambda rows: rows[0]["samples_ms"]["before"].__setitem__(0, float("inf")),
        "nan_final": lambda rows: rows[0]["samples_ms"]["final"].__setitem__(0, float("nan")),
        "zero_before": lambda rows: rows[0]["samples_ms"]["before"].__setitem__(0, 0),
        "negative_final": lambda rows: rows[0]["samples_ms"]["final"].__setitem__(0, -1),
        "boolean_sample": lambda rows: rows[0]["samples_ms"]["final"].__setitem__(0, True),
        "baseline_median": lambda rows: rows[0].update(baseline_ms=4.0),
        "candidate_median": lambda rows: rows[0].update(candidate_ms=2.0),
        "speedup": lambda rows: rows[0].update(speedup=1.0),
    }


class AcceptedForClassification(AssertionError):
    """Stop after evidence validation, before executing the classifier."""


class SummaryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.art = self.root / "artifact"
        self.art.mkdir()
        self.summary = module("copy_peak_summary", SUMMARY)
        self.runs = fixture_runs()
        self.gates = [fixture_gate(r) for r in self.runs]
        self.write("masked-final-micro-summary.json", fixture_micro())
        self.write("performance-input-before.json", {"synthetic-input": "unchanged"})
        self.write("performance-input-after.json", {"synthetic-input": "unchanged"})
        self.snapshot = {"wsclean": "a" * 64, "libschaapthreading.dylib": "b" * 64}
        self.binaries = {str(self.root / "bench/bin" / VARIANTS["candidate"] / name): value
                         for name, value in self.snapshot.items()}
        self.write("performance-binaries-before.json", self.binaries)
        self.write("performance-binaries-after.json", self.binaries)
        self.write("candidate-provenance.json", {"snapshot": self.snapshot})
        for run in self.runs:
            folder = self.root / "bench/out" / run['tag'] / run['variant']
            folder.mkdir(parents=True)
            for name in PRODUCTS:
                (folder / name).write_bytes(b"synthetic inventory only")
            (folder / "wsclean.log").write_text(LOG)
            (folder / "time.txt").write_text(
                "real 5\nuser 8\nsys 1\n123 maximum resident set size\n"
                "100 instructions retired\n200 cycles elapsed\n")
            run.update(exit=0, work=dict(final_iteration=5, major_cycles=2,
                                        termination=TERMINATION), before={}, after={})
        self.write("performance-plan.json", [{k: v for k, v in r.items()
                                             if k not in ('exit', 'work', 'before', 'after')}
                                            for r in self.runs])
        self.write("performance-runs.json", self.runs)
        self.write("performance-gates.json", self.gates)
        (self.root / "bench/ab.sh").write_text(
            'python3 - "$results" "$mode_file" <<\'EOF\'\npass\nEOF\n')

    def write(self, name, data):
        (self.art / name).write_text(json.dumps(data))

    def run_summary(self):
        import bench.analyze_cpu_campaign as analyzer
        with patch.object(self.summary, "ROOT", self.root), \
             patch.object(self.summary, "ART", self.art), \
             patch.object(self.summary, "OUT", self.root / "report"), \
             patch.object(analyzer, "ROOT", self.root), \
             patch.object(self.summary.subprocess, "run", side_effect=AcceptedForClassification):
            self.summary.main()

    def test_valid_summary_evidence_reaches_classifier(self):
        with self.assertRaises(AcceptedForClassification):
            self.run_summary()

    def test_summary_binds_gate_to_run_tier_paths_and_six_distinct_products(self):
        mutations = {
            "output": lambda g: g.update(right=self.gates[1]["right"]),
            "reference": lambda g: g.update(left="bench/out/unrelated/base"),
            "tier": lambda g: g.update(expected="T2"),
            "truthy_pass": lambda g: g.update(passed=1),
            "duplicate_product": lambda g: g["products"][0].update(name=PRODUCTS[1]),
            "unexpected_product": lambda g: g["products"][0].update(name="img-other.fits"),
            "truthy_T0": lambda g: g["products"][0].update(T0="true"),
            "false_T0": lambda g: g["products"][0].update(T0=False),
            "contradictory_bitwise": lambda g: g["products"][0].update(bitwise=False),
            "error": lambda g: g["products"][0].update(error="infinite pixels"),
            "nonzero_diff": lambda g: g["products"][0].update(n_diff=1),
            "nonzero_max_abs": lambda g: g["products"][0].update(max_abs=1e-20),
            "nonfinite_max_abs": lambda g: g["products"][0].update(max_abs=float("inf")),
        }
        import copy
        original = copy.deepcopy(self.gates)
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.gates = copy.deepcopy(original)
                mutate(self.gates[0])
                self.write("performance-gates.json", self.gates)
                # Any previous accepted case leaves classifier outputs; remove only
                # these temporary fixture files before trying the next mutation.
                for path in self.art.glob("performance-3072-*"):
                    path.unlink()
                with self.assertRaises(ValueError):
                    self.run_summary()

    def test_summary_cross_checks_last_iteration_and_completion_metadata(self):
        import re
        changes = {
            "last_not_receipt_max": lambda text: text.replace("Iteration 2,", "Iteration 5,")
                .replace("Iteration 5, scale 9", "Iteration 4, scale 9"),
            "missing_iterations": lambda text: re.sub(r"Iteration [^\n]+\n", "", text),
            "missing_major": lambda text: text.replace("2 major iterations were performed.\n", ""),
            "duplicate_major": lambda text: text + "2 major iterations were performed.\n",
            "major_receipt_mismatch": lambda text: text.replace("2 major iterations", "3 major iterations"),
            "missing_termination": lambda text: text.replace(TERMINATION + "\n", ""),
            "duplicate_final_termination": lambda text: text + TERMINATION + "\n",
            "wrong_termination": lambda text: text.replace(TERMINATION, "Cleaning finished at iteration cap."),
            "missing_summary": lambda text: text.replace("Multi-scale cleaning summary:\n", ""),
            "duplicate_summary": lambda text: text + "Multi-scale cleaning summary:\n",
            "duplicate_scale_identity": lambda text: text.replace("Scale 9 px", "Scale 0 px"),
            "duplicate_total": lambda text: text + "Total: 5 components (2 Jy)\n",
            "inconsistent_scale_sum": lambda text: text.replace("cleaned: 3", "cleaned: 4"),
        }
        folder = self.root / "bench/out" / self.runs[0]["tag"] / self.runs[0]["variant"]
        for name, change in changes.items():
            with self.subTest(name=name):
                (folder / "wsclean.log").write_text(change(LOG))
                for path in self.art.glob("performance-3072-*"):
                    path.unlink()
                with self.assertRaises(ValueError):
                    self.run_summary()

    def test_summary_rejects_inconsistent_receipt_completion_fields(self):
        for key, value in (("major_cycles", 3), ("termination", "different reason"),
                           ("final_iteration", True)):
            with self.subTest(key=key):
                self.runs[0]["work"] = dict(final_iteration=5, major_cycles=2, termination=TERMINATION)
                self.runs[0]["work"][key] = value
                self.write("performance-runs.json", self.runs)
                for path in self.art.glob("performance-3072-*"):
                    path.unlink()
                with self.assertRaises(ValueError):
                    self.run_summary()

    def test_summary_rejects_invalid_micro_evidence_before_classifier(self):
        for name, mutate in micro_mutations().items():
            with self.subTest(name=name):
                rows = fixture_micro()
                mutate(rows)
                self.write("masked-final-micro-summary.json", rows)
                for path in self.art.glob("performance-3072-*"):
                    path.unlink()
                with self.assertRaises(ValueError):
                    self.run_summary()

    def test_summary_binds_unchanged_snapshots_to_candidate_provenance(self):
        for name in ("wrong_snapshot", "missing_snapshot", "missing_manifest_entry", "changed_after"):
            with self.subTest(name=name):
                snapshot = dict(self.snapshot)
                before = dict(self.binaries)
                after = dict(self.binaries)
                key = next(iter(before))
                if name == "wrong_snapshot":
                    snapshot["wsclean"] = "c" * 64
                elif name == "missing_snapshot":
                    snapshot.pop("wsclean")
                elif name == "missing_manifest_entry":
                    before.pop(key)
                    after.pop(key)
                else:
                    after[key] = "c" * 64
                self.write("candidate-provenance.json", {"snapshot": snapshot})
                self.write("performance-binaries-before.json", before)
                self.write("performance-binaries-after.json", after)
                for path in self.art.glob("performance-3072-*"):
                    path.unlink()
                with self.assertRaises(ValueError):
                    self.run_summary()


class AcceptedForRendering(AssertionError):
    """Stop at the first figure; validation tests create no large figures."""


class PlotValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plot = module("copy_peak_plot", REPORT / "plot_results.py")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.here = Path(self.temp.name)
        runs = fixture_runs()
        for r in runs:
            r["path"] = f"bench/out/{r['tag']}/{r['variant']}"
            r["timing"] = {key: 1.0 for key in ("wall_s", "deconvolution_s", "inversion_s",
                             "prediction_s", "rss_bytes", "instructions", "cycles")}
        self.data = dict(schema=1, runs=runs, gates=[fixture_gate(r) for r in runs],
                         configuration=dict(niter_cap=150000, threads=8, cpu_only=True,
                                            memory_percent=40, all_products=sorted(PRODUCTS)))
        self.data["micro"] = fixture_micro()
        self.data["figure_inputs"] = {str(size): {role: dict(
            path=next(r["path"] for r in runs if r["size"] == size and r["repeat"] == 1
                      and r["role"] == role) + "/img-image.fits", sha256="a"*64)
            for role in ("baseline", "candidate")} for size in (3072, 4096)}
        self.data["modes"] = {str(size): dict(status="synthetic mode", text=
            "synthetic mode\nresolution: a single repeat gives no repeatability estimate\n")
            for size in (3072, 4096)}

    def run_plot(self):
        (self.here / "results.json").write_text(json.dumps(self.data))
        with patch.object(self.plot, "HERE", self.here), \
             patch.object(self.plot.plt, "subplots", side_effect=AcceptedForRendering):
            self.plot.main()

    def test_valid_plot_evidence_reaches_renderer(self):
        with self.assertRaises(AcceptedForRendering):
            self.run_plot()

    def test_valid_compact_plot_evidence_reaches_renderer(self):
        for run in self.data["runs"]:
            for key in ("mode", "profile", "monitor", "sample", "common", "warmup"):
                run.pop(key)
        with self.assertRaises(AcceptedForRendering):
            self.run_plot()

    def test_plot_rejects_run_identity_and_configuration_mismatches(self):
        mutations = {
            "duplicate": lambda d: d["runs"].__setitem__(6, copy.deepcopy(d["runs"][4])),
            "unexpected_tag": lambda d: d["runs"][0].update(tag="unrelated"),
            "variant": lambda d: d["runs"][0].update(variant=VARIANTS["candidate"]),
            "role": lambda d: d["runs"][0].update(role="aa"),
            "phase": lambda d: d["runs"][0].update(phase="warmup"),
            "repeat": lambda d: d["runs"][4].update(repeat=7),
            "threads": lambda d: d["runs"][4].update(threads=4),
            "niter": lambda d: d["runs"][4].update(niter=5000),
            "output_path": lambda d: d["runs"][4].update(path="bench/out/unrelated/base"),
            "global_threads": lambda d: d["configuration"].update(threads=4),
            "cpu_only": lambda d: d["configuration"].update(cpu_only=1),
            "memory": lambda d: d["configuration"].update(memory_percent=80),
            "all_products": lambda d: d["configuration"]["all_products"].__setitem__(0, PRODUCTS[1]),
        }
        original = copy.deepcopy(self.data)
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.data = copy.deepcopy(original)
                mutate(self.data)
                with self.assertRaises(ValueError):
                    self.run_plot()

    def test_plot_binds_gates_and_figure_inputs_to_runs(self):
        mutations = {
            "duplicate_gate": lambda d: d["gates"].__setitem__(1, copy.deepcopy(d["gates"][0])),
            "unrelated_gate": lambda d: d["gates"][0].update(label="unrelated"),
            "tier": lambda d: d["gates"][0].update(expected="T2"),
            "reference": lambda d: d["gates"][0].update(left=d["gates"][1]["right"]),
            "output": lambda d: d["gates"][0].update(right=d["gates"][1]["right"]),
            "pass_type": lambda d: d["gates"][0].update(passed="true"),
            "product_type": lambda d: d["gates"][0]["products"][0].update(T0=1),
            "nonzero_diff": lambda d: d["gates"][0]["products"][0].update(n_diff=1),
            "nonzero_max_abs": lambda d: d["gates"][0]["products"][0].update(max_abs=1e-20),
            "product_name": lambda d: d["gates"][0]["products"][0].update(name="img-other.fits"),
            "duplicate_product": lambda d: d["gates"][0]["products"][0].update(name=PRODUCTS[1]),
            "missing_product": lambda d: d["gates"][0]["products"].pop(),
            "figure_path": lambda d: d["figure_inputs"]["3072"]["candidate"].update(
                path=d["figure_inputs"]["3072"]["baseline"]["path"]),
        }
        original = copy.deepcopy(self.data)
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.data = copy.deepcopy(original)
                mutate(self.data)
                with self.assertRaises(ValueError):
                    self.run_plot()

    def test_plot_rejects_invalid_micro_evidence_before_rendering(self):
        for name, mutate in micro_mutations().items():
            with self.subTest(name=name):
                self.data["micro"] = fixture_micro()
                mutate(self.data["micro"])
                with self.assertRaises(ValueError):
                    self.run_plot()

    def test_performance_caption_keeps_resolution_and_single_sample_caveats(self):
        import numpy as np
        caveats = {str(size): f"resolution: {size} synthetic resolution caveat"
                   for size in (3072, 4096)}
        for size, caveat in caveats.items():
            self.data["modes"][size]["text"] = "synthetic mode\n" + caveat + "\n"
        (self.here / "results.json").write_text(json.dumps(self.data))
        figure = Mock()
        figure.savefig.side_effect = AcceptedForRendering
        axes = np.array([[Mock() for _ in range(3)] for _ in range(2)])
        with patch.object(self.plot, "HERE", self.here), \
             patch.object(self.plot.plt, "subplots", return_value=(figure, axes)), \
             self.assertRaises(AcceptedForRendering):
            self.plot.main()
        caption = figure.suptitle.call_args.args[0]
        for caveat in caveats.values():
            self.assertIn(caveat, caption)
        self.assertIn("4096 A/A: one sample", caption)


class ImageValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plot = module("copy_peak_image_plot", REPORT / "plot_results.py")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def load_pair(self, left, right, *, changed_hash=False):
        import numpy as np
        from astropy.io import fits
        data = {"figure_inputs": {"2": {}}}
        for role, image in (("baseline", left), ("candidate", right)):
            path = self.root / (role + ".fits")
            fits.writeto(path, np.array(image, dtype=np.float64), overwrite=True)
            data["figure_inputs"]["2"][role] = dict(path=path.name, sha256=self.plot.digest(path))
        if changed_hash:
            data["figure_inputs"]["2"]["candidate"]["sha256"] = "0"*64
        with patch.object(self.plot, "ROOT", self.root), \
             patch.object(self.plot.plt, "subplots", side_effect=AssertionError("Unexpected rendering")):
            return self.plot.load_image_pair(data, 2)

    def test_image_pair_rejects_infinity_in_either_image(self):
        import numpy as np
        for value in (np.inf, -np.inf):
            for side in ("both", "baseline", "candidate"):
                with self.subTest(value=value, side=side):
                    left = [[1, 2], [3, value if side != "candidate" else 4]]
                    right = [[1, 2], [3, value if side != "baseline" else 4]]
                    with self.assertRaisesRegex(ValueError, "[Ii]nfin"):
                        self.load_pair(left, right)

    def test_image_pair_requires_coverage_shape_nan_masks_and_exact_zero(self):
        import numpy as np
        ordinary = [[1, 2], [3, 4]]
        bad_pairs = [([[np.nan]*2]*2, [[np.nan]*2]*2),
                     (ordinary, [[1, 2, 3], [4, 5, 6]]),
                     ([[1, 2], [3, np.nan]], ordinary),
                     (ordinary, [[1, 2], [3, 4 + 1e-12]])]
        for left, right in bad_pairs:
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                self.load_pair(left, right)
        with self.assertRaisesRegex(ValueError, "Changed figure input"):
            self.load_pair(ordinary, ordinary, changed_hash=True)

    def test_matching_nans_and_finite_zeros_are_valid(self):
        import numpy as np
        images, difference = self.load_pair([[0, 2], [3, np.nan]], [[0, 2], [3, np.nan]])
        self.assertEqual((2, 2), images[0].shape)
        np.testing.assert_array_equal(difference[:1], [[0, 0]])
        self.assertTrue(np.isnan(difference[1, 1]))


if __name__ == "__main__":
    unittest.main()
