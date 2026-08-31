from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import build_test_pack as btp
import generate_report as gr
import make_test_file as mtf
import metrics
import plan_boundary as pb
import record_result as rr


def ledger_with(documented, pairs, trials=1, unit="pages", **kw):
    """Build a ledger whose observations are (value, outcome) pairs."""
    led = rr.new_ledger("c", "direct-upload", "m", unit,
                        documented_value=documented, **kw)
    for value, outcome in pairs:
        for _ in range(trials):
            rr.record(led, f"case-{value}",
                      {"name": "m", "value": value, "unit": unit}, {},
                      outcome_override=outcome,
                      failure_stage="coverage" if outcome == "fail" else "none")
    return led


def verdict_for(documented, pairs, trials=1, unit="pages"):
    led = ledger_with(documented, pairs, trials, unit)
    return gr.reconcile(documented, gr._boundaries(led), unit)[0]


class CanaryTests(unittest.TestCase):
    def test_canaries_are_not_derived_from_run_id(self):
        # Reusing the same visible run id must not reproduce secret canaries.
        a = mtf.run("txt", 8192, pages=10, run_id="ABCDEF")
        b = mtf.run("txt", 8192, pages=10, run_id="ABCDEF")
        da = [x["tokenSha256"] for x in a["canaries"]]
        db = [x["tokenSha256"] for x in b["canaries"]]
        self.assertNotEqual(da, db)

    def test_exact_size_pdf(self):
        entry = mtf.run("pdf", 128 * 1024, pages=10, run_id="ABCDEF")
        self.assertTrue(entry["exactSize"])
        self.assertEqual(entry["actualBytes"], 128 * 1024)

    def test_manifest_never_carries_the_token(self):
        # Reading the manifest must not reveal an answer.
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("size", td, "txt", sizes=[16384])
            blob = json.dumps(manifest)
            self.assertNotIn("CANARY-", blob)
            for artefact in manifest["artefacts"]:
                for canary in artefact["canaries"]:
                    self.assertIn("tokenSha256", canary)
                    self.assertNotIn("token", canary)
                    self.assertEqual(len(canary["tokenSha256"]), 64)

    def test_claim_verification_is_digest_based(self):
        entry = mtf.run("txt", 8192, pages=4, run_id="ABCDEF")
        token = "CANARY-P0001-" + "A" * 24
        expected = [{"page": 1, "tokenSha256": mtf.canary_digest(token)}]

        coverage, detail = rr.verify_page_claims(expected, {1: token.lower()})
        self.assertEqual(coverage, "pass")
        self.assertTrue(detail[0]["found"])
        self.assertNotIn("expected", detail[0])

        coverage, detail = rr.verify_page_claims(expected, {1: "CANARY-P0001-" + "B" * 24})
        self.assertEqual(coverage, "fail")
        self.assertTrue(detail[0]["mismatch"])
        self.assertEqual(len(entry["canaries"]), 4)

    def test_legacy_plaintext_manifests_still_verify(self):
        token = "CANARY-P0001-" + "C" * 24
        coverage, _ = rr.verify_page_claims([{"page": 1, "token": token}], {1: token})
        self.assertEqual(coverage, "pass")


