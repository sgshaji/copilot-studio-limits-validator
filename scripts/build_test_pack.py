#!/usr/bin/env python3
"""Batched test-pack builder for Copilot Studio limit validation.

A skill runs *inside* the agent, but file upload happens *before* the agent is
invoked -- so the agent cannot upload artefacts to itself. Testing a boundary
one file at a time would mean a human round trip per probe, and nobody
finishes that.

This script front-loads the whole sweep instead: generate every artefact in
one run, hand the folder to the human **once**, then probe all of them
autonomously. N round trips collapse to 1.

Run standalone:

    # size sweep around a documented 50 MB limit
    python build_test_pack.py --mode size --around 50MB --format pdf --pages 60 \
        --out-dir pack

    # explicit sizes
    python build_test_pack.py --mode size --sweep 1MB,5MB,10MB,25MB \
        --format docx --out-dir pack

    # page-count sweep (each file as small as its page count allows)
    python build_test_pack.py --mode pages --sweep 10,50,100,250,500 \
        --format pdf --out-dir pack

    # same size across every format, to compare per-format handling
    python build_test_pack.py --mode formats --size 10MB --out-dir pack

    # N small files, to find the attachment-count limit
    python build_test_pack.py --mode count --count 20 --format pdf --out-dir pack

Writes the artefacts, a machine-readable `manifest.json`, and an `UPLOAD-ME.md`
containing the exact human instructions for the single upload step.

Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import make_test_file as mtf

BUILDER_ID = "limits-validator-test-pack"
BUILDER_VERSION = "0.1.0"

MODES = ("size", "pages", "formats", "count")


def sweep_around(centre: int) -> list[int]:
    """Sizes bracketing a suspected limit: well below, just below, at, just
    above, well above. `step` is 1 MB or 2% of the centre, whichever is larger,
    so the pack stays informative at both small and large scales."""
    step = max(1024 * 1024, int(centre * 0.02))
    raw = [
        int(centre * 0.2),
        int(centre * 0.8),
        centre - step,
        centre,
        centre + step,
        int(centre * 1.2),
    ]
    return sorted({s for s in raw if s > 0})


def _label(n: int) -> str:
    if n % (1024 ** 2) == 0:
        return f"{n // 1024 ** 2}MB"
    if n % 1024 == 0:
        return f"{n // 1024}KB"
    return f"{n}B"


def _pages_for(fmt: str, target: int, requested: int) -> int:
    """Never ask for more pages than the target size can structurally hold."""
    if requested > 0:
        return requested
    return 10


def artefact_run_id(pack_id: str, name: str) -> str:
    """Each artefact gets its own run id, so canary tokens are unique per file.

    Without this every file in a pack would carry identical tokens and a
    retrieved token could not be attributed to the file it came from --
    which is exactly what attachment-count and per-format tests need to know.
    """
    return hashlib.sha256(f"{pack_id}|{name}".encode()).hexdigest()[:6].upper()


def build(mode: str, out_dir: str, fmt: str = "pdf", sizes: list[int] | None = None,
          pages_list: list[int] | None = None, pages: int = 0, size: int = 0,
          count: int = 0, run_id: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    rid = run_id or mtf.new_run_id()
    entries: list[dict] = []
    skipped: list[dict] = []

    def emit(f_fmt: str, target: int, n_pages: int, name: str) -> None:
        path = os.path.join(out_dir, name)
        try:
            entry = mtf.run(f_fmt, target, n_pages, artefact_run_id(rid, name), path)
        except ValueError as exc:
            skipped.append({"file": name, "reason": str(exc)})
            return
        if not entry["exactSize"]:
            os.remove(path)
            skipped.append({
                "file": name,
                "reason": (
                    f"{n_pages} pages need at least {entry['minimumBytes']} bytes; "
                    f"cannot produce {target}"
                ),
            })
            return
        entries.append(entry)

    if mode == "size":
        for target in sizes or []:
            emit(fmt, target, _pages_for(fmt, target, pages),
                 f"{fmt}-{_label(target)}.{fmt}")

    elif mode == "pages":
        for n in pages_list or []:
            # Smallest artefact that holds n pages: probe the structural floor,
            # then round up so the size stays a clean, reportable number.
            name = f"{fmt}-{n}pages.{fmt}"
            floor = len(mtf._BUILDERS[fmt](n, artefact_run_id(rid, name), 0))
            target = size if size else ((floor // 1024) + 1) * 1024
            emit(fmt, target, n, name)

    elif mode == "formats":
        for f_fmt in mtf.FORMATS:
            emit(f_fmt, size, _pages_for(f_fmt, size, pages),
                 f"{f_fmt}-{_label(size)}.{f_fmt}")

    elif mode == "count":
        target = size or 64 * 1024
        for i in range(1, count + 1):
            emit(fmt, target, _pages_for(fmt, target, pages),
                 f"{fmt}-{i:03d}-of-{count:03d}.{fmt}")

    else:
        raise ValueError(f"unknown mode {mode!r}")

    return {
        "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION},
        "packId": rid,
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artefactCount": len(entries),
        "artefacts": entries,
        "skipped": skipped,
    }


UPLOAD_TEMPLATE = """# Upload instructions -- run {run_id}

This pack was generated in one batch **so you only have to upload once**.

## What to do

1. Attach **all {count} files** in `{out_dir}` to the agent in a single turn if
   the channel allows it. If it does not, attach them in as few turns as
   possible and tell the agent which files went in which turn.
