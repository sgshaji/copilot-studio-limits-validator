#!/usr/bin/env python3
"""Plan the next bounded validation probe for any numeric metric."""
from __future__ import annotations

import argparse
import json

import metrics
import record_result as rr


def _aggregate(ledger: dict) -> dict[float, dict]:
    by_value: dict[float, dict] = {}
    for obs in ledger.get("observations", []):
        metric = obs.get("metric") or {}
        value = metric.get("value")
        if not isinstance(value, (int, float)):
            continue
        value = float(value)
        slot = by_value.setdefault(value, {"value": value, "outcomes": [], "subjects": set()})
        slot["outcomes"].append(obs.get("outcome", "inconclusive"))
        slot["subjects"].add(obs.get("subject", ""))
    for slot in by_value.values():
        outcomes = slot["outcomes"]
        slot["trials"] = len(outcomes)
        if outcomes and all(o == "pass" for o in outcomes):
            slot["verdict"] = "pass"
        elif outcomes and all(o in ("fail", "partial") for o in outcomes):
            slot["verdict"] = "fail"
        else:
            slot["verdict"] = "inconsistent"
        slot["subjects"] = sorted(slot["subjects"])
    return by_value


def plan(ledger: dict, tolerance: float | None = None, min_trials: int = 2) -> dict:
    unit = ledger.get("metric", {}).get("unit", "units")
    tolerance = metrics.default_tolerance(unit) if tolerance is None else float(tolerance)
    by_value = _aggregate(ledger)
    if not by_value:
        return {
            "status": "no-data", "metric": ledger.get("metric", {}),
            "recommendation": "Record at least one numeric observation first.",
            "nextValue": None,
        }

    passes = sorted(v for v, item in by_value.items() if item["verdict"] == "pass")
    fails = sorted(v for v, item in by_value.items() if item["verdict"] == "fail")
    inconsistent = sorted(v for v, item in by_value.items() if item["verdict"] == "inconsistent")
    result = {
        "status": "", "metric": ledger.get("metric", {}),
        "largestPass": passes[-1] if passes else None,
        "smallestFail": fails[0] if fails else None,
        "inconsistentValues": inconsistent, "nextValue": None,
        "repeatsRecommended": [], "recommendation": "",
    }

    if inconsistent:
        result["status"] = "inconsistent"
        result["repeatsRecommended"] = inconsistent
        result["recommendation"] = (
            "The same test value produced different outcomes across trials. Treat this as intermittency or another governing variable, not a clean limit. Repeat: "
            + ", ".join(metrics.format_metric(v, unit) for v in inconsistent)
        )
        return result

    if passes and fails and passes[-1] > fails[0]:
        result["status"] = "non-monotonic"
        result["repeatsRecommended"] = [fails[0], passes[-1]]
        result["recommendation"] = (
            f"{metrics.format_metric(passes[-1], unit)} passed while "
            f"{metrics.format_metric(fails[0], unit)} failed. The selected metric is not behaving monotonically. Repeat both values and investigate confounders before reporting a boundary."
        )
        return result

    if not passes:
        result["status"] = "no-lower-bound"
        result["recommendation"] = (
            "No working baseline has been demonstrated. Test a smaller, known-safe value. If that also fails, stop treating this as a boundary problem and investigate configuration or capability support."
        )
        return result

    if not fails:
        result["status"] = "no-upper-bound"
        result["recommendation"] = (
            "All tested values passed. Do not automatically keep doubling or expanding the workload. Choose a new upper bracket from official guidance or an explicit user-approved safe cap, then test within that bounded range."
        )
        return result

    lo, hi = passes[-1], fails[0]
    gap = hi - lo
    thin = [v for v in (lo, hi) if by_value[v]["trials"] < min_trials]
    if gap <= tolerance:
        result["status"] = "converged"
        result["boundaryLow"] = lo
        result["boundaryHigh"] = hi
        result["repeatsRecommended"] = thin
        result["recommendation"] = (
            f"Boundary located between {metrics.format_metric(lo, unit)} (pass) and "
            f"{metrics.format_metric(hi, unit)} (fail)."
            + (" Repeat both boundary values before publishing." if thin else "")
        )
        return result

    next_value = metrics.midpoint(lo, hi, unit)
    if next_value <= lo:
        next_value = lo + 1
    if next_value >= hi:
        next_value = hi - 1
    result["status"] = "bisect"
    result["nextValue"] = next_value
    result["recommendation"] = (
        f"Boundary remains between {metrics.format_metric(lo, unit)} and "
        f"{metrics.format_metric(hi, unit)}. Test {metrics.format_metric(next_value, unit)} next while holding all other variables constant."
    )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--tolerance", help="numeric tolerance in the ledger unit; byte metrics also accept 1MB, 512KB, etc.")
    ap.add_argument("--min-trials", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ledger = rr.load(args.ledger)
    unit = ledger.get("metric", {}).get("unit", "units")
    tolerance = None if args.tolerance is None else metrics.parse_metric(args.tolerance, unit)
    out = plan(ledger, tolerance, args.min_trials)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"status: {out['status'].upper()}")
        if out.get("largestPass") is not None:
            print(f"largest pass : {metrics.format_metric(out['largestPass'], unit)}")
        if out.get("smallestFail") is not None:
            print(f"smallest fail: {metrics.format_metric(out['smallestFail'], unit)}")
        if out.get("nextValue") is not None:
            print(f"next value   : {metrics.format_metric(out['nextValue'], unit)}")
        print(out["recommendation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