class PackIsolationTests(unittest.TestCase):
    def test_page_sweep_holds_bytes_constant(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("pages", td, "pdf", pages_list=[10, 25, 50])
            sizes = {a["actualBytes"] for a in manifest["artefacts"]}
            values = {a["metric"]["value"] for a in manifest["artefacts"]}
            self.assertEqual(len(sizes), 1)
            self.assertEqual(values, {10, 25, 50})

    def test_count_scenarios_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("count", td, "txt", fixed_size=4096, counts=[1, 3])
            self.assertEqual([s["metric"]["value"] for s in manifest["scenarios"]], [1, 3])
            self.assertEqual([len(s["files"]) for s in manifest["scenarios"]], [1, 3])

    def test_format_is_not_a_sweepable_metric(self):
        # Format has no ordering, so it cannot have a boundary. It must not be
        # offered as a mode that the numeric pipeline cannot complete.
        self.assertNotIn("formats", btp.MODES)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                btp.build("formats", td, "pdf", fixed_size=65536)

    def test_artefacts_are_isolated_in_an_upload_directory(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("size", td, "txt", sizes=[16384])
            for artefact in manifest["artefacts"]:
                self.assertTrue(os.path.isfile(os.path.join(td, btp.UPLOAD_DIR, artefact["file"])))

    def test_upload_instructions_require_one_artefact_per_turn(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("size", td, "txt", sizes=[16384, 32768])
            with open(btp.write_upload_instructions(manifest, td), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("one artefact per turn", text.lower())
            self.assertNotIn("as few turns as the channel permits", text)

    def test_count_instructions_require_a_fresh_conversation(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("count", td, "txt", fixed_size=4096, counts=[1, 2])
            with open(btp.write_upload_instructions(manifest, td), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("fresh conversation", text.lower())


class CapacityTests(unittest.TestCase):
    """A pack that cannot fit must be refused before any bytes are written."""

    def test_planned_bytes_is_known_before_building(self):
        self.assertEqual(btp.planned_bytes("size", sizes=[1024, 2048]), 3072)
        self.assertEqual(btp.planned_bytes("pages", pages_list=[1, 2, 3], fixed_size=1024), 3072)
        self.assertEqual(btp.planned_bytes("count", counts=[1, 3], fixed_size=1024), 4096)

    def test_oversized_pack_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                btp.build("size", td, "txt", sizes=[64 * 1024], max_total_bytes=1024)
            self.assertIn("max-total-bytes", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(td, btp.UPLOAD_DIR)))

    def test_insufficient_free_space_is_refused_with_a_way_forward(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError) as ctx:
                btp.check_capacity(td, 1024 ** 5)  # 1 PiB
            message = str(ctx.exception)
            self.assertIn("free", message)
            self.assertIn("one pack at a time", message)

    def test_space_check_can_be_skipped_deliberately(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = btp.build("size", td, "txt", sizes=[8192],
                                 max_total_bytes=1, skip_space_check=True)
            self.assertEqual(manifest["artefactCount"], 1)


class ArtefactStructureTests(unittest.TestCase):
    def test_every_format_produces_a_structurally_valid_file(self):
        with tempfile.TemporaryDirectory() as td:
            for fmt in mtf.FORMATS:
                path = os.path.join(td, f"probe.{fmt}")
                entry = mtf.run(fmt, 256 * 1024, pages=6, run_id="ABCDEF", out_path=path)
                self.assertTrue(entry["exactSize"], fmt)
                with open(path, "rb") as fh:
                    blob = fh.read()
                if fmt == "pdf":
                    self.assertTrue(blob.startswith(b"%PDF-"))
                    self.assertIn(b"%%EOF", blob)
                elif fmt == "txt":
                    self.assertIn(b"CANARY-", blob)
                else:
                    with zipfile.ZipFile(path) as z:
                        self.assertIsNone(z.testzip(), fmt)
                        self.assertIn("[Content_Types].xml", z.namelist())


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


class ReconciliationTests(unittest.TestCase):
    def test_documented_value_passing_alone_is_not_headroom(self):
        # Nothing above the documented value was tested, so no headroom exists.
        self.assertEqual(verdict_for(50, [(50, "pass")]), "inconclusive")

    def test_passing_below_documented_alone_is_not_a_restriction(self):
        # Nothing failed, so nothing shows the platform stops early.
        self.assertEqual(verdict_for(50, [(40, "pass")]), "inconclusive")

    def test_bracketing_the_documented_value_is_not_a_confirmed_match(self):
        # 40 passes and 60 fails: the boundary is in (40, 60); 50 is untested.
        self.assertEqual(verdict_for(50, [(40, "pass"), (60, "fail")]),
                         "consistent-with-guidance")

    def test_confirmed_match_requires_direct_repeated_evidence(self):
        self.assertEqual(verdict_for(50, [(50, "pass"), (51, "fail")], trials=2),
                         "confirmed-match")

    def test_confirmed_match_requires_more_than_one_trial(self):
        self.assertEqual(verdict_for(50, [(50, "pass"), (51, "fail")], trials=1),
                         "consistent-with-guidance")

    def test_headroom_requires_a_pass_strictly_above_documented(self):
        self.assertEqual(verdict_for(50, [(60, "pass")]), "observed-headroom")

    def test_restriction_requires_a_failure_at_or_below_documented(self):
        self.assertEqual(verdict_for(50, [(30, "pass"), (40, "fail")]),
                         "more-restrictive-than-documented")
        self.assertEqual(verdict_for(50, [(40, "pass"), (50, "fail")]),
                         "more-restrictive-than-documented")

    def test_non_monotonic_results_are_never_reconciled(self):
        self.assertEqual(verdict_for(50, [(60, "pass"), (40, "fail")]), "inconclusive")

    def test_no_pass_at_all_is_inconclusive_not_restrictive(self):
        self.assertEqual(verdict_for(50, [(40, "fail")]), "inconclusive")

    def test_reconciliation_never_contradicts_boundary_status(self):
        # A report must not claim a confirmed match while the planner still
        # wants a bisection.
        led = ledger_with(50, [(40, "pass"), (60, "fail")])
        verdict, _ = gr.reconcile(50, gr._boundaries(led), "pages")
        self.assertNotEqual(verdict, "confirmed-match")
        self.assertEqual(pb.plan(led, tolerance=1, min_trials=1)["status"], "bisect")


class ProvenanceTests(unittest.TestCase):
    def test_official_guidance_label_requires_source_and_check_date(self):
        bare = rr.new_ledger("c", "direct-upload", "m", "bytes", documented_value=50)
        self.assertEqual(gr._evidence(bare), "Documented value supplied + Measured")

        sourced = rr.new_ledger("c", "direct-upload", "m", "bytes", documented_value=50,
                                documented_source="https://learn.microsoft.com/x")
        self.assertEqual(gr._evidence(sourced), "Documented value supplied + Measured")

        full = rr.new_ledger("c", "direct-upload", "m", "bytes", documented_value=50,
                             documented_source="https://learn.microsoft.com/x",
                             documented_checked_at="2026-08-31")
        self.assertEqual(gr._evidence(full), "Official guidance + Measured")

        none = rr.new_ledger("c", "direct-upload", "m", "bytes")
        self.assertEqual(gr._evidence(none), "Measured")

    def test_scope_is_recorded_and_validated(self):
        led = rr.new_ledger("c", "direct-upload", "m", "bytes",
                            scope={"platform": "Copilot Studio", "region": "UK"})
        self.assertEqual(led["scope"]["region"], "UK")
        self.assertIn("testedAt", led["scope"])
        with self.assertRaises(ValueError):
            rr.new_ledger("c", "direct-upload", "m", "bytes", scope={"tenantId": "secret"})

    def test_missing_scope_is_surfaced_in_the_report(self):
        led = ledger_with(50, [(50, "pass")])
        led["scope"] = {}
        self.assertIn("Scope was not recorded", gr.render_ledger(led))

    def test_path_integrity_defaults_to_unattested_and_warns(self):
        led = ledger_with(50, [(50, "pass")])
        self.assertEqual(led["pathIntegrity"], "not-attested")
        self.assertIn("Path integrity not attested", gr.render_ledger(led))

        led["pathIntegrity"] = "attested"
        self.assertIn("Path integrity attested", gr.render_ledger(led))

        led["pathIntegrity"] = "bypass-observed"
        self.assertIn("coverage evidence is void", gr.render_ledger(led))

    def test_unknown_path_integrity_is_rejected(self):
        with self.assertRaises(ValueError):
            rr.new_ledger("c", "direct-upload", "m", "bytes", path_integrity="probably-fine")


class SchemaTests(unittest.TestCase):
    """Structural conformance without pulling in a jsonschema dependency."""

    def setUp(self):
        with open(os.path.join(ROOT, "assets", "ledger.schema.json"), encoding="utf-8") as fh:
            self.schema = json.load(fh)

    def test_generated_ledger_matches_the_published_schema(self):
        led = ledger_with(50, [(50, "pass"), (51, "fail")], unit="bytes")
        top = self.schema["properties"]
        for key in self.schema["required"]:
            self.assertIn(key, led, key)
        for key in led:
            self.assertIn(key, top, f"{key} is not declared in the schema")

        self.assertIn(led["path"], top["path"]["enum"])
        self.assertIn(led["pathIntegrity"], top["pathIntegrity"]["enum"])
        for key in led["scope"]:
            self.assertIn(key, top["scope"]["properties"], key)

        obs_schema = self.schema["$defs"]["observation"]
        for obs in led["observations"]:
            for key in obs_schema["required"]:
                self.assertIn(key, obs, key)
            for key in obs:
                self.assertIn(key, obs_schema["properties"], f"{key} is not declared")
            self.assertIn(obs["outcome"], obs_schema["properties"]["outcome"]["enum"])
            self.assertIn(obs["failureStage"], obs_schema["properties"]["failureStage"]["enum"])
            self.assertIsInstance(obs["metric"]["value"], (int, float))


class IntegrationTests(unittest.TestCase):
    def test_build_record_plan_report_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            pack = os.path.join(td, "pack")
            manifest = btp.build("size", pack, "txt", sizes=[16384, 32768])
            btp.write_probe_sheet(manifest, pack)
            btp.write_upload_instructions(manifest, pack)

            led = rr.new_ledger("Direct upload", "direct-upload", "file-size", "bytes",
                                documented_value=16384,
                                documented_source="https://learn.microsoft.com/x",
                                documented_checked_at="2026-08-31",
                                scope={"platform": "Copilot Studio", "region": "UK"},
                                path_integrity="attested")
            small, large = manifest["artefacts"][0], manifest["artefacts"][1]
            for _ in range(2):
                rr.record(led, small["file"], small["metric"], {"accepted": "pass"},
                          outcome_override="pass", failure_stage="none")
                rr.record(led, large["file"], large["metric"], {"accepted": "fail"},
                          outcome_override="fail", failure_stage="client-validation")

            self.assertEqual(pb.plan(led)["status"], "converged")
            report = gr.build_report([led])
            self.assertIn("confirmed-match", report)
            self.assertIn("Official guidance + Measured", report)
            self.assertIn("Path integrity attested", report)
            self.assertNotIn("CANARY-", report)

    def test_report_renders_without_a_documented_limit(self):
        led = ledger_with(None, [(10, "pass"), (20, "fail")])
        self.assertIn("no-published-limit", gr.build_report([led]))


class MetricFormattingTests(unittest.TestCase):
    def test_non_numeric_metric_never_crashes_the_pipeline(self):
        # Defence in depth: a stray categorical value must not raise.
        self.assertEqual(metrics.format_metric("pdf", "category"), "pdf")

    def test_categorical_metric_value_is_rejected_with_a_useful_message(self):
        with self.assertRaises(ValueError) as ctx:
            metrics.parse_metric("pdf", "category")
        self.assertIn("not a numeric", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
