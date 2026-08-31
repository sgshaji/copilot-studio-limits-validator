#!/usr/bin/env python3
"""Metric parsing/formatting helpers for Copilot Studio Limits Validator."""
from __future__ import annotations

import re

BYTE_UNITS = {
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024 ** 2,
    "MIB": 1024 ** 2,
    "GB": 1024 ** 3,
    "GIB": 1024 ** 3,
}

DISCRETE_UNITS = {
    "pages", "attachments", "files", "items", "records", "rows", "slides",
    "sources", "documents", "calls", "messages",
}


def parse_bytes(text: str) -> int:
    raw = str(text).strip().replace(",", "").replace(" ", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)", raw)
    if not match:
        raise ValueError(f"invalid byte size: {text!r}")
    value = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    if unit in {"K", "M", "G"}:
        unit += "B"
    if unit not in BYTE_UNITS:
        raise ValueError(f"unrecognised byte unit: {unit!r}")
    if value < 0:
        raise ValueError("value must be non-negative")
    return int(value * BYTE_UNITS[unit])


def parse_metric(text: str, unit: str) -> float:
    unit = unit.strip().lower()
    if unit == "bytes":
        return float(parse_bytes(text))
    raw = str(text).strip().replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{raw!r} is not a numeric {unit or 'metric'} value. This skill validates "
            "quantitative boundaries; categorical properties such as file format are "
            "dimensions to hold constant, not metrics to sweep."
        ) from None
    if value < 0:
        raise ValueError("metric value must be non-negative")
    return value


def human_bytes(value: int | float) -> str:
    n = float(value)
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GiB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.2f} KiB"
    return f"{int(n)} B"


def format_metric(value: int | float | None, unit: str) -> str:
    if value is None:
        return "not established"
    unit = (unit or "units").strip().lower()
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        # Never crash the ledger/report pipeline on an unexpected non-numeric
        # value; render it literally and let the caller judge it.
        return str(value)
    if unit == "bytes":
        return human_bytes(value)
    if unit in DISCRETE_UNITS or float(value).is_integer():
        return f"{int(value)} {unit}"
    return f"{value:g} {unit}"


def midpoint(lo: float, hi: float, unit: str) -> float:
    mid = lo + (hi - lo) / 2
    if unit.strip().lower() in DISCRETE_UNITS:
        return float(int(mid))
    return mid


def default_tolerance(unit: str) -> float:
    return float(1024 ** 2) if unit.strip().lower() == "bytes" else 1.0
