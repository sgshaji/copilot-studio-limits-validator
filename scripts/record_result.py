#!/usr/bin/env python3
"""Record limit-validation observations without over-interpreting evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import metrics

LEDGER_VERSION = "0.2.0"
STAGES = ("accepted", "transferred", "processed", "retrievable", "coverage")
STAGE_VALUES = ("pass", "fail", "partial", "unknown", "not-tested")
OUTCOMES = ("pass", "fail", "partial", "inconclusive")
FAILURE_STAGES = (
    "client-validation", "upload", "transport", "ingestion", "connector",
    "sharepoint-retrieval", "onedrive-retrieval", "parsing", "indexing",
    "runtime-transfer", "context-handling", "tool-invocation", "downstream-api",
    "generated-output", "coverage", "none", "unknown",
)
PATHS = (
    "direct-upload", "agent-knowledge", "sharepoint", "sharepoint-library",
    "onedrive", "tool-input", "tool-output", "generated-output", "runtime",
)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def new_ledger(capability: str, path: str, metric_name: str, metric_unit: str,
               documented_value: float | None = None, documented_text: str = "",
               documented_source: str = "", pack_id: str = "") -> dict:
    if path not in PATHS:
        raise ValueError(f"unknown path {path!r}; expected one of {', '.join(PATHS)}")
    documented = None
    if documented_value is not None or documented_text:
        documented = {
            "value": documented_value,
            "unit": metric_unit,
            "text": documented_text,
            "source": documented_source,
        }
    return {
        "ledgerVersion": LEDGER_VERSION,
        "capability": capability,
        "path": path,
        "metric": {"name": metric_name, "unit": metric_unit},
        "packId": pack_id,
        "documentedLimit": documented,
        "createdAt": now(),
        "observations": [],
    }


def _artifact(manifest: dict, filename: str) -> dict | None:
    return next((a for a in manifest.get("artefacts", []) if a.get("file") == filename), None)


def _scenario(manifest: dict, scenario_id: str) -> dict | None:
    return next((s for s in manifest.get("scenarios", []) if s.get("id") == scenario_id), None)


def verify_page_claims(expected: list[dict], claims: dict[int, str]) -> tuple[str, list[dict]]:
    if not expected:
        return "unknown", []
    detail = []
    for item in expected:
        claimed = (claims.get(int(item["page"])) or "").strip().upper()
        expected_token = str(item["token"]).strip().upper()
        detail.append({
            "position": int(item["page"]),
            "expected": expected_token,
            "claimed": claimed or None,
            "found": claimed == expected_token,
            "mismatch": bool(claimed) and claimed != expected_token,
        })
    hits = sum(1 for d in detail if d["found"])
    if hits == len(detail):
        return "pass", detail
    if hits == 0:
        return "fail", detail
    return "partial", detail


def verify_scenario_claims(manifest: dict, scenario: dict, claims: dict[str, str]) -> tuple[str, list[dict]]:
    detail = []
    for filename in scenario.get("files", []):
        artifact = _artifact(manifest, filename)
        canaries = (artifact or {}).get("canaries", [])
        expected_token = str(canaries[0]["token"]).upper() if canaries else ""
        claimed = (claims.get(filename) or "").strip().upper()
        detail.append({
            "file": filename,
            "position": int(canaries[0]["page"]) if canaries else 1,
            "expected": expected_token or None,
            "claimed": claimed or None,
            "found": bool(expected_token) and claimed == expected_token,
            "mismatch": bool(claimed) and bool(expected_token) and claimed != expected_token,
        })
    if not detail:
        return "unknown", []
    hits = sum(1 for d in detail if d["found"])
    if hits == len(detail):
        return "pass", detail
    if hits == 0:
        return "fail", detail
    return "partial", detail


def derive_outcome(stages: dict[str, str], coverage_observed: bool = False) -> tuple[str, str]:
    # A directly observed fail/partial wins. Do not fabricate failure causes.
    for stage in STAGES:
        value = stages.get(stage, "unknown")
        if value == "fail":
            return "fail", "coverage" if stage == "coverage" else "unknown"
        if value == "partial":
            return "partial", "coverage" if stage == "coverage" else "unknown"
    if coverage_observed and stages.get("coverage") == "pass":
        return "pass", "none"
    observed = [v for v in stages.values() if v not in ("unknown", "not-tested")]
    if observed and all(v == "pass" for v in observed):
        return "pass", "none"
    return "inconclusive", "unknown"


def record(ledger: dict, subject: str, metric: dict, stages: dict[str, str],
           *, fmt: str | None = None, byte_size: int | None = None,
           pages: int | None = None, canaries: list[dict] | None = None,
           outcome_override: str | None = None, failure_stage: str = "",
           error: str = "", note: str = "") -> dict:
    trial = 1 + sum(1 for o in ledger["observations"] if o["subject"] == subject)
    outcome, hint = derive_outcome(stages, coverage_observed=canaries is not None)
    if outcome_override:
        outcome = outcome_override
    obs = {
        "subject": subject,
        "format": fmt,
        "bytes": byte_size,
        "pages": pages,
        "metric": metric,
        "trial": trial,
        "stages": {s: stages.get(s, "unknown") for s in STAGES},
        "canaries": canaries or [],
        "outcome": outcome,
        "failureStage": failure_stage or hint,
        "error": error or None,
        "note": note or None,
        "recordedAt": now(),
    }
    ledger["observations"].append(obs)
    return obs


def _parse_page_claims(text: str) -> dict[int, str]:
    claims: dict[int, str] = {}
    for pair in text.split(","):
        if "=" not in pair:
            continue
        key, token = pair.split("=", 1)
        claims[int(key.strip())] = token.strip()
    return claims


def _parse_file_claims(text: str) -> dict[str, str]:
    claims: dict[str, str] = {}
    for pair in text.split(";"):
        if "=" not in pair:
            continue
        key, token = pair.split("=", 1)
        claims[key.strip()] = token.strip()
    return claims


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--capability", default="")
    ap.add_argument("--path", default="direct-upload", choices=PATHS)
    ap.add_argument("--metric-name", default="file-size")
    ap.add_argument("--metric-unit", default="bytes")
    ap.add_argument("--documented-value", help="numeric value in --metric-unit")
    ap.add_argument("--documented", help="backward-compatible byte size, e.g. 50MB")
    ap.add_argument("--documented-source", default="")
    ap.add_argument("--manifest")
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--file")
    target.add_argument("--scenario")
    ap.add_argument("--subject", help="manual subject name for non-file tests")
    ap.add_argument("--metric-value", help="manual metric value for non-file tests")
    for stage in STAGES:
        ap.add_argument(f"--{stage}", choices=STAGE_VALUES)
    ap.add_argument("--canaries-claimed", help='file probe claims: "1=TOKEN,5=TOKEN"')
    ap.add_argument("--attachments-claimed", help='count scenario claims: "file1=TOKEN;file2=TOKEN"')
    ap.add_argument("--outcome", choices=OUTCOMES)
    ap.add_argument("--failure-stage", choices=FAILURE_STAGES, default="")
    ap.add_argument("--error", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)

    manifest = load(args.manifest) if args.manifest else {}

    if args.init:
        unit = args.metric_unit
        documented_value: float | None = None
        documented_text = ""
        if args.documented:
            unit = "bytes"
            documented_value = float(metrics.parse_bytes(args.documented))
            documented_text = args.documented
        elif args.documented_value is not None:
            documented_value = metrics.parse_metric(args.documented_value, unit)
            documented_text = f"{args.documented_value} {unit}"
        ledger = new_ledger(
            args.capability or "unnamed capability", args.path,
            args.metric_name, unit, documented_value, documented_text,
            args.documented_source, manifest.get("packId", ""),
        )
        save(ledger, args.ledger)
        print(f"initialised {args.ledger}: metric={ledger['metric']['name']} ({ledger['metric']['unit']})")
        return 0

    ledger = load(args.ledger)
    stages = {s: getattr(args, s) for s in STAGES if getattr(args, s) is not None}
    detail: list[dict] | None = None

    if args.file:
        artifact = _artifact(manifest, args.file) if manifest else None
        if not artifact:
            ap.error("--file requires a manifest containing that artefact")
        metric = artifact.get("metric") or {"name": ledger["metric"]["name"], "value": artifact.get("actualBytes"), "unit": ledger["metric"]["unit"]}
        if args.canaries_claimed is not None:
            coverage, detail = verify_page_claims(artifact.get("canaries", []), _parse_page_claims(args.canaries_claimed))
            stages.setdefault("coverage", coverage)
            if coverage in ("pass", "partial"):
                # Token retrieval proves end-to-end availability at at least one
                # position. It does NOT identify which internal parser/indexer ran.
                stages.setdefault("retrievable", "pass")
                stages.setdefault("transferred", "pass")
        obs = record(
            ledger, args.file, metric, stages, fmt=artifact.get("format"),
            byte_size=artifact.get("actualBytes"), pages=artifact.get("pages"),
            canaries=detail, outcome_override=args.outcome,
            failure_stage=args.failure_stage, error=args.error, note=args.note,
        )

    elif args.scenario:
        scenario = _scenario(manifest, args.scenario) if manifest else None
        if not scenario:
            ap.error("--scenario requires a manifest containing that scenario")
        if args.attachments_claimed is not None:
            coverage, detail = verify_scenario_claims(manifest, scenario, _parse_file_claims(args.attachments_claimed))
            stages.setdefault("coverage", coverage)
            if coverage in ("pass", "partial"):
                stages.setdefault("retrievable", "pass")
                stages.setdefault("transferred", "pass")
        obs = record(
            ledger, args.scenario, scenario["metric"], stages,
            byte_size=scenario.get("totalBytes"), canaries=detail,
            outcome_override=args.outcome, failure_stage=args.failure_stage,
            error=args.error, note=args.note,
        )

    else:
        subject = args.subject or "manual-observation"
        if args.metric_value is None:
            ap.error("manual observations require --metric-value")
        metric = {
            "name": ledger["metric"]["name"],
            "value": metrics.parse_metric(args.metric_value, ledger["metric"]["unit"]),
            "unit": ledger["metric"]["unit"],
        }
        obs = record(
            ledger, subject, metric, stages, outcome_override=args.outcome,
            failure_stage=args.failure_stage, error=args.error, note=args.note,
        )

    save(ledger, args.ledger)
    print(f"{obs['subject']} trial={obs['trial']} metric={metrics.format_metric(obs['metric']['value'], obs['metric']['unit'])} outcome={obs['outcome']} failureStage={obs['failureStage']}")
    if obs["canaries"]:
        hits = sum(1 for c in obs["canaries"] if c.get("found"))
        print(f"canary coverage: {hits}/{len(obs['canaries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
