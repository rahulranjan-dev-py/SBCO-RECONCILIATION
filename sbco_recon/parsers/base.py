"""Shared parsing infrastructure.

Every report parser exposes:
    fingerprint(grid) -> bool          does this file look like my report type?
    extract(grid, file_name) -> ParsedReport

A "grid" is the first worksheet read as a rectangle of raw values (no header
inference), which mirrors how the legacy VBA pasted UsedRange into TEMP and then
inspected fixed cells. Parsers search for landmarks instead of trusting exact cell
positions, so minor layout drift in Finacle/APT exports doesn't break imports.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

MAX_SCAN_ROWS = 30  # landmarks (titles, dates, header rows) live near the top


@dataclass
class ParsedReport:
    report_type: str
    report_date: dt.date | None
    rows: list[dict] = field(default_factory=list)
    #: per-SOL breakdown rows, populated by parsers whose report carries SOL sections
    sol_rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ParseError(Exception):
    """Raised when a file matches a fingerprint but its content can't be extracted."""


def read_grid(path: str | Path) -> list[list[Any]]:
    """Read the first worksheet as a list of rows of raw values."""
    df = pd.read_excel(path, sheet_name=0, header=None, dtype=object)
    return df.values.tolist()


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:  # NaN — pandas' representation of an empty cell
            return ""
        if value == int(value):
            return str(int(value))
    return str(value).strip()


def find_cell(grid: list[list[Any]], pattern: str, max_rows: int = MAX_SCAN_ROWS) -> tuple[int, int] | None:
    """Locate the first cell whose text matches `pattern` (case-insensitive regex search)."""
    rx = re.compile(pattern, re.IGNORECASE)
    for r, row in enumerate(grid[:max_rows]):
        for c, val in enumerate(row):
            if rx.search(cell_text(val)):
                return r, c
    return None


def find_header_row(
    grid: list[list[Any]], required: list[str], max_rows: int = MAX_SCAN_ROWS
) -> tuple[int, dict[str, int]] | None:
    """Find the row containing all `required` header fragments.

    Returns (row_index, {fragment: column_index}).
    """
    patterns = {frag: re.compile(frag, re.IGNORECASE) for frag in required}
    for r, row in enumerate(grid[:max_rows]):
        found: dict[str, int] = {}
        for c, val in enumerate(row):
            text = cell_text(val)
            if not text:
                continue
            for frag, rx in patterns.items():
                if frag not in found and rx.search(text):
                    found[frag] = c
        if len(found) == len(required):
            return r, found
    return None


_DATE_RX = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


def parse_date(value: Any) -> dt.date | None:
    """Parse a date cell that may be a datetime, a date, or dd-mm-yyyy-ish text.

    Finacle and APT exports use day-first formats (dd-mm-yyyy / dd/mm/yyyy),
    exactly as the legacy VBA assumed when it rebuilt dates with DateSerial.
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    m = _DATE_RX.search(str(value))
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def parse_amount(value: Any) -> float:
    """Parse an amount cell; tolerates thousands separators and blanks."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        result = float(value)
        return 0.0 if result != result else result  # NaN -> 0
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_code(value: Any) -> str:
    """Account codes arrive as floats (8001000100.0) or text; normalize to digits."""
    text = cell_text(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text
