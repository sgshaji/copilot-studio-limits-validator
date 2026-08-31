#!/usr/bin/env python3
"""Render a Verified Limits Report from one or more observation ledgers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import metrics
import plan_boundary as pb
import record_result as rr

REPORT_VERSION = "0.3.0"
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


def reconcile(documented: float | None, b: dict, unit: str,
              *, tolerance: float | None = None, min_trials: int = 2) -> tuple[str, str]:
    """Classify measurement against published guidance.

    Every verdict must be earned by evidence that was actually collected. In
    particular, a value is never called permissive or restrictive unless a
    value on the relevant side of the documented boundary was really tested.
    """
    usable, first_fail, values = b["usable"], b["firstFail"], b["values"]
    fmt = lambda v: metrics.format_metric(v, unit)

    if documented is None:
        return (
            "no-published-limit",
            "No authoritative published limit was recorded for this path. The result below is a scoped measurement, not a supported product limit.",
        )
    if usable is None and first_fail is None:
        return ("inconclusive", "No numeric observation was recorded, so the published limit could not be reconciled.")
    if usable is not None and first_fail is not None and usable > first_fail:
        return (
            "inconclusive",
            f"{fmt(usable)} passed while the smaller value {fmt(first_fail)} failed. The metric is not behaving monotonically, so no boundary can be reconciled until the confounder is found.",
        )
    if usable is None:
        return (
            "inconclusive",
            f"No tested value met the end-to-end success criterion, including values at or below the documented {fmt(documented)}. Establish a working baseline before treating this as a boundary.",
        )

    if first_fail is not None and first_fail <= documented:
        return (
            "more-restrictive-than-documented",
            f"{fmt(first_fail)} failed consistently, at or below the documented {fmt(documented)}. The largest value that met the criterion was {fmt(usable)}. Treat this as an environment-scoped discrepancy and investigate before relying on the documented value here.",
        )
    if usable > documented:
        return (
            "observed-headroom",
            f"{fmt(usable)} met the criterion, above the documented {fmt(documented)}. This is unsupported headroom observed in one environment, not a supported product capability; design to the documented boundary.",
        )

    # Remaining case: every passing value is at or below the documented
    # boundary, and every failing value is above it.
    tolerance = metrics.default_tolerance(unit) if tolerance is None else float(tolerance)
    at_documented = values.get(float(documented))
    documented_passes = bool(at_documented) and at_documented["verdict"] == "pass"
    repeated = documented_passes and at_documented["trials"] >= min_trials
    fail_repeated = first_fail is not None and values[first_fail]["trials"] >= min_trials

    if repeated and fail_repeated and (first_fail - documented) <= tolerance:
        return (
            "confirmed-match",
            f"The documented boundary of {fmt(documented)} was tested directly and passed on {at_documented['trials']} trials, while {fmt(first_fail)} failed. Measurement and guidance agree at this boundary, in this environment.",
        )
    if first_fail is not None:
        detail = (
            f"{fmt(documented)} itself passed, but the nearest failing value {fmt(first_fail)} is more than {fmt(tolerance)} above it, so the exact boundary is not resolved."
            if documented_passes else
            f"{fmt(documented)} itself was never tested; the boundary lies somewhere between {fmt(usable)} (pass) and {fmt(first_fail)} (fail)."
        )
        return ("consistent-with-guidance", f"Nothing contradicts the documented {fmt(documented)}. {detail}")

    if documented_passes:
        return (
            "inconclusive",
            f"The documented {fmt(documented)} was tested and passed, but no larger value was tested. This does not establish whether the boundary sits at the documented value or above it.",
        )
    return (
        "inconclusive",
        f"The largest passing value was {fmt(usable)}, at or below the documented {fmt(documented)}, and no value failed. Nothing above the documented boundary was tested, so guidance can be neither confirmed nor contradicted.",
    )


def _stage(value: str) -> str:
    return {"pass": "Pass", "fail": "Fail", "partial": "Partial", "unknown": "–", "not-tested": "n/t"}.get(value, value)


def _evidence(ledger: dict) -> str:
    """A documented value only counts as official guidance when it is
    attributable: a value, a source, and the date the source was read."""
    documented = ledger.get("documentedLimit") or {}
    if not documented:
        return "Measured"
    if documented.get("value") is not None and documented.get("source") and documented.get("checkedAt"):
        return "Official guidance + Measured"
    return "Documented value supplied + Measured"


_SCOPE_LABEL = {
    "platform": "Platform", "harness": "Harness", "environmentType": "Environment",
    "region": "Region", "channel": "Channel", "model": "Model",
    "licenseContext": "Licence", "testedAt": "Tested", "notes": "Notes",
}


def _scope_line(ledger: dict) -> list[str]:
    scope = ledger.get("scope") or {}
    recorded = [(k, scope[k]) for k in rr.SCOPE_KEYS if scope.get(k)]
    if not recorded:
        return [
            "**Scope:** not recorded  ",
            "",
            "> **Scope was not recorded.** A boundary is only meaningful against the tenant, region, licence, harness and date it was measured in. Without them this result cannot be compared with a later run or another environment.",
            "",
        ]
    return [f"**Scope:** {'; '.join(f'{_SCOPE_LABEL[k]} {v}' for k, v in recorded)}  "]


def _path_integrity_block(ledger: dict) -> list[str]:
    state = ledger.get("pathIntegrity", "not-attested")
    if state == "attested":
        return [
            "> **Path integrity attested.** The operator confirmed the agent had no alternate route to the artefact contents, so a correct canary is evidence about the tested path.",
            "",
        ]
    if state == "bypass-observed":
        return [
            "> **Path integrity failed — coverage evidence is void.** An alternate access route to the artefact was available or used, so a correct canary shows only that the agent obtained the content somehow. It is not evidence about the tested path. Re-run with that route disabled.",
            "",
        ]
    return [
        "> **Path integrity not attested.** A correct canary proves the agent obtained the content by *some* route available to it, which is only evidence about this path if no alternate route (runtime file reads, unzipping, PDF libraries, filesystem search) existed. Read coverage results accordingly.",
        "",
    ]


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
    lines.extend(_scope_line(ledger))
    lines.extend([
        f"**Path integrity:** `{ledger.get('pathIntegrity', 'not-attested')}`  ",
        f"**Largest verified usable value:** {metrics.format_metric(b['usable'], unit)}  ",
        f"**First consistent failing value:** {metrics.format_metric(b['firstFail'], unit)}  ",
        f"**Largest explicitly accepted value:** {metrics.format_metric(b['acceptance'], unit)}  ",
        f"**Observed failure stage:** {_STAGE_LABEL.get(b['failureStage'], b['failureStage'])}  ",
        f"**Evidence:** {_evidence(ledger)}  ",
        f"**Reconciliation:** `{verdict}`", "",
        "### Result", "", prose, "",
    ])
    lines.extend(_path_integrity_block(ledger))
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
        "A verdict here describes only what was actually tested. `confirmed-match` requires the documented value to have been tested directly and repeated; `consistent-with-guidance` means nothing contradicted it; `inconclusive` means the evidence does not settle the question either way.", "",
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
