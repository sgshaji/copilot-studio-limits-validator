#!/usr/bin/env python3
"""Render a Verified Limits Report from one or more observation ledgers.

The report separates two numbers that are routinely conflated:

* the **acceptance** boundary -- the largest input the platform took, and
* the **usable** boundary -- the largest input whose content was fully
  readable afterwards.

A file that uploads cleanly but is only half parsed is not a passing test at
that size, and reporting it as one is the specific mistake this skill exists
to prevent.

Run standalone:

    python generate_report.py --ledger run.json --out report.md
    python generate_report.py --ledger direct.json --ledger sharepoint.json \\
        --out comparison.md          # cross-path comparison table

Standard library only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import make_test_file as mtf
import plan_boundary as pb
import record_result as rr

REPORT_VERSION = "0.1.0"

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
    "accepted": "Input acceptance",
    "transferred": "Transfer to agent",
    "processed": "Processing",
    "retrievable": "Content retrieval",
    "coverage": "Content coverage",
    "none": "None",
    "unknown": "Not determined",
}


def _boundaries(ledger: dict) -> dict:
    """Largest size that was accepted, and largest that was fully usable."""
    accepted: list[int] = []
    usable: list[int] = []
    first_fail: int | None = None
    fail_stage = "unknown"

    by_size = pb._aggregate(ledger)
    for size in sorted(by_size):
        obs = [o for o in ledger["observations"] if o.get("bytes") == size]
        if all(o["stages"].get("accepted") == "pass" for o in obs):
            accepted.append(size)
        if by_size[size]["verdict"] == "pass":
            usable.append(size)
        elif by_size[size]["verdict"] == "fail" and first_fail is None:
            first_fail = size
            stages = [o["failureStage"] for o in obs if o["failureStage"] not in ("none", None)]
            fail_stage = stages[0] if stages else "unknown"

    return {
        "acceptance": max(accepted) if accepted else None,
        "usable": max(usable) if usable else None,
        "firstFail": first_fail,
        "failureStage": fail_stage,
        "sizes": by_size,
    }


def reconcile(documented: int | None, b: dict) -> tuple[str, str]:
    """Compare measured behaviour with published guidance."""
    usable, first_fail = b["usable"], b["firstFail"]
    if documented is None:
        return (
            "no-published-limit",
            "No authoritative published limit was identified for this path. The "
            "values below are measured observations only and must not be quoted "
            "as a supported product limit.",
        )
    if usable is None:
        return ("inconclusive", "No size passed all lifecycle stages, so the "
                               "documented limit could not be reconciled.")
    if first_fail is not None and usable <= documented < first_fail:
        return (
            "match",
            f"Measured behaviour reproduces the documented {mtf.human_size(documented)} "
            "limit: inputs at or below it completed every lifecycle stage, and the "
            "first consistent failure sits above it.",
        )
    if usable < documented:
        return (
            "more-restrictive-than-documented",
            f"Documentation states {mtf.human_size(documented)}, but reliable "
            f"end-to-end processing was only observed up to {mtf.human_size(usable)}. "
            "Design to the measured value in this environment and raise the gap with "
            "Microsoft rather than assuming the documented figure.",
        )
    return (
        "more-permissive-than-documented",
        f"Inputs above the documented {mtf.human_size(documented)} limit were "
        f"processed successfully (up to {mtf.human_size(usable)}). This is "
        "**not** a supported capability -- unsupported headroom can be removed "
        "without notice. The documented value remains the boundary to design to.",
    )


def _evidence(documented: int | None) -> str:
    return "Official guidance + Measured" if documented is not None else "Measured"


def _stage_cell(value: str) -> str:
    return {"pass": "Pass", "fail": "Fail", "partial": "Partial",
            "unknown": "-", "not-tested": "n/t"}.get(value, value)


def render_ledger(ledger: dict) -> str:
    b = _boundaries(ledger)
    doc = (ledger.get("documentedLimit") or {}).get("bytes")
    verdict, prose = reconcile(doc, b)
    planning = pb.plan(ledger)

    lines: list[str] = []
    lines.append(f"## {ledger['capability']}")
    lines.append("")
    lines.append(f"**Ingestion path:** `{ledger['path']}`  ")
    lines.append(
        "**Documented limit:** "
        + (f"{mtf.human_size(doc)}" if doc else "none identified")
        + (f" ([source]({ledger['documentedLimit']['source']}))"
           if doc and (ledger.get('documentedLimit') or {}).get('source') else "")
        + "  "
    )
    lines.append(
        "**Observed input acceptance:** "
        + (f"up to {mtf.human_size(b['acceptance'])}" if b["acceptance"] else "not established")
        + "  "
    )
    lines.append(
        "**Observed complete processing:** "
        + (f"up to {mtf.human_size(b['usable'])}" if b["usable"] else "not established")
        + "  "
    )
    lines.append(
        "**First consistent failure:** "
        + (mtf.human_size(b["firstFail"]) if b["firstFail"] else "none observed")
        + "  "
    )
    lines.append(f"**Failure stage:** {_STAGE_LABEL.get(b['failureStage'], b['failureStage'])}  ")
    lines.append(f"**Evidence:** {_evidence(doc)}  ")
    lines.append(f"**Reconciliation:** `{verdict}`")
    lines.append("")

    if b["acceptance"] and b["usable"] and b["acceptance"] > b["usable"]:
        lines.append(
            f"> **Acceptance exceeds usability.** Inputs up to "
            f"{mtf.human_size(b['acceptance'])} were accepted, but content was only "
            f"fully readable up to {mtf.human_size(b['usable'])}. Between those two "
            "figures the platform takes the file and silently returns incomplete "
            "content -- the most expensive failure mode, because nothing reports an "
            "error."
        )
        lines.append("")

    lines.append("### Result")
    lines.append("")
    lines.append(prose)
    lines.append("")

    if planning["status"] not in ("converged", "no-data"):
        lines.append(f"> **Boundary not yet settled** (`{planning['status']}`). "
                     f"{planning['recommendation']}")
        lines.append("")

    lines.append("### Test record")
    lines.append("")
    lines.append("| Artefact | Size | Pages | Accept | Process | Retrieve | Coverage | Trial | Outcome |")
    lines.append("| --- | ---: | ---: | --- | --- | --- | --- | ---: | --- |")
    for obs in sorted(ledger["observations"], key=lambda o: (o.get("bytes") or 0, o["trial"])):
        s = obs["stages"]
        cov = s.get("coverage", "unknown")
        if obs["canaries"]:
            hits = sum(1 for c in obs["canaries"] if c["found"])
            cov = f"{_stage_cell(cov)} ({hits}/{len(obs['canaries'])})"
        else:
            cov = _stage_cell(cov)
        lines.append(
            f"| `{obs['file']}` | {mtf.human_size(obs['bytes']) if obs['bytes'] else '-'} "
            f"| {obs['pages'] or '-'} | {_stage_cell(s.get('accepted','unknown'))} "
            f"| {_stage_cell(s.get('processed','unknown'))} "
            f"| {_stage_cell(s.get('retrievable','unknown'))} | {cov} "
            f"| {obs['trial']} | **{obs['outcome']}** |"
        )
    lines.append("")

    missing = [
        (obs["file"], [c["page"] for c in obs["canaries"] if not c["found"]])
        for obs in ledger["observations"] if any(not c["found"] for c in obs["canaries"])
    ]
    if missing:
        lines.append("### Unparsed pages")
        lines.append("")
        lines.append("Canary tokens that could not be retrieved. Because the tokens are "
                     "random, a miss is positive evidence the page was never parsed -- "
                     "not a retrieval preference.")
        lines.append("")
        for name, pages in missing:
            lines.append(f"- `{name}` -- pages {', '.join(str(p) for p in pages)}")
        lines.append("")

    return "\n".join(lines)


def render_comparison(ledgers: list[dict]) -> str:
    lines = ["## Path comparison", "",
             "Copilot Studio has no single universal file limit -- different "
             "subsystems enforce different boundaries. Comparing the same "
             "capability across ingestion paths is usually more useful than any "
             "single number.", "",
             "| Path | Capability | Accepted to | Fully usable to | Failure stage | Evidence |",
             "| --- | --- | ---: | ---: | --- | --- |"]
    for ledger in ledgers:
        b = _boundaries(ledger)
        doc = (ledger.get("documentedLimit") or {}).get("bytes")
        lines.append(
            f"| `{ledger['path']}` | {ledger['capability']} "
            f"| {mtf.human_size(b['acceptance']) if b['acceptance'] else 'not established'} "
            f"| {mtf.human_size(b['usable']) if b['usable'] else 'not established'} "
            f"| {_STAGE_LABEL.get(b['failureStage'], b['failureStage'])} "
            f"| {_evidence(doc)} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_report(ledgers: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = [
        "# Verified Limits Report", "",
        f"Generated {stamp} by `copilot-studio-limits-validator` v{REPORT_VERSION}.", "",
        "Every figure below is an observation from **this environment**. Limits can "
        "differ by tenant, environment, licence, harness and region, and can change "
        "with any service update. Re-measure before relying on these numbers "
        "elsewhere.", "",
    ]
    body = [render_ledger(l) for l in ledgers]
    if len(ledgers) > 1:
        body.append(render_comparison(ledgers))
    return "\n".join(head) + "\n" + "\n\n---\n\n".join(body) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", action="append", required=True,
                    help="ledger JSON; repeat for a cross-path comparison")
    ap.add_argument("--out", help="write Markdown here (default: stdout)")
    args = ap.parse_args(argv)

    report = build_report([rr.load(p) for p in args.ledger])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"wrote {args.out} ({len(report)} chars)")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
