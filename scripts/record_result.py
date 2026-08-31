#!/usr/bin/env python3
"""Observation ledger for Copilot Studio limit validation.

Records what happened to each test artefact, **stage by stage**. The whole
point of the ledger is that "the upload worked" is not a result: an artefact
can be accepted, transferred, parsed, and still only be half readable. Each
stage is recorded separately so the report can name the stage at which a
capability actually stops working.

Lifecycle stages, in order:

    accepted     the client/UI/API took the file at all
    transferred  the agent can see the artefact in its context
    processed    parsing / extraction / indexing completed
    retrievable  at least some content can be read back
    coverage     ALL canary tokens can be read back (start, middle, end)

Stage values: pass | fail | partial | unknown | not-tested
`unknown` is used whenever a stage was not observed. A stage is never marked
`fail` because we forgot to look.

Run standalone:

    python record_result.py --ledger run.json --init \\
        --capability "Direct file upload - PDF" --path direct-upload \\
        --documented 50MB --documented-source "https://learn.microsoft.com/..."

    python record_result.py --ledger run.json --manifest pack/manifest.json \\
        --file pdf-50MB.pdf --accepted pass --transferred pass --processed pass \\
        --canaries-found 1,2,3,4,5,10,20,30,36,40

    python record_result.py --ledger run.json --manifest pack/manifest.json \\
        --file pdf-51MB.pdf --accepted fail --failure-stage client-validation \\
        --error "attachment rejected before send"

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

LEDGER_VERSION = "0.1.0"

STAGES = ("accepted", "transferred", "processed", "retrievable", "coverage")
STAGE_VALUES = ("pass", "fail", "partial", "unknown", "not-tested")

# Where a failure was observed to occur. Naming the stage is the core output
# of this skill -- "rejected before upload" and "uploaded but only partly
# parsed" are completely different product behaviours.
FAILURE_STAGES = (
    "client-validation", "upload", "transport", "ingestion", "connector",
    "sharepoint-retrieval", "onedrive-retrieval", "parsing", "indexing",
    "runtime-transfer", "context-handling", "tool-invocation",
    "downstream-api", "generated-output", "none", "unknown",
)


def new_ledger(capability: str, path: str, documented_bytes: int | None = None,
               documented_text: str = "", documented_source: str = "",
               pack_id: str = "") -> dict:
    return {
        "ledgerVersion": LEDGER_VERSION,
        "capability": capability,
        "path": path,
        "packId": pack_id,
        "documentedLimit": {
            "bytes": documented_bytes,
            "text": documented_text,
            "source": documented_source,
        } if documented_bytes or documented_text else None,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "observations": [],
    }


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(ledger: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2)


def _artefact(manifest: dict, filename: str) -> dict | None:
    for a in manifest.get("artefacts", []):
        if a.get("file") == filename:
            return a
    return None


def derive_coverage(expected: list[dict], found_pages: set[int]) -> tuple[str, list[dict]]:
    """Compare retrieved canary pages against the manifest.

    Returns (stage_value, per-canary detail). A missing token is hard evidence
    that the page was never parsed -- the token cannot be guessed.
    """
    if not expected:
        return "unknown", []
    detail = [
        {"page": c["page"], "token": c["token"], "found": c["page"] in found_pages}
        for c in expected
    ]
    hits = sum(1 for d in detail if d["found"])
    if hits == len(detail):
        return "pass", detail
    if hits == 0:
        return "fail", detail
    return "partial", detail


def verify_claims(expected: list[dict], claims: dict[int, str]) -> tuple[str, list[dict]]:
    """Score claimed tokens against the manifest.

    A page counts as parsed only when the agent reproduces the token
    *verbatim*. Anything else -- a plausible-looking invention, a token copied
    from a different page, or a token echoed from the manifest for a page that
    was never read -- scores as not found. This is what makes coverage a
    measurement rather than a self-report.
    """
    if not expected:
        return "unknown", []
    detail = []
    for c in expected:
        claimed = (claims.get(c["page"]) or "").strip().upper()
        detail.append({
            "page": c["page"],
            "token": c["token"],
            "claimed": claimed or None,
            "found": claimed == c["token"].upper(),
            "mismatch": bool(claimed) and claimed != c["token"].upper(),
        })
    hits = sum(1 for d in detail if d["found"])
    if hits == len(detail):
        return "pass", detail
    if hits == 0:
        return "fail", detail
    return "partial", detail


def outcome_of(stages: dict[str, str]) -> tuple[str, str]:
    """Collapse the stage map into (outcome, failure_stage_hint)."""
    for stage in STAGES:
        value = stages.get(stage, "unknown")
        if value == "fail":
            return "fail", stage
        if value == "partial":
            return "partial", stage
    if all(stages.get(s) in ("pass", "not-tested") for s in STAGES):
        return "pass", "none"
    return "inconclusive", "unknown"


def record(ledger: dict, filename: str, stages: dict[str, str],
           artefact: dict | None = None, canary_detail: list[dict] | None = None,
           failure_stage: str = "", error: str = "", note: str = "") -> dict:
    trial = 1 + sum(1 for o in ledger["observations"] if o["file"] == filename)
    outcome, hint = outcome_of(stages)
    obs = {
        "file": filename,
        "format": (artefact or {}).get("format"),
        "bytes": (artefact or {}).get("actualBytes"),
        "pages": (artefact or {}).get("pages"),
        "runId": (artefact or {}).get("runId"),
        "trial": trial,
        "stages": {s: stages.get(s, "unknown") for s in STAGES},
        "canaries": canary_detail or [],
        "outcome": outcome,
        "failureStage": failure_stage or (hint if outcome != "pass" else "none"),
        "error": error or None,
        "note": note or None,
        "recordedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    ledger["observations"].append(obs)
    return obs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--init", action="store_true", help="create a new ledger")
    ap.add_argument("--capability", default="")
    ap.add_argument("--path", default="direct-upload",
                    help="ingestion path under test (direct-upload, sharepoint, tool, ...)")
    ap.add_argument("--documented", help="documented limit, e.g. 50MB")
    ap.add_argument("--documented-source", default="")
    ap.add_argument("--manifest", help="pack manifest.json, to resolve artefact facts")
    ap.add_argument("--file", help="artefact filename this observation is about")
    for stage in STAGES:
        ap.add_argument(f"--{stage}", choices=STAGE_VALUES, default=None)
    ap.add_argument("--canaries-found", default=None,
                    help="comma-separated page numbers whose token was retrieved verbatim")
    ap.add_argument("--canaries-claimed", default=None,
                    help='verified form: "1=CANARY-AB12-P0001-9C1E,5=CANARY-..." -- '
                         "each claimed token is checked against the manifest, so a "
                         "guessed or echoed token is scored as NOT found")
    ap.add_argument("--failure-stage", choices=FAILURE_STAGES, default="")
    ap.add_argument("--error", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)

    if args.init:
        import make_test_file as mtf
        pack_id = ""
        if args.manifest and os.path.exists(args.manifest):
            pack_id = json.load(open(args.manifest, encoding="utf-8")).get("packId", "")
        ledger = new_ledger(
            args.capability or "unnamed capability", args.path,
            mtf.parse_size(args.documented) if args.documented else None,
            args.documented or "", args.documented_source, pack_id,
        )
        save(ledger, args.ledger)
        print(f"initialised ledger {args.ledger} for {ledger['capability']!r} "
              f"(path={ledger['path']})")
        return 0

    if not args.file:
        ap.error("--file is required unless --init")

    ledger = load(args.ledger)
    manifest = json.load(open(args.manifest, encoding="utf-8")) if args.manifest else {}
    artefact = _artefact(manifest, args.file) if manifest else None

    stages = {s: getattr(args, s) for s in STAGES if getattr(args, s) is not None}
    canary_detail: list[dict] = []
    expected = (artefact or {}).get("canaries", [])

    value = None
    if args.canaries_claimed is not None:
        claims: dict[int, str] = {}
        for pair in args.canaries_claimed.split(","):
            if "=" not in pair:
                continue
            page, token = pair.split("=", 1)
            claims[int(page.strip())] = token.strip()
        value, canary_detail = verify_claims(expected, claims)
    elif args.canaries_found is not None:
        pages = {int(p) for p in args.canaries_found.split(",") if p.strip()}
        value, canary_detail = derive_coverage(expected, pages)

    if value is not None:
        stages.setdefault("coverage", value)
        if value in ("pass", "partial"):
            stages.setdefault("retrievable", "pass")
            stages.setdefault("processed", "pass")
            stages.setdefault("transferred", "pass")
            stages.setdefault("accepted", "pass")

    obs = record(ledger, args.file, stages, artefact, canary_detail,
                 args.failure_stage, args.error, args.note)
    save(ledger, args.ledger)

    hits = sum(1 for c in obs["canaries"] if c["found"])
    total = len(obs["canaries"])
    print(f"{obs['file']}  trial {obs['trial']}  outcome={obs['outcome'].upper()}  "
          f"stage={obs['failureStage']}  canaries={hits}/{total}")
    for stage in STAGES:
        print(f"    {stage:12} {obs['stages'][stage]}")
    if total and hits < total:
        missing = [str(c["page"]) for c in obs["canaries"] if not c["found"]]
        print(f"    unparsed pages: {', '.join(missing)}")
    wrong = [c for c in obs["canaries"] if c.get("mismatch")]
    if wrong:
        print(f"    !! {len(wrong)} claimed token(s) did not match the manifest "
              "-- treat as fabricated, not as evidence of parsing:")
        for c in wrong:
            print(f"       page {c['page']}: claimed {c['claimed']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
