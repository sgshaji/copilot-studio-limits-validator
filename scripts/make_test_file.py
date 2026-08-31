#!/usr/bin/env python3
"""Generate exact-size synthetic test artefacts with non-derivable canaries.

Supports PDF, DOCX, XLSX, PPTX and TXT using only the Python standard library.
Each probed position receives an independently random canary token. The token is
stored only in the returned manifest and embedded in the artefact; it is not
derivable from the visible run id, file name, page number, or bundled code.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import sys
import zipfile
from datetime import datetime, timezone

import metrics

GENERATOR_ID = "limits-validator-artefact-generator"
GENERATOR_VERSION = "0.2.0"
FORMATS = ("pdf", "docx", "xlsx", "pptx", "txt")
_PAD_PART = "padding/pad.bin"


def new_run_id() -> str:
    return secrets.token_hex(3).upper()


def canary_pages(pages: int) -> list[int]:
    if pages <= 0:
        return []
    wanted = {1, 2, 3, 4, 5, pages}
    for frac in (0.25, 0.5, 0.75, 0.9):
        wanted.add(max(1, int(round(pages * frac))))
    return sorted(p for p in wanted if 1 <= p <= pages)


def new_canaries(pages: int) -> dict[int, str]:
    """Create independent canaries; no token is derivable from public metadata."""
    return {
        page: f"CANARY-P{page:04d}-{secrets.token_hex(12).upper()}"
        for page in canary_pages(pages)
    }


def _filler(page: int, run_id: str, width: int = 88) -> str:
    seed = hashlib.sha256(f"{run_id}|filler|{page}".encode()).hexdigest()
    return (seed * ((width // len(seed)) + 1))[:width]


def _pad_bytes(n: int, seed: str) -> bytes:
    """Deterministic high-entropy padding; canaries do not use this mechanism."""
    if n <= 0:
        return b""
    out = bytearray()
    block = hashlib.sha256(seed.encode()).digest()
    counter = 0
    while len(out) < n:
        block = hashlib.sha256(block + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


def solve_exact(builder, target: int, max_iter: int = 16):
    base = builder(0)
    if len(base) > target:
        return base, False, 0
    pad = target - len(base)
    payload = base
    for _ in range(max_iter):
        payload = builder(pad)
        delta = target - len(payload)
        if delta == 0:
            return payload, True, pad
        pad += delta
        if pad < 0:
            return builder(0), False, 0
    return payload, len(payload) == target, pad


# ------------------------------- PDF -------------------------------------

def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(pages: int, run_id: str, canaries: dict[int, str], pad_len: int) -> bytes:
    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(pages):
        p = i + 1
        lines = [
            (14, 720, "Copilot Studio Limits Validator - synthetic test artefact"),
            (11, 696, f"Page {p} of {pages}"),
            (9, 672, f"Run {run_id}"),
        ]
        if p in canaries:
            lines.extend([
                (13, 636, canaries[p]),
                (9, 612, "Retrieve this exact token only if this page is available."),
            ])
        lines.append((8, 576, _filler(p, run_id)))
        content = "\n".join(
            f"BT /F1 {size} Tf 64 {y} Td ({_pdf_escape(text)}) Tj ET"
            for size, y, text in lines
        ).encode()
        objects.append(
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
             "/Resources << /Font << /F1 3 0 R >> >> "
             f"/Contents {5 + 2 * i} 0 R >>").encode()
        )
        objects.append(
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" +
            content + b"\nendstream"
        )
    pad = _pad_bytes(pad_len, f"{run_id}|pdf-padding")
    objects.append(
        b"<< /Length " + str(len(pad)).encode() + b" >>\nstream\n" +
        pad + b"\nendstream"
    )
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


# ---------------------------- OOXML common -------------------------------

def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _zip_package(parts: dict[str, str | bytes], pad_len: int, run_id: str) -> bytes:
    buf = io.BytesIO()
    fixed = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, data.encode() if isinstance(data, str) else data)
        if pad_len:
            info = zipfile.ZipInfo(_PAD_PART, date_time=fixed)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            zf.writestr(info, _pad_bytes(pad_len, f"{run_id}|ooxml-padding"))
    return buf.getvalue()


_CT = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
_RELS = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def build_docx(pages: int, run_id: str, canaries: dict[int, str], pad_len: int) -> bytes:
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body: list[str] = []
    for p in range(1, pages + 1):
        if p > 1:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        texts = [f"Limits Validator - page {p} of {pages}", f"Run {run_id}"]
        if p in canaries:
            texts.append(canaries[p])
        texts.append(_filler(p, run_id))
        for text in texts:
            body.append(f'<w:p><w:r><w:t xml:space="preserve">{_xml(text)}</w:t></w:r></w:p>')
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>'
        + "".join(body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )
    parts = {
        "[Content_Types].xml": _CT +
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
            '<Default Extension="xml" ContentType="application/xml"/>' +
            '<Default Extension="bin" ContentType="application/octet-stream"/>' +
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": _RELS + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": document,
        "word/_rels/document.xml.rels": _RELS + "</Relationships>",
    }
    return _zip_package(parts, pad_len, run_id)


def build_xlsx(pages: int, run_id: str, canaries: dict[int, str], pad_len: int) -> bytes:
    S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    def cell(ref: str, text: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml(text)}</t></is></c>'
    rows = [f'<row r="1">{cell("A1", "position")}{cell("B1", "canary")}{cell("C1", "filler")}</row>']
    for p in range(1, pages + 1):
        r = p + 1
        rows.append(f'<row r="{r}">{cell(f"A{r}", str(p))}{cell(f"B{r}", canaries.get(p, ""))}{cell(f"C{r}", _filler(p, run_id))}</row>')
    sheet = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{S}"><sheetData>{"".join(rows)}</sheetData></worksheet>'
    workbook = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{S}" xmlns:r="{_R}"><sheets><sheet name="canaries" sheetId="1" r:id="rId1"/></sheets></workbook>'
    parts = {
        "[Content_Types].xml": _CT +
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
            '<Default Extension="xml" ContentType="application/xml"/>' +
            '<Default Extension="bin" ContentType="application/octet-stream"/>' +
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": _RELS + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": _RELS + f'<Relationship Id="rId1" Type="{_R}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    return _zip_package(parts, pad_len, run_id)


_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _ppt_textbox(idx: int, y: int, text: str, size: int = 1600) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{idx}" name="tb{idx}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="457200" y="{y}"/><a:ext cx="8229600" cy="650000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="{size}"/>'
        f'<a:t>{_xml(text)}</a:t></a:r></a:p></p:txBody></p:sp>'
    )


def _ppt_slide(p: int, pages: int, run_id: str, canary: str | None) -> str:
    shapes = [
        _ppt_textbox(2, 400000, f"Limits Validator - slide {p} of {pages}", 2000),
        _ppt_textbox(3, 1200000, f"Run {run_id}", 1200),
    ]
    if canary:
        shapes.append(_ppt_textbox(4, 2000000, canary, 1500))
    shapes.append(_ppt_textbox(5, 3000000, _filler(p, run_id, 60), 900))
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">' 
        '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        + "".join(shapes) + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    )


def build_pptx(pages: int, run_id: str, canaries: dict[int, str], pad_len: int) -> bytes:
    slide_ids = "".join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1, pages + 1))
    pres = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}"><p:sldIdLst>{slide_ids}</p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    pres_rels = "".join(f'<Relationship Id="rId{i}" Type="{_R}/slide" Target="slides/slide{i}.xml"/>' for i in range(1, pages + 1))
    ct_overrides = "".join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, pages + 1))
    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": _CT +
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
            '<Default Extension="xml" ContentType="application/xml"/>' +
            '<Default Extension="bin" ContentType="application/octet-stream"/>' +
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>' +
            ct_overrides + '</Types>',
        "_rels/.rels": _RELS + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
        "ppt/presentation.xml": pres,
        "ppt/_rels/presentation.xml.rels": _RELS + pres_rels + '</Relationships>',
    }
    for p in range(1, pages + 1):
        parts[f"ppt/slides/slide{p}.xml"] = _ppt_slide(p, pages, run_id, canaries.get(p))
    return _zip_package(parts, pad_len, run_id)


# ------------------------------- TXT -------------------------------------

def build_txt(pages: int, run_id: str, canaries: dict[int, str], pad_len: int) -> bytes:
    lines: list[str] = []
    for p in range(1, pages + 1):
        lines.append(f"--- position {p} of {pages} (run {run_id}) ---")
        if p in canaries:
            lines.append(canaries[p])
        lines.append(_filler(p, run_id))
    body = ("\n".join(lines) + "\n").encode()
    if pad_len:
        body += ("X" * pad_len).encode()
    return body


_BUILDERS = {
    "pdf": build_pdf,
    "docx": build_docx,
    "xlsx": build_xlsx,
    "pptx": build_pptx,
    "txt": build_txt,
}


def minimum_size(fmt: str, pages: int) -> int:
    fmt = fmt.lower()
    if fmt not in _BUILDERS:
        raise ValueError(f"unsupported format {fmt!r}")
    # Placeholder canaries have the same fixed length as real canaries.
    canaries = {p: f"CANARY-P{p:04d}-" + "A" * 24 for p in canary_pages(pages)}
    return len(_BUILDERS[fmt](pages, "ABCDEF", canaries, 0))


def run(fmt: str, target_bytes: int, pages: int = 10, run_id: str | None = None,
        out_path: str | None = None) -> dict:
    fmt = fmt.lower()
    if fmt not in _BUILDERS:
        raise ValueError(f"unsupported format {fmt!r}; expected {', '.join(FORMATS)}")
    if pages < 1:
        raise ValueError("pages must be >= 1")
    if target_bytes < 1:
        raise ValueError("target size must be positive")
    rid = run_id or new_run_id()
    canaries = new_canaries(pages)
    builder = _BUILDERS[fmt]
    payload, exact, pad = solve_exact(lambda n: builder(pages, rid, canaries, n), target_bytes)
    entry = {
        "file": os.path.basename(out_path) if out_path else None,
        "format": fmt,
        "runId": rid,
        "pages": pages,
        "targetBytes": target_bytes,
        "actualBytes": len(payload),
        "exactSize": exact,
        "paddingBytes": pad,
        "minimumBytes": None if exact else len(builder(pages, rid, canaries, 0)),
        "canaries": [{"page": p, "token": canaries[p]} for p in sorted(canaries)],
        "generator": {"id": GENERATOR_ID, "version": GENERATOR_VERSION},
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if out_path:
        with open(out_path, "wb") as fh:
            fh.write(payload)
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--format", required=True, choices=FORMATS)
    size = ap.add_mutually_exclusive_group(required=True)
    size.add_argument("--size", help="e.g. 49MB, 512KB")
    size.add_argument("--size-bytes", type=int)
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--run-id")
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest")
    args = ap.parse_args(argv)
    target = args.size_bytes if args.size_bytes is not None else metrics.parse_bytes(args.size)
    entry = run(args.format, target, args.pages, args.run_id, args.out)
    if args.manifest:
        with open(args.manifest, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2)
    status = "exact" if entry["exactSize"] else "MINIMUM-EXCEEDS-TARGET"
    print(f"{args.out}  {args.format}  {metrics.human_bytes(entry['actualBytes'])}  {status}  pages={args.pages}  canaries={len(entry['canaries'])}")
    if not entry["exactSize"]:
        print(f"structural minimum is {entry['minimumBytes']} bytes", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
