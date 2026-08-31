from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import build_test_pack as btp
import make_test_file as mtf
import plan_boundary as pb
import record_result as rr


class CanaryTests(unittest.TestCase):
    def test_canaries_are_not_derived_from_run_id(self):
        # Reusing the same visible run id must not reproduce secret canaries.
        a = mtf.run("txt", 8192, pages=10, run_id="ABCDEF")
        b = mtf.run("txt", 8192, pages=10, run_id="ABCDEF")
        ta = [x["token"] for x in a["canaries"]]
        tb = [x["token"] for x in b["canaries"]]
        self.assertNotEqual(ta, tb)
        self.assertTrue(all("ABCDEF" not in token for token in ta + tb))

    def test_exact_size_pdf(self):
        entry = mtf.run("pdf", 128 * 1024, pages=10, run_id="ABCDEF")
        self.assertTrue(entry["exactSize"])
        self.assertEqual(entry["actualBytes"], 128 * 1024)


class PackIsolationTests(unittest.TestCase):
    def test_page_sweep_holds_bytes_constant(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("pages", td, "pdf", pages_list=[10, 25, 50])
            sizes = {a["actualBytes"] for a in manifest["artefacts"]}
            metrics = {a["metric"]["value"] for a in manifest["artefacts"]}
            self.assertEqual(len(sizes), 1)
            self.assertEqual(metrics, {10, 25, 50})

    def test_count_scenarios_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("count", td, "txt", fixed_size=4096, counts=[1, 3])
            self.assertEqual([s["metric"]["value"] for s in manifest["scenarios"]], [1, 3])
            self.assertEqual([len(s["files"]) for s in manifest["scenarios"]], [1, 3])


class EvidenceTests(unittest.TestCase):
    def test_canary_miss_does_not_claim_parsing_failure(self):
        stages = {"coverage": "fail"}
        outcome, hint = rr.derive_outcome(stages, coverage_observed=True)
        self.assertEqual(outcome, "fail")
        self.assertEqual(hint, "coverage")

    def test_generic_page_boundary_planner(self):
        ledger = rr.new_ledger("page test", "direct-upload", "page-count", "pages")
        for value, outcome in [(100, "pass"), (200, "pass"), (300, "fail"), (300, "fail")]:
            rr.record(
                ledger, f"case-{value}",
                {"name": "page-count", "value": value, "unit": "pages"},
                {}, outcome_override=outcome,
                failure_stage="coverage" if outcome == "fail" else "none",
            )
        result = pb.plan(ledger, tolerance=1, min_trials=2)
        self.assertEqual(result["status"], "bisect")
        self.assertEqual(result["nextValue"], 250)

    def test_planner_does_not_auto_expand_unbounded_range(self):
        ledger = rr.new_ledger("runtime", "runtime", "duration", "milliseconds")
        rr.record(ledger, "a", {"name": "duration", "value": 1000, "unit": "milliseconds"}, {}, outcome_override="pass")
        result = pb.plan(ledger)
        self.assertEqual(result["status"], "no-upper-bound")
        self.assertIsNone(result["nextValue"])


if __name__ == "__main__":
    unittest.main()
