"""Parser for the Finacle *GL IT 2.0 Transaction GL Wise Report* Excel export.

Two variants of the same layout (SB Order 09/2026 Annexure-III):

- generated with the **HO Sol Id** → one consolidated table (Incl HO, SO & BOs):
  the CBS side of the daily reconciliation (SOP §4.ii);
- generated with a **Set ID** → one section per SOL, each section headed by a
  "Sol ID / Desc :" block and its own data table: feeds the office-wise
  reconciliation as well.

Layout knowledge from the legacy tool's VBA (`cashbook_finacledata_1..7`) and the
report sample on page 11 of the SB Order: a title cell containing "GL IT2.0
Transaction GL Wise Report ... Consolidated" near the top (VBA checked I4), the
report date in a labelled cell ("Date :", VBA read F8), and per section a table:

    S.No | GL Sub Head Code | IT2.0 A/C Code | IT2.0 Acct Code Desc |
    Deposits (Cr) | Withdrawals (Dr)

Deposits and withdrawals are summed into a single amount per account code, as the
legacy tool did (each IT 2.0 code is inherently receipt- or payment-side).
"""

from __future__ import annotations

import re

from .base import (
    ParsedReport,
    ParseError,
    cell_text,
    find_cell,
    normalize_code,
    parse_amount,
    parse_date,
)

REPORT_TYPE = "FINACLE_GLWISE"

TITLE_PATTERN = r"GL\s*IT\s*2\.?0\s+Transaction\s+GL\s*Wise\s+Report.*Consolidated"

CODE_HEADER_RX = re.compile(r"A/?C\s*Code", re.IGNORECASE)
DESC_HEADER_RX = re.compile(r"Acct\s*Code\s*Desc|Description", re.IGNORECASE)
DEP_HEADER_RX = re.compile(r"Deposit", re.IGNORECASE)
WD_HEADER_RX = re.compile(r"Withdrawal", re.IGNORECASE)
SOL_LABEL_RX = re.compile(r"Sol\s*ID(\s*/\s*Desc)?\s*:?", re.IGNORECASE)


def fingerprint(grid: list[list[object]]) -> bool:
    return find_cell(grid, TITLE_PATTERN) is not None


def _find_report_date(grid: list[list[object]]):
    loc = find_cell(grid, r"^Date\s*:?\s*$|^Date\s*:")
    if loc is None:
        return None
    r, c = loc
    for value in [grid[r][c]] + list(grid[r][c + 1 : c + 5]):
        parsed = parse_date(value)
        if parsed:
            return parsed
    return None


def _table_header_rows(grid: list[list[object]]) -> list[tuple[int, int, int, int, int]]:
    """All data-table header rows in the file, one per SOL section.

    Returns (row, code_col, desc_col, dep_col, wd_col) tuples.
    """
    out = []
    for r, row in enumerate(grid):
        code_col = dep_col = wd_col = desc_col = None
        for c, val in enumerate(row):
            text = cell_text(val)
            if not text:
                continue
            if code_col is None and CODE_HEADER_RX.search(text):
                code_col = c
            elif desc_col is None and DESC_HEADER_RX.search(text):
                desc_col = c
            elif dep_col is None and DEP_HEADER_RX.search(text):
                dep_col = c
            elif wd_col is None and WD_HEADER_RX.search(text):
                wd_col = c
        if code_col is not None and dep_col is not None and wd_col is not None:
            out.append((r, code_col, desc_col if desc_col is not None else code_col + 1, dep_col, wd_col))
    return out


def _sol_for_section(grid: list[list[object]], header_row: int) -> str:
    """The SOL id governing the section whose table header sits at header_row:
    the value beside the nearest preceding 'Sol ID / Desc :' (or 'Sol ID :') label
    that actually carries one."""
    for r in range(header_row - 1, -1, -1):
        row = grid[r]
        for c, val in enumerate(row):
            if not SOL_LABEL_RX.fullmatch(cell_text(val)):
                continue
            for value in row[c + 1 : c + 4]:
                text = cell_text(value)
                m = re.search(r"\d{4,}", text)
                if m:
                    return m.group(0)
    return ""


def extract(grid: list[list[object]], file_name: str = "") -> ParsedReport:
    if not fingerprint(grid):
        raise ParseError("Not a GL IT 2.0 GL Wise Consolidated report")

    report_date = _find_report_date(grid)
    if report_date is None:
        raise ParseError("Report date not found (looked for a 'Date :' header cell)")

    sections = _table_header_rows(grid)
    if not sections:
        raise ParseError("Data table header row not found (A/C Code / Deposits / Withdrawals)")

    report = ParsedReport(report_type=REPORT_TYPE, report_date=report_date)
    consolidated: dict[str, dict] = {}
    section_starts = [s[0] for s in sections]

    for i, (header_row, code_col, desc_col, dep_col, wd_col) in enumerate(sections):
        end = section_starts[i + 1] if i + 1 < len(sections) else len(grid)
        sol_id = _sol_for_section(grid, header_row)
        sol_totals: dict[str, dict] = {}
        for row in grid[header_row + 1 : end]:
            code = normalize_code(row[code_col] if code_col < len(row) else None)
            if not code.isdigit() or len(code) < 6:
                text = cell_text(row[code_col] if code_col < len(row) else None) or cell_text(
                    row[desc_col] if desc_col < len(row) else None
                )
                if text.lower().startswith(("total", "grand total")):
                    break
                continue
            amount = parse_amount(row[dep_col] if dep_col < len(row) else None) + parse_amount(
                row[wd_col] if wd_col < len(row) else None
            )
            desc = cell_text(row[desc_col] if desc_col < len(row) else None)
            bucket = sol_totals.setdefault(code, {"amount": 0.0, "description": desc})
            bucket["amount"] += amount
            agg = consolidated.setdefault(code, {"amount": 0.0, "description": desc})
            agg["amount"] += amount

        for code, data in sol_totals.items():
            report.sol_rows.append(
                {
                    "date": report_date,
                    "sol_id": sol_id,
                    "account_code": code,
                    "description": data["description"],
                    "amount": round(data["amount"], 2),
                }
            )

    for code in sorted(consolidated):
        report.rows.append(
            {
                "date": report_date,
                "account_code": code,
                "description": consolidated[code]["description"],
                "amount": round(consolidated[code]["amount"], 2),
            }
        )

    if not report.rows:
        report.warnings.append("No data rows found below the table header")
    if len(sections) > 1:
        report.warnings.append(f"{len(sections)} SOL sections parsed")
    return report