2. Note anything the **client** rejected before sending -- a file greyed out,
   an error toast, an attachment silently dropped. That is a real observation
   ("failure stage: client validation") and the agent cannot see it.
3. Tell the agent you have finished uploading.

The agent then probes each artefact by asking for its canary tokens, and
records which lifecycle stage each file reached.

## Do not

- Rename the files. The agent matches them to the manifest by name.
- Open and re-save them in Office. That rewrites the package and changes the
  byte size, which invalidates the size measurement.
- Convert or compress them.

## Files in this pack

{table}

## What the canaries are for

Each artefact carries unguessable tokens at known page positions. Asking a
model "can you read the end of this document?" proves nothing -- it will
produce something plausible. Asking for the exact token on a named page
cannot be answered by guessing, so a missing token is real evidence that the
page was never parsed.

{skipped_block}"""


def write_upload_instructions(manifest: dict, out_dir: str) -> str:
    rows = ["| File | Format | Size | Pages | Canaries |",
            "| --- | --- | ---: | ---: | ---: |"]
    for a in manifest["artefacts"]:
        rows.append(
            f"| `{a['file']}` | {a['format']} | {mtf.human_size(a['actualBytes'])} "
            f"| {a['pages']} | {len(a['canaries'])} |"
        )
    skipped_block = ""
    if manifest["skipped"]:
        lines = "\n".join(f"- `{s['file']}` -- {s['reason']}" for s in manifest["skipped"])
        skipped_block = f"## Not generated\n\n{lines}\n"

    text = UPLOAD_TEMPLATE.format(
        run_id=manifest["packId"],
        count=manifest["artefactCount"],
        out_dir=out_dir,
        table="\n".join(rows),
        skipped_block=skipped_block,
    )
    path = os.path.join(out_dir, "UPLOAD-ME.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write_probe_sheet(manifest: dict, out_dir: str) -> str:
    """A token-free worksheet: which pages to probe, with the answers withheld.

    `manifest.json` contains the expected tokens, so an agent that reads it
    before probing can echo them back without ever looking at the document.
    This sheet lists only the *positions*, so the agent has to actually read
    the artefact. `record_result.py --canaries-claimed` then scores what it
    reports against the manifest.
    """
    lines = [
        f"# Probe sheet -- pack {manifest['packId']}",
        "",
        "For each artefact below, ask the agent for the **exact canary token** on "
        "each listed page, then record what it reports with:",
        "",
        "```",
        "python record_result.py --ledger run.json --manifest manifest.json \\",
        '    --file <artefact> --canaries-claimed "1=<token>,5=<token>,..."',
        "```",
        "",
        "Do **not** read `manifest.json` before probing -- it holds the expected "
        "tokens, and an agent that has seen them can report them without ever "
        "opening the document. The tokens are deliberately withheld here.",
        "",
    ]
    for a in manifest["artefacts"]:
        pages = ", ".join(str(c["page"]) for c in a["canaries"])
        lines.append(
            f"- `{a['file']}` -- {mtf.human_size(a['actualBytes'])}, "
            f"{a['pages']} pages. Probe pages: {pages}"
        )
    lines.append("")
    path = os.path.join(out_dir, "probe-sheet.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="size", choices=MODES)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--format", default="pdf", choices=mtf.FORMATS)
    ap.add_argument("--sweep", help="comma-separated sizes (mode=size) or page counts (mode=pages)")
    ap.add_argument("--around", help="suspected limit; auto-brackets it (mode=size)")
    ap.add_argument("--size", help="fixed size for mode=formats / count")
    ap.add_argument("--pages", type=int, default=0, help="pages per artefact")
    ap.add_argument("--count", type=int, default=10, help="file count for mode=count")
    ap.add_argument("--run-id", help="reuse a run id so canary tokens stay stable")
    args = ap.parse_args(argv)

    sizes: list[int] = []
    pages_list: list[int] = []
    if args.mode == "size":
        if args.around:
            sizes = sweep_around(mtf.parse_size(args.around))
        elif args.sweep:
            sizes = [mtf.parse_size(s) for s in args.sweep.split(",") if s.strip()]
        else:
            ap.error("mode=size needs --around or --sweep")
    elif args.mode == "pages":
        if not args.sweep:
            ap.error("mode=pages needs --sweep, e.g. --sweep 10,50,100,250")
        pages_list = [int(s) for s in args.sweep.split(",") if s.strip()]
    elif args.mode in ("formats", "count") and not args.size:
        if args.mode == "formats":
            ap.error("mode=formats needs --size")

    manifest = build(
        args.mode, args.out_dir, args.format, sizes, pages_list, args.pages,
        mtf.parse_size(args.size) if args.size else 0, args.count, args.run_id,
    )

    with open(os.path.join(args.out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    write_upload_instructions(manifest, args.out_dir)
    write_probe_sheet(manifest, args.out_dir)

    print(f"pack {manifest['packId']}  mode={manifest['mode']}  "
          f"{manifest['artefactCount']} artefact(s) -> {args.out_dir}")
    for a in manifest["artefacts"]:
        print(f"  {a['file']:36} {mtf.human_size(a['actualBytes']):>10}  "
              f"pages={a['pages']:<5} run={a['runId']}")
    for s in manifest["skipped"]:
        print(f"  SKIPPED {s['file']}: {s['reason']}")
    print(f"\nNext: hand {args.out_dir}/UPLOAD-ME.md to the user, then probe canaries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
