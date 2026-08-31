#!/usr/bin/env python3
"""Boundary planner: decides the next size worth testing, or declares convergence.

Reads an observation ledger and applies bisection between the largest passing
input and the smallest failing one. This is what stops the skill from testing
every value in a range, and -- more importantly -- it is what stops it from
stopping too early.

It also refuses to converge on unreliable evidence:

* **Non-monotonic results** (something larger passed while something smaller
  failed) mean the boundary is not a clean size threshold. That is usually
  intermittency, throttling, or a timeout -- not a product limit -- and the
  planner asks for repeat trials instead of reporting a boundary.
* **Single-trial boundaries** are reported with `repeatsRecommended`, because
  one failure can be a transient service condition.

Run standalone:

    python plan_boundary.py --ledger run.json
    python plan_boundary.py --ledger run.json --tolerance 1MB --min-trials 2
    python plan_boundary.py --ledger run.json --json

Standard library only.
"""
from __future__ import annotations

import argparse
import json

import make_test_file as mtf
import record_result as rr


def _aggregate(ledger: dict) -> dict[int, dict]:
    """Collapse trials per size. A size is only PASS if every trial passed."""
    by_size: dict[int, dict] = {}
    for obs in ledger.get("observations", []):
        size = obs.get("bytes")
        if size is None:
            continue
        slot = by_size.setdefault(size, {"size": size, "outcomes": [], "files": set()})
        slot["outcomes"].append(obs["outcome"])
        slot["files"].add(obs["file"])
    for slot in by_size.values():
        outcomes = slot["outcomes"]
        slot["trials"] = len(outcomes)
        if all(o == "pass" for o in outcomes):
            slot["verdict"] = "pass"
        elif all(o in ("fail", "partial") for o in outcomes):
            slot["verdict"] = "fail"
        else:
            slot["verdict"] = "inconsistent"
        slot["files"] = sorted(slot["files"])
    return by_size


def plan(ledger: dict, tolerance: int = 1024 * 1024, min_trials: int = 1) -> dict:
    by_size = _aggregate(ledger)
    if not by_size:
        return {
            "status": "no-data",
            "recommendation": "Build and upload a test pack first.",
            "nextSize": None,
        }

    passes = sorted(s for s, v in by_size.items() if v["verdict"] == "pass")
    fails = sorted(s for s, v in by_size.items() if v["verdict"] == "fail")
    inconsistent = sorted(s for s, v in by_size.items() if v["verdict"] == "inconsistent")

    result: dict = {
        "status": "",
        "largestPass": passes[-1] if passes else None,
        "smallestFail": fails[0] if fails else None,
        "inconsistentSizes": inconsistent,
        "nextSize": None,
        "recommendation": "",
        "repeatsRecommended": [],
    }

    if inconsistent:
        result["status"] = "inconsistent"
        result["recommendation"] = (
            "The same size both passed and failed across trials. Treat this as "
            "intermittency (throttling, timeout, transient service state), not a "
            "size limit. Repeat these sizes before concluding anything: "
            + ", ".join(mtf.human_size(s) for s in inconsistent)
        )
        result["repeatsRecommended"] = inconsistent
        return result

    # A larger input passing while a smaller one failed means size is not the
    # governing variable.
    if passes and fails and passes[-1] > fails[0]:
        result["status"] = "non-monotonic"
        result["recommendation"] = (
            f"{mtf.human_size(passes[-1])} passed but {mtf.human_size(fails[0])} "
            "failed. Size is not the governing variable here -- suspect a timeout, "
            "throttle, page/complexity limit, or transient failure. Repeat both "
            "sizes and check the failure stage before reporting a boundary."
        )
        result["repeatsRecommended"] = [fails[0], passes[-1]]
        return result

    if not fails:
        largest = passes[-1]
        result["status"] = "no-upper-bound"
        result["nextSize"] = largest * 2
        result["recommendation"] = (
            f"Everything up to {mtf.human_size(largest)} passed and nothing has "
            f"failed yet. Test {mtf.human_size(largest * 2)} to find an upper bound."
        )
        return result

    if not passes:
        smallest = fails[0]
        nxt = max(1024, smallest // 2)
        result["status"] = "no-lower-bound"
        result["nextSize"] = nxt
        result["recommendation"] = (
            f"Everything failed, smallest at {mtf.human_size(smallest)}. Test "
            f"{mtf.human_size(nxt)} to establish a working baseline -- and confirm "
            "the failure is about size at all, since a baseline that also fails "
            "means something else is wrong."
        )
        return result

    lo, hi = passes[-1], fails[0]
    gap = hi - lo
    thin = [s for s in (lo, hi) if by_size[s]["trials"] < min_trials]

    if gap <= tolerance:
        result["status"] = "converged"
        result["boundaryLow"] = lo
        result["boundaryHigh"] = hi
        result["repeatsRecommended"] = thin
        result["recommendation"] = (
            f"Boundary located between {mtf.human_size(lo)} (pass) and "
            f"{mtf.human_size(hi)} (fail); interval {mtf.human_size(gap)} is within "
            f"the {mtf.human_size(tolerance)} tolerance."
            + (
                " Repeat the boundary sizes before publishing -- they have only "
                f"{min_trials - 1} confirming trial(s)." if thin else ""
            )
        )
        return result

    result["status"] = "bisect"
    result["nextSize"] = lo + gap // 2
    result["recommendation"] = (
        f"Boundary is between {mtf.human_size(lo)} and {mtf.human_size(hi)} "
        f"({mtf.human_size(gap)} apart). Test {mtf.human_size(result['nextSize'])} next."
    )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--tolerance", default="1MB",
                    help="stop bisecting once the pass/fail gap is this small")
    ap.add_argument("--min-trials", type=int, default=2,
                    help="trials required at the boundary before it is publishable")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ledger = rr.load(args.ledger)
    out = plan(ledger, mtf.parse_size(args.tolerance), args.min_trials)

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"status: {out['status'].upper()}")
    if out.get("largestPass") is not None:
        print(f"  largest pass : {mtf.human_size(out['largestPass'])}")
    if out.get("smallestFail") is not None:
        print(f"  smallest fail: {mtf.human_size(out['smallestFail'])}")
    if out.get("nextSize"):
        print(f"  next size    : {mtf.human_size(out['nextSize'])} ({out['nextSize']} bytes)")
        print(f"\n  python build_test_pack.py --mode size --sweep {out['nextSize']}B "
              f"--out-dir pack-next")
    print(f"\n{out['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
