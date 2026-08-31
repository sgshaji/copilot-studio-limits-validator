#!/usr/bin/env python3
"""Render a Verified Limits Report from one or more observation ledgers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import metrics
import plan_boundary as pb
import record_result as rr

REPORT_VERSION = "0.2.0"
_STAGE_LABEL = {
    "client-validation": "Client validation (rejected before send)",
    "upload": "Upload",
    "transport": "Transport",
    "ingestion": "Copilot Studio ingestion",
    "connector": "Connector",
    "sharepoint-retrieval": "SharePoint retrieval",
    "onedrive-retrieval": "OneDrive retrieval",
    "parsing": "Parsing",
    "indexing": "Indexing",
    "runtime-transfer": "Runtime transfer",
    "context-handling": "Context handling",
    "tool-invocation": "Tool invocation",
    "downstream-api": "Downstream API",
    "generated-output": "Generated output",
    "coverage": "End-to-end content coverage",
    "none": "None",
    "unknown": "Not determined",
}


def _boundaries(ledger: dict) -> dict:
    by_value = pb._aggregate(ledger)
    passes = sorted(v for v, x in by_value.items() if x["verdict"] == "pass")
    fails = sorted(v for v, x in by_value.items() if x["verdict"] == "fail")
    acceptance: list[float] = []
    for value in sorted(by_value):
        obs = [o for o in ledger["observations"] if float((o.get("metric") or {}).get("value", -1)) == value]
        if obs and all(o.get("stages", {}).get("accepted") == "pass" for o in obs):
            acceptance.append(value)
    first_fail = fails[0] if fails else None
    failure_stage = "unknown"
    if first_fail is not None:
        obs = [o for o in ledger["observations"] if float((o.get("metric") or {}).get("value", -1)) == first_fail]
        stages = [o.get("failureStage") for o in obs if o.get("failureStage") not in (None, "none")]
        if stages:
            # Only report the observed stage. 'coverage' means the internal cause
            # was not isolated by the canary test.
            failure_stage = stages[0]
    return {
        "acceptance": max(acceptance) if acceptance else None,
        "usable": max(passes) if passes else None,
        "firstFail": first_fail,
        "failureStage": failure_stage,
        "values": by_value,
    }


def reconcile(documented: float | None, b: dict, unit: str) -> tuple[str, str]:
    usable, first_fail = b["usable"], b["firstFail"]
    if documented is None:
        return (
            "no-published-limit",
            "No authoritative published limit was recorded for this path. The result below is a scoped measurement, not a supported product limit.",
        )
    if usable is None:
        return ("inconclusive", "No tested value passed the defined end-to-end success criterion, so the published limit could not be reconciled.")
    if first_fail is not None and usable <= documented < first_fail:
        return (
            "match",
            f"Measured behaviour is consistent with the documented boundary of {metrics.format_metric(documented, unit)} within the tested interval.",
        )
    if usable < documented:
        return (
            "more-restrictive-than-documented",
            f"The largest consistently usable value observed was {metrics.format_metric(usable, unit)}, below the documented {metrics.format_metric(documented, unit)}. Treat this as an environment-scoped discrepancy and investigate before relying on the documented value here.",
        )
    return (
        "more-permissive-than-documented",
        f"Values above the documented {metrics.format_metric(documented, unit)} boundary worked in this test, up to {metrics.format_metric(usable, unit)}. This is unsupported headroom, not a supported product capability; design to the documented boundary.",
    )


def _stage(value: str) -> str:
    return {"pass": "Pass", "fail": "Fail", "partial": "Partial", "unknown": "–", "not-tested": "n/t"}.get(value, value)


def _evidence(ledger: dict) -> str:
    return "Official guidance + Measured" if ledger.get("documentedLimit") else "Measured"


def render_ledger(ledger: dict) -> str:
    b = _boundaries(ledger)
    unit = ledger.get("metric", {}).get("unit", "units")
    metric_name = ledger.get("metric", {}).get("name", "metric")
    documented = (ledger.get("documentedLimit") or {}).get("value")
    verdict, prose = reconcile(documented, b, unit)
    planning = pb.plan(ledger)
    lines = [f"## {ledger['capability']}", "",
             f"**Path:** `{ledger['path']}`  ",
             f"**Metric:** {metric_name} ({unit})  "]
    if documented is None:
        lines.append("**Documented limit:** none identified  ")
    else:
        source = (ledger.get("documentedLimit") or {}).get("source")
        src = f" ([source]({source}))" if source else ""
        lines.append(f"**Documented limit:** {metrics.format_metric(documented, unit)}{src}  ")
    lines.extend([
        f"**Largest verified usable value:** {metrics.format_metric(b['usable'], unit)}  ",
        f"**First consistent failing value:** {metrics.format_metric(b['firstFail'], unit)}  ",
        f"**Largest explicitly accepted value:** {metrics.format_metric(b['acceptance'], unit)}  ",
        f"**Observed failure stage:** {_STAGE_LABEL.get(b['failureStage'], b['failureStage'])}  ",
        f"**Evidence:** {_evidence(ledger)}  ",
        f"**Reconciliation:** `{verdict}`", "",
        "### Result", "", prose, "",
    ])
    if planning["status"] != "converged":
        lines.extend([f"> **Boundary status: `{planning['status']}`.** {planning['recommendation']}", ""])
    if b["acceptance"] is not None and b["usable"] is not None and b["acceptance"] > b["usable"]:
        lines.extend([
            "> **Acceptance exceeds demonstrated usability.** The platform accepted a larger value than the largest value that met the end-to-end success criterion. Do not treat acceptance alone as capability.", ""
        ])

    lines.extend([
        "### Test record", "",
        "| Subject | Test value | Format | Bytes | Pages | Accept | Retrieve | Coverage | Trial | Outcome | Failure stage |",
        "| --- | ---: | --- | ---: | ---: | --- | --- | --- | ---: | --- | --- |",
    ])
    for obs in sorted(ledger.get("observations", []), key=lambda o: (float((o.get("metric") or {}).get("value", 0)), o.get("trial", 1))):
        m = obs.get("metric") or {}
        s = obs.get("stages") or {}
        canaries = obs.get("canaries") or []
        cov = _stage(s.get("coverage", "unknown"))
        if canaries:
            hits = sum(1 for c in canaries if c.get("found"))
            cov += f" ({hits}/{len(canaries)})"
        lines.append(
            f"| `{obs.get('subject','')}` | {metrics.format_metric(m.get('value'), m.get('unit', unit))} | {obs.get('format') or '–'} | "
            f"{metrics.human_bytes(obs['bytes']) if obs.get('bytes') is not None else '–'} | {obs.get('pages') if obs.get('pages') is not None else '–'} | "
            f"{_stage(s.get('accepted','unknown'))} | {_stage(s.get('retrievable','unknown'))} | {cov} | {obs.get('trial',1)} | **{obs.get('outcome','inconclusive')}** | {_STAGE_LABEL.get(obs.get('failureStage','unknown'), obs.get('failureStage','unknown'))} |"
        )
    lines.append("")

    misses = []
    for obs in ledger.get("observations", []):
        failed = [c for c in obs.get("canaries", []) if not c.get("found")]
        if failed:
            misses.append((obs.get("subject", ""), failed))
    if misses:
        lines.extend([
            "### Positions not demonstrated end-to-end", "",
            "A missing canary means the model did not reproduce the expected token for that position. It does **not** by itself prove whether the cause was parsing, indexing, retrieval, context handling, or another internal stage.", "",
        ])
        for subject, failed in misses:
            labels = []
            for item in failed:
                if item.get("file"):
                    labels.append(item["file"])
                else:
                    labels.append(str(item.get("position", "?")))
            lines.append(f"- `{subject}` — {', '.join(labels)}")
        lines.append("")
    return "\n".join(lines)


def render_comparison(ledgers: list[dict]) -> str:
    lines = [
        "## Path comparison", "",
        "Compare only ledgers measuring the same metric and success criterion. Different ingestion/runtime paths can impose different boundaries.", "",
        "| Path | Capability | Metric | Largest usable | First fail | Failure stage | Evidence |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for ledger in ledgers:
        b = _boundaries(ledger)
        unit = ledger.get("metric", {}).get("unit", "units")
        lines.append(
            f"| `{ledger['path']}` | {ledger['capability']} | {ledger.get('metric',{}).get('name','metric')} | "
            f"{metrics.format_metric(b['usable'], unit)} | {metrics.format_metric(b['firstFail'], unit)} | "
            f"{_STAGE_LABEL.get(b['failureStage'], b['failureStage'])} | {_evidence(ledger)} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_report(ledgers: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = [
        "# Verified Limits Report", "",
        f"Generated {stamp} by `copilot-studio-limits-validator` v{REPORT_VERSION}.", "",
        "Every measured value is scoped to the environment and conditions in which it was observed. Product updates, tenant configuration, region, licence, harness, ingestion path, and downstream dependencies can change the result. Re-measure before generalising it.", "",
    ]
    body = [render_ledger(l) for l in ledgers]
    if len(ledgers) > 1:
        body.append(render_comparison(ledgers))
    return "\n".join(head) + "\n" + "\n\n---\n\n".join(body) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", action="append", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    report = build_report([rr.load(path) for path in args.ledger])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
