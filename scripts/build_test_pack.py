#!/usr/bin/env python3
"""Build controlled Copilot Studio limit-validation test packs.

Modes:
  size     vary bytes while holding page count constant
  pages    vary page count while holding file size constant
  count    create separate attachment-count scenarios (one conversation each)

Format is a dimension to hold constant, not a metric to sweep: to compare
formats, run the same sweep once per --format and compare the ledgers.

Artefacts are written to <out-dir>/upload/ so the upload set is unambiguous.
The manifest stores canary digests, never tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone

import make_test_file as mtf
import metrics

BUILDER_ID = "limits-validator-test-pack"
BUILDER_VERSION = "0.3.0"
UPLOAD_DIR = "upload"
# The agent sandbox is small and the pack is usually copied once more when it is
# handed to the user, so a pack needs materially more free space than its own
# size. Refusing up front beats a half-written pack or an out-of-disk crash.
SPACE_FACTOR = 1.5
SPACE_MARGIN = 64 * 1024 ** 2
MODES = ("size", "pages", "count")


def sweep_around(centre: int) -> list[int]:
    step = max(1024 * 1024, int(centre * 0.02))
    raw = [int(centre * 0.2), int(centre * 0.8), centre - step,
           centre, centre + step, int(centre * 1.2)]
    return sorted({s for s in raw if s > 0})


def _label_bytes(n: int) -> str:
    if n % (1024 ** 2) == 0:
        return f"{n // 1024 ** 2}MiB"
    if n % 1024 == 0:
        return f"{n // 1024}KiB"
    return f"{n}B"


def _artifact_run_id(pack_id: str, name: str) -> str:
    # Public attribution id only. Canary values are independently random.
    return hashlib.sha256(f"{pack_id}|{name}".encode()).hexdigest()[:6].upper()


def _round_up(n: int, quantum: int = 1024) -> int:
    return ((n + quantum - 1) // quantum) * quantum


def planned_bytes(mode: str, sizes=None, pages_list=None, counts=None,
                  fixed_size: int = 0) -> int:
    """Total bytes the pack will occupy, before anything is written."""
    if mode == "size":
        return sum(sizes or [])
    if mode == "pages":
        return (fixed_size or 0) * len(pages_list or [])
    if mode == "count":
        return (fixed_size or 32 * 1024) * sum(counts or [])
    return 0


def check_capacity(out_dir: str, planned: int, max_total: int = 0) -> None:
    """Refuse a pack that will not fit, with the arithmetic and a way forward.

    This skill measures limits; running into an undocumented one of its own is
    an avoidable irony. The failure mode being prevented is real: a four-path
    comparison at 120 MiB per path fills a 900 MB sandbox.
    """
    if max_total and planned > max_total:
        raise ValueError(
            f"pack would occupy {metrics.human_bytes(planned)}, above the "
            f"--max-total-bytes cap of {metrics.human_bytes(max_total)}. "
            "Reduce the sweep, or raise the cap deliberately."
        )
    free = shutil.disk_usage(out_dir).free
    needed = int(planned * SPACE_FACTOR) + SPACE_MARGIN
    if needed > free:
        raise ValueError(
            f"pack would occupy {metrics.human_bytes(planned)} and needs about "
            f"{metrics.human_bytes(needed)} of working space, but only "
            f"{metrics.human_bytes(free)} is free.\n"
            "Build one pack at a time rather than several at once: comparing "
            "paths means one sweep per path, generated and uploaded in turn, "
            "not all of them up front. Or narrow the sweep to a three-point "
            "bracket (below, at, above) and bisect from there. Artefacts are "
            "uploaded one per turn anyway, so generating the whole matrix in "
            "advance buys nothing."
        )


def build(mode: str, out_dir: str, fmt: str = "pdf",
          sizes: list[int] | None = None, pages_list: list[int] | None = None,
          pages: int = 10, fixed_size: int = 0,
          counts: list[int] | None = None, run_id: str | None = None,
          max_total_bytes: int = 0, skip_space_check: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    if not skip_space_check:
        check_capacity(out_dir,
                       planned_bytes(mode, sizes, pages_list, counts, fixed_size),
                       max_total_bytes)
    upload_dir = os.path.join(out_dir, UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    pack_id = run_id or mtf.new_run_id()
    artefacts: list[dict] = []
    scenarios: list[dict] = []
    skipped: list[dict] = []

    def emit(name: str, f_fmt: str, target: int, n_pages: int,
             metric: dict, scenario: str | None = None) -> dict | None:
        path = os.path.join(upload_dir, name)
        entry = mtf.run(f_fmt, target, n_pages, _artifact_run_id(pack_id, name), path)
        if not entry["exactSize"]:
            if os.path.exists(path):
                os.remove(path)
            skipped.append({"file": name, "reason": f"structural minimum {entry['minimumBytes']} bytes exceeds target {target}"})
            return None
        entry["metric"] = metric
        if scenario:
            entry["scenario"] = scenario
        artefacts.append(entry)
        return entry

    if mode == "size":
        metric_name, metric_unit = "file-size", "bytes"
        for target in sizes or []:
            emit(f"{fmt}-{_label_bytes(target)}.{fmt}", fmt, target, pages,
                 {"name": metric_name, "value": target, "unit": metric_unit})

    elif mode == "pages":
        metric_name, metric_unit = "page-count", "pages"
        requested = pages_list or []
        if not requested:
            raise ValueError("page mode requires at least one page count")
        largest_floor = max(mtf.minimum_size(fmt, n) for n in requested)
        # Hold file size constant. If the caller does not choose a size, use one
        # target that can structurally contain the largest requested document.
        target = fixed_size or _round_up(largest_floor + 16 * 1024, 1024)
        if target < largest_floor:
            raise ValueError(
                f"--size {target} bytes is too small for the largest page-count case; "
                f"need at least {largest_floor} bytes. Increase --size so page count is "
                "the only variable."
            )
        for n in requested:
            emit(f"{fmt}-{n:05d}pages.{fmt}", fmt, target, n,
                 {"name": metric_name, "value": n, "unit": metric_unit})

    elif mode == "count":
        metric_name, metric_unit = "attachment-count", "attachments"
        requested = counts or []
        if not requested:
            raise ValueError("count mode requires one or more counts")
        target = fixed_size or 32 * 1024
        for count in requested:
            if count < 1:
                raise ValueError("attachment counts must be >= 1")
            scenario_id = f"count-{count:04d}"
            members: list[str] = []
            for i in range(1, count + 1):
                name = f"{scenario_id}-{i:04d}.{fmt}"
                entry = emit(name, fmt, target, 1,
                             {"name": metric_name, "value": count, "unit": metric_unit},
                             scenario_id)
                if entry:
                    members.append(name)
            scenarios.append({
                "id": scenario_id,
                "metric": {"name": metric_name, "value": count, "unit": metric_unit},
                "files": members,
                "totalBytes": sum(a["actualBytes"] for a in artefacts if a.get("scenario") == scenario_id),
            })
    else:
        raise ValueError(f"unknown mode {mode!r}")

    return {
        "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION},
        "packId": pack_id,
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metric": {"name": metric_name, "unit": metric_unit},
        "artefactCount": len(artefacts),
        "totalBytes": sum(a["actualBytes"] for a in artefacts),
        "artefacts": artefacts,
        "scenarios": scenarios,
        "skipped": skipped,
    }


def write_probe_sheet(manifest: dict, out_dir: str) -> str:
    lines = [
        f"# Probe sheet — pack {manifest['packId']}", "",
        "This sheet contains probe positions but **not** expected tokens.",
        "The manifest stores only SHA-256 digests, so it holds no recoverable answer; keeping it aside until claims are captured is defence in depth, not the load-bearing control.", "",
        "**Path integrity:** ask for the tokens only through the path under test. Do not open, parse, unzip, or grep the artefact with runtime code unless that runtime access *is* the path being measured.", "",
    ]
    if manifest["mode"] == "count":
        lines.append("## Attachment-count scenarios")
        lines.append("")
        lines.append("Test each scenario in its own **fresh conversation**. Attachments from an earlier turn can remain in context and inflate the count actually in play.")
        lines.append("")
        by_file = {a["file"]: a for a in manifest["artefacts"]}
        for s in manifest["scenarios"]:
            lines.append(f"### `{s['id']}` — {int(s['metric']['value'])} attachments")
            for name in s["files"]:
                pages = ", ".join(str(c["page"]) for c in by_file[name]["canaries"])
                lines.append(f"- `{name}` — probe position(s): {pages}")
            lines.append("")
    else:
        for a in manifest["artefacts"]:
            pages = ", ".join(str(c["page"]) for c in a["canaries"])
            metric = a["metric"]
            value = metrics.format_metric(metric["value"], metric["unit"])
            lines.append(f"- `{a['file']}` — test value: {value}; probe positions: {pages}")
    lines.extend([
        "", "### Evidence rule", "",
        "A correct token proves the agent obtained content at that position by **some** route available to it during this probe. It proves the tested path specifically only if no alternate access route (runtime file reads, unzipping, PDF libraries, filesystem search) was available or used.", "",
        "A missing token proves only that end-to-end availability was **not demonstrated**; it does not, by itself, identify parsing, indexing, retrieval, or context handling as the failing stage.",
    ])
    path = os.path.join(out_dir, "probe-sheet.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def write_upload_instructions(manifest: dict, out_dir: str) -> str:
    lines = [
        f"# Upload instructions — pack {manifest['packId']}", "",
        f"Generated artefacts: **{manifest['artefactCount']}**  ",
        f"Total generated bytes: **{metrics.human_bytes(manifest['totalBytes'])}**", "",
        f"Artefacts are in `{UPLOAD_DIR}/`. Synthetic content only. Do not rename, re-save, convert, or compress the files.", "",
        "## Path integrity", "",
        "Retrieve canary tokens only through the path under test. If the agent can read the artefact with runtime code (Python, unzip, PDF libraries, filesystem search), a correct token no longer proves the tested path carried the content. Either disable that route or record the run as not path-attested.", "",
    ]
    if manifest["mode"] == "count":
        lines.extend([
            "## Important: count tests are separate scenarios", "",
            "Test each attachment count in its own **fresh conversation**, not merely a new turn: files attached earlier can stay in context and change the count actually under test. Upload only the files belonging to one scenario, record whether the client accepted all of them, then start a new conversation for the next scenario.", "",
        ])
        for s in manifest["scenarios"]:
            lines.append(f"- `{s['id']}`: {len(s['files'])} files, {metrics.human_bytes(s['totalBytes'])}")
    else:
        lines.extend([
            "## Upload one artefact per turn", "",
            "Attach exactly one artefact per conversation turn, and use a fresh conversation for the values that decide the boundary.", "",
            "Uploading the sweep together changes three variables at once — per-file size, attachment count, and total turn payload — so a failure could not be attributed to any of them. Batch generation is the labour saving; batch uploading destroys the measurement.", "",
            "Record any file the client rejects before send: the agent cannot observe a file it never received.", "",
        ])
    lines.extend([
        "", "After upload, use `probe-sheet.md` to request exact canary values. Keep `manifest.json` hidden from the model until claims have been captured and are ready for verification.",
    ])
    path = os.path.join(out_dir, "UPLOAD-ME.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=MODES, default="size")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--format", choices=mtf.FORMATS, default="pdf",
                    help="format to hold constant; to compare formats run this sweep once per format and compare ledgers")
    ap.add_argument("--sweep", help="comma-separated sizes, page counts, or attachment counts")
    ap.add_argument("--around", help="suspected byte-size limit for mode=size")
    ap.add_argument("--size", help="fixed artefact size for pages/count modes")
    ap.add_argument("--pages", type=int, default=10, help="fixed page/slide/row count for size mode")
    ap.add_argument("--count", type=int, help="single attachment-count scenario; --sweep is preferred")
    ap.add_argument("--run-id")
    ap.add_argument("--max-total-bytes",
                    help="refuse to build a pack larger than this, e.g. 256MB")
    ap.add_argument("--skip-space-check", action="store_true",
                    help="build even when free space looks insufficient")
    args = ap.parse_args(argv)

    sizes: list[int] = []
    pages_list: list[int] = []
    counts: list[int] = []
    if args.mode == "size":
        if args.around:
            sizes = sweep_around(metrics.parse_bytes(args.around))
        elif args.sweep:
            sizes = [metrics.parse_bytes(v) for v in args.sweep.split(",") if v.strip()]
        else:
            ap.error("size mode requires --around or --sweep")
    elif args.mode == "pages":
        if not args.sweep:
            ap.error("pages mode requires --sweep, e.g. 10,50,100,250")
        pages_list = [int(v) for v in args.sweep.split(",") if v.strip()]
    elif args.mode == "count":
        if args.sweep:
            counts = [int(v) for v in args.sweep.split(",") if v.strip()]
        elif args.count:
            counts = [args.count]
        else:
            ap.error("count mode requires --sweep or --count")

    try:
        manifest = build(
            args.mode, args.out_dir, args.format, sizes=sizes, pages_list=pages_list,
            pages=args.pages, fixed_size=metrics.parse_bytes(args.size) if args.size else 0,
            counts=counts, run_id=args.run_id,
            max_total_bytes=metrics.parse_bytes(args.max_total_bytes) if args.max_total_bytes else 0,
            skip_space_check=args.skip_space_check,
        )
    except ValueError as exc:
        ap.error(str(exc))
    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    write_upload_instructions(manifest, args.out_dir)
    write_probe_sheet(manifest, args.out_dir)

    print(f"pack {manifest['packId']}  mode={manifest['mode']}  artefacts={manifest['artefactCount']}  total={metrics.human_bytes(manifest['totalBytes'])}")
    print(f"artefacts: {os.path.join(args.out_dir, UPLOAD_DIR)}")
    print(f"next: read {os.path.join(args.out_dir, 'UPLOAD-ME.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
