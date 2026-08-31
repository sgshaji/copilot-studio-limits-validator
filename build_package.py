#!/usr/bin/env python3
"""Build the uploadable skill package for Copilot Studio.

Produces dist/copilot-studio-limits-validator-skill-v<version>.zip containing
SKILL.md at the ZIP root alongside references/, scripts/ and assets/. A skill
package is rejected when SKILL.md is nested inside a wrapper folder, so the
layout here is the load-bearing part.

Development-only material (tests/, .github/, __pycache__/, metadata.json) is
excluded: metadata.json is the CAT submission manifest, not part of the skill
format, and the rest would be bundled into the agent for no reason.

    python build_package.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).parent.resolve()
BUNDLED = ("references", "scripts", "assets")
SKIP_PARTS = {"__pycache__", ".git", ".github", "tests", "dist"}


def version() -> str:
    with open(ROOT / "metadata.json", encoding="utf-8") as fh:
        return json.load(fh)["version"]


def members() -> list[str]:
    found = ["SKILL.md"]
    for folder in BUNDLED:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and not SKIP_PARTS.intersection(path.parts):
                found.append(path.relative_to(ROOT).as_posix())
    return found


def check(names: list[str]) -> list[str]:
    """Fail loudly rather than shipping a package the platform will reject."""
    problems = []
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        problems.append("SKILL.md has no YAML front matter")
    else:
        front = text.split("---")[1]
        name = re.search(r"^name: *(.+)$", front, re.M)
        if not name:
            problems.append("SKILL.md front matter has no name")
        elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name.group(1).strip()):
            problems.append(f"skill name {name.group(1).strip()!r} is not a lowercase slug")
        if not re.search(r"^description:", front, re.M):
            problems.append("SKILL.md front matter has no description")

    for ref in sorted(set(re.findall(r"(?:scripts|references|assets)/[A-Za-z0-9_./-]+", text))):
        if ref not in names:
            problems.append(f"SKILL.md references {ref}, which is not in the package")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", default=str(ROOT / "dist"))
    args = ap.parse_args(argv)

    names = members()
    problems = check(names)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"copilot-studio-limits-validator-skill-v{version()}.zip"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(ROOT / name, arcname=name)  # SKILL.md at the ZIP root

    print(f"{out}  ({out.stat().st_size:,} bytes, {len(names)} files)")
    for name in names:
        print(f"  {name}")
    print("\nUpload: agent > Build > Skills > Add skill > Upload a skill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
