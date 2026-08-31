#!/usr/bin/env python3
"""Calibrated test-artefact generator for Copilot Studio limit validation.

Produces a *structurally valid* PDF / DOCX / XLSX / PPTX / TXT of an **exact**
byte size, carrying unguessable **canary tokens** at known page positions.

Why canaries: asking a model "can you read the end of the document?" is not a
measurement -- the model will confabulate plausible content. A random token
cannot be guessed, so retrieving the token for a named page turns coverage
into a falsifiable observation. This is what detects *silent* truncation
(e.g. only the first N pages were actually parsed or OCR'd).

Run standalone:

    python make_test_file.py --format pdf  --size 49MB --pages 100 --out t.pdf
    python make_test_file.py --format docx --size 5MB   --pages 40  --out t.docx
    python make_test_file.py --format xlsx --size-bytes 1048576 --out t.xlsx
    python make_test_file.py --format pdf --size 10MB --pages 20 --out t.pdf \
        --manifest t.manifest.json

Sizes: `MB`/`M`/`MiB` are 1024*1024; `KB`/`K`/`KiB` are 1024. Use `--size-bytes`
for an unambiguous exact count.

Or import and call `run(...)` to get the manifest as a dict.

Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import zipfile
from datetime import datetime, timezone

GENERATOR_ID = "limits-validator-artefact-generator"
GENERATOR_VERSION = "0.1.0"

FORMATS = ("pdf", "docx", "xlsx", "pptx", "txt")

# Padding is incompressible random data stored uncompressed, so the padded size
# is predictable. Never use zeros -- deflate would collapse them.
_PAD_PART = "padding/pad.bin"


# --------------------------------------------------------------------------
# sizes
# --------------------------------------------------------------------------

_UNITS = {
    "": 1,
    "B": 1,
    "K": 1024, "KB": 1024, "KIB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
}


def parse_size(text: str) -> int:
    """Parse '49MB' / '512KB' / '1048576' into a byte count."""
    raw = str(text).strip().replace(" ", "").replace(",", "")
    if not raw:
        raise ValueError("empty size")
    idx = len(raw)
    while idx > 0 and (raw[idx - 1].isalpha()):
        idx -= 1
    number, unit = raw[:idx], raw[idx:].upper()
    if unit not in _UNITS:
        raise ValueError(f"unrecognised size unit: {unit!r}")
    value = float(number)
    if value < 0:
        raise ValueError("size must be non-negative")
    return int(value * _UNITS[unit])


def human_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.2f} KB"
    return f"{n} B"


# --------------------------------------------------------------------------
# canaries
# --------------------------------------------------------------------------

def new_run_id() -> str:
    return secrets.token_hex(3).upper()


def canary_token(run_id: str, page: int) -> str:
    """Deterministic, unguessable-without-run_id token for a page."""
    sig = hashlib.sha256(f"{run_id}|{page}".encode()).hexdigest()[:6].upper()
    return f"CANARY-{run_id}-P{page:04d}-{sig}"


def canary_pages(pages: int) -> list[int]:
    """Pages that carry a canary.

    Dense at the start (catches parsers/OCR that stop after a few pages),
    then quartiles, then the last page (catches tail truncation).
    """
    if pages <= 0:
        return []
    wanted = {1, 2, 3, 4, 5}
    for frac in (0.25, 0.5, 0.75, 0.9):
        wanted.add(max(1, int(round(pages * frac))))
    wanted.add(pages)
    return sorted(p for p in wanted if 1 <= p <= pages)


def _filler(page: int, run_id: str, width: int = 88) -> str:
    """Deterministic, non-repeating body text so pages are distinguishable."""
    seed = hashlib.sha256(f"{run_id}|filler|{page}".encode()).hexdigest()
    return (seed * ((width // len(seed)) + 1))[:width]


# --------------------------------------------------------------------------
# exact-size solver
# --------------------------------------------------------------------------

def solve_exact(builder, target: int, max_iter: int = 12):
    """Find pad_len such that len(builder(pad_len)) == target.

    len(builder(p)) is monotonic in p with slope 1 apart from occasional
    digit-width changes in length fields, so simple feedback converges fast.
    Returns (payload_bytes, exact: bool, pad_len: int).
    """
    base = builder(0)
    if len(base) > target:
        # Cannot shrink below the structural minimum.
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


def _random_bytes(n: int, seed: str) -> bytes:
    """Deterministic incompressible padding derived from a seed."""
    if n <= 0:
        return b""
    out = bytearray()
    counter = 0
    block = hashlib.sha256(seed.encode()).digest()
    while len(out) < n:
        block = hashlib.sha256(block + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_page_lines(page: int, pages: int, run_id: str, carries: bool) -> list[str]:
    lines = [
        (14, 720, "Copilot Studio Limits Validator - test artefact"),
        (11, 696, f"Page {page} of {pages}"),
        (11, 672, f"Run {run_id}"),
    ]
    if carries:
        lines.append((13, 636, canary_token(run_id, page)))
        lines.append((9, 612, "^ retrieve this exact token to prove this page was parsed"))
    lines.append((8, 576, _filler(page, run_id)))
    return [
        f"BT /F1 {size} Tf 64 {y} Td ({_pdf_escape(text)}) Tj ET"
        for size, y, text in lines
    ]


def build_pdf(pages: int, run_id: str, pad_len: int) -> bytes:
    carrier = set(canary_pages(pages))
    objects: list[bytes] = []

    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for i in range(pages):
        page_no = i + 1
        content = "\n".join(_pdf_page_lines(page_no, pages, run_id, page_no in carrier)).encode()
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
        )

    pad = _random_bytes(pad_len, f"{run_id}|pdfpad")
    objects.append(
        b"<< /Length " + str(len(pad)).encode() + b" >>\nstream\n" + pad + b"\nendstream"
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


# --------------------------------------------------------------------------
# OOXML shared
# --------------------------------------------------------------------------

def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _zip_package(parts: dict[str, str | bytes], pad_len: int, run_id: str) -> bytes:
    import io

    buf = io.BytesIO()
    fixed = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, data.encode() if isinstance(data, str) else data)
        if pad_len > 0:
            info = zipfile.ZipInfo(_PAD_PART, date_time=fixed)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            zf.writestr(info, _random_bytes(pad_len, f"{run_id}|zippad"))
    return buf.getvalue()


_CT_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
_CT_DEFAULTS = (
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="bin" ContentType="application/octet-stream"/>'
)
_RELS_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def build_docx(pages: int, run_id: str, pad_len: int) -> bytes:
    carrier = set(canary_pages(pages))
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def para(text: str, bold: bool = False) -> str:
        rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
        return f'<w:p><w:r>{rpr}<w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r></w:p>'

    body: list[str] = []
    for page_no in range(1, pages + 1):
        if page_no > 1:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        body.append(para(f"Copilot Studio Limits Validator - page {page_no} of {pages}", True))
        body.append(para(f"Run {run_id}"))
        if page_no in carrier:
            body.append(para(canary_token(run_id, page_no), True))
            body.append(para("^ retrieve this exact token to prove this page was parsed"))
        body.append(para(_filler(page_no, run_id)))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )

    parts = {
        "[Content_Types].xml": (
            _CT_HEAD + _CT_DEFAULTS
            + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            + "</Types>"
        ),
        "_rels/.rels": (
            _RELS_HEAD
            + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="word/document.xml"/>'
            + "</Relationships>"
        ),
        "word/document.xml": document,
        "word/_rels/document.xml.rels": _RELS_HEAD + "</Relationships>",
    }
    return _zip_package(parts, pad_len, run_id)


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------

def build_xlsx(pages: int, run_id: str, pad_len: int) -> bytes:
    """`pages` maps to worksheet rows -- one logical 'page' per row block."""
    carrier = set(canary_pages(pages))
    S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def cell(ref: str, text: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(text)}</t></is></c>'

    rows = [f'<row r="1">{cell("A1", "page")}{cell("B1", "canary")}{cell("C1", "filler")}</row>']
    for page_no in range(1, pages + 1):
        r = page_no + 1
        token = canary_token(run_id, page_no) if page_no in carrier else ""
        rows.append(
            f'<row r="{r}">{cell(f"A{r}", str(page_no))}'
            f'{cell(f"B{r}", token)}{cell(f"C{r}", _filler(page_no, run_id))}</row>'
        )

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{S}"><sheetData>{"".join(rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="{S}" xmlns:r="{_R}"><sheets>'
        '<sheet name="canaries" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )

    parts = {
        "[Content_Types].xml": (
            _CT_HEAD + _CT_DEFAULTS
            + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            + "</Types>"
        ),
        "_rels/.rels": (
            _RELS_HEAD
            + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="xl/workbook.xml"/>'
            + "</Relationships>"
        ),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": (
            _RELS_HEAD
            + f'<Relationship Id="rId1" Type="{_R}/worksheet" Target="worksheets/sheet1.xml"/>'
            + "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    return _zip_package(parts, pad_len, run_id)


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _pptx_theme() -> str:
    accents = "".join(
        f'<a:accent{i}><a:srgbClr val="4472C4"/></a:accent{i}>' for i in range(1, 7)
    )
    fill = (
        '<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
    )
    line = (
        '<a:lnStyleLst>'
        + '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
        + "</a:lnStyleLst>"
    )
    effect = "<a:effectStyleLst>" + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3 + "</a:effectStyleLst>"
    bg = (
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
    )
    font = (
        '<a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<a:theme xmlns:a="{_A}" name="LimitsValidator"><a:themeElements>'
        '<a:clrScheme name="LV">'
        '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
        '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
        f"{accents}"
        '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
        '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
        f'<a:fontScheme name="LV"><a:majorFont>{font}</a:majorFont>'
        f'<a:minorFont>{font}</a:minorFont></a:fontScheme>'
        f'<a:fmtScheme name="LV">{fill}{line}{effect}{bg}</a:fmtScheme>'
        "</a:themeElements></a:theme>"
    )


def _pptx_textbox(idx: int, y_emu: int, text: str, size: int = 1800) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{idx}" name="tb{idx}"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="457200" y="{y_emu}"/>'
        '<a:ext cx="8229600" cy="700000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/><a:p><a:r>'
        f'<a:rPr lang="en-US" sz="{size}"/><a:t>{_xml_escape(text)}</a:t>'
        "</a:r></a:p></p:txBody></p:sp>"
    )


def _pptx_slide(page_no: int, pages: int, run_id: str, carries: bool) -> str:
    shapes = [
        _pptx_textbox(2, 400000, f"Limits Validator - slide {page_no} of {pages}", 2000),
        _pptx_textbox(3, 1200000, f"Run {run_id}", 1400),
    ]
    if carries:
        shapes.append(_pptx_textbox(4, 2000000, canary_token(run_id, page_no), 1600))
        shapes.append(_pptx_textbox(5, 2800000, "^ retrieve this exact token", 1100))
    shapes.append(_pptx_textbox(6, 3600000, _filler(page_no, run_id, 60), 900))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<p:sld xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f'{"".join(shapes)}'
        "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def _pptx_empty_tree(tag: str, extra: str = "") -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<p:{tag} xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"</p:spTree></p:cSld>{extra}</p:{tag}>"
    )


def build_pptx(pages: int, run_id: str, pad_len: int) -> bytes:
    carrier = set(canary_pages(pages))
    clr_map = (
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    )

    parts: dict[str, str | bytes] = {}
    ct = [
        _CT_HEAD, _CT_DEFAULTS,
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
    ]

    sld_ids, pres_rels = [], []
    for i in range(1, pages + 1):
        parts[f"ppt/slides/slide{i}.xml"] = _pptx_slide(i, pages, run_id, i in carrier)
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = (
            _RELS_HEAD
            + f'<Relationship Id="rId1" Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            + "</Relationships>"
        )
        ct.append(
            f'<Override PartName="/ppt/slides/slide{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        )
        rid = f"rId{i + 1}"
        sld_ids.append(f'<p:sldId id="{255 + i}" r:id="{rid}"/>')
        pres_rels.append(
            f'<Relationship Id="{rid}" Type="{_R}/slide" Target="slides/slide{i}.xml"/>'
        )
    ct.append("</Types>")

    parts["[Content_Types].xml"] = "".join(ct)
    parts["_rels/.rels"] = (
        _RELS_HEAD
        + f'<Relationship Id="rId1" Type="{_R}/officeDocument" Target="ppt/presentation.xml"/>'
        + "</Relationships>"
    )
    parts["ppt/presentation.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<p:presentation xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f'<p:sldIdLst>{"".join(sld_ids)}</p:sldIdLst>'
        '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    parts["ppt/_rels/presentation.xml.rels"] = (
        _RELS_HEAD
        + f'<Relationship Id="rId1" Type="{_R}/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        + "".join(pres_rels)
        + f'<Relationship Id="rId{pages + 2}" Type="{_R}/theme" Target="theme/theme1.xml"/>'
        + "</Relationships>"
    )
    parts["ppt/slideMasters/slideMaster1.xml"] = _pptx_empty_tree(
        "sldMaster",
        clr_map + '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>',
    )
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = (
        _RELS_HEAD
        + f'<Relationship Id="rId1" Type="{_R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        + f'<Relationship Id="rId2" Type="{_R}/theme" Target="../theme/theme1.xml"/>'
        + "</Relationships>"
    )
    parts["ppt/slideLayouts/slideLayout1.xml"] = _pptx_empty_tree(
        "sldLayout", '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
    ).replace("<p:sldLayout ", '<p:sldLayout type="blank" preserve="1" ')
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = (
        _RELS_HEAD
        + f'<Relationship Id="rId1" Type="{_R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
        + "</Relationships>"
    )
    parts["ppt/theme/theme1.xml"] = _pptx_theme()
    return _zip_package(parts, pad_len, run_id)


# --------------------------------------------------------------------------
# TXT
# --------------------------------------------------------------------------

def build_txt(pages: int, run_id: str, pad_len: int) -> bytes:
    carrier = set(canary_pages(pages))
    lines = []
    for page_no in range(1, pages + 1):
        lines.append(f"--- page {page_no} of {pages} (run {run_id}) ---")
        if page_no in carrier:
            lines.append(canary_token(run_id, page_no))
        lines.append(_filler(page_no, run_id))
    body = ("\n".join(lines) + "\n").encode()
    if pad_len > 0:
        chunk = _random_bytes(pad_len, f"{run_id}|txtpad").hex()[:pad_len].encode()
        body += chunk
    return body


_BUILDERS = {
    "pdf": build_pdf,
    "docx": build_docx,
    "xlsx": build_xlsx,
    "pptx": build_pptx,
    "txt": build_txt,
}


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def run(fmt: str, target_bytes: int, pages: int = 10, run_id: str | None = None,
        out_path: str | None = None) -> dict:
    """Generate one artefact. Returns its manifest entry."""
    fmt = fmt.lower()
    if fmt not in _BUILDERS:
        raise ValueError(f"unsupported format {fmt!r}; expected one of {', '.join(FORMATS)}")
    if pages < 1:
        raise ValueError("pages must be >= 1")
    rid = run_id or new_run_id()
    builder = _BUILDERS[fmt]

    payload, exact, pad = solve_exact(lambda p: builder(pages, rid, p), target_bytes)
    entry = {
        "file": os.path.basename(out_path) if out_path else None,
        "format": fmt,
        "runId": rid,
        "pages": pages,
        "targetBytes": target_bytes,
        "actualBytes": len(payload),
        "exactSize": exact,
        "paddingBytes": pad,
        "minimumBytes": None if exact else len(builder(pages, rid, 0)),
        "canaries": [
            {"page": p, "token": canary_token(rid, p)} for p in canary_pages(pages)
        ],
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
    size.add_argument("--size", help="e.g. 49MB, 512KB (MB = 1024*1024)")
    size.add_argument("--size-bytes", type=int, help="exact byte count")
    ap.add_argument("--pages", type=int, default=10,
                    help="pages / slides / rows carrying content (default 10)")
    ap.add_argument("--run-id", help="reuse a run id so canary tokens stay stable")
    ap.add_argument("--out", required=True, help="output file path")
    ap.add_argument("--manifest", help="write the manifest entry as JSON here")
    args = ap.parse_args(argv)

    target = args.size_bytes if args.size_bytes is not None else parse_size(args.size)
    entry = run(args.format, target, args.pages, args.run_id, args.out)

    if args.manifest:
        with open(args.manifest, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2)

    status = "exact" if entry["exactSize"] else "MINIMUM-EXCEEDS-TARGET"
    print(
        f"{args.out}  {entry['format']}  {human_size(entry['actualBytes'])} "
        f"({entry['actualBytes']} bytes, {status})  pages={entry['pages']}  "
        f"canaries={len(entry['canaries'])}  run={entry['runId']}"
    )
    if not entry["exactSize"]:
        print(
            f"  ! structural minimum for {entry['pages']} pages is "
            f"{entry['minimumBytes']} bytes -- reduce --pages to reach {target}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
