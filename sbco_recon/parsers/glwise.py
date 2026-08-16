"""Parser for the Finacle *GL IT 2.0 Transaction GL Wise Report (Incl HO, SO & BOs) —
Consolidated (Previous Day)* Excel export.

This is the CBS side of the daily reconciliation (SOP §4.ii). Layout knowledge,
derived from the legacy tool's VBA (`cashbook_finacledata_1..7`) and the report
sample in SB Order 09/2026 Annexure-III:

- a title cell containing "GL IT2.0 Transaction GL Wise Report ... Consolidated"
  near the top (the VBA checked cell I4 for the exact string);
- the report date in a labelled header cell ("Date :" ... dd-mm-yyyy; VBA read F8);
- a data table with columns: S.No | GL Sub Head Code | IT2.0 A/C Code |
  IT2.0 Acct Code Desc | Deposits (Cr) | Withdrawals (Dr).

Deposits and withdrawals are summed into a single amount per account code, exactly
as the legacy tool did (each IT 2.0 code is inherently receipt- or payment-side).
"""

from __future__ import annotations

from .base import (
    MAX_SCAN_ROWS,
    ParsedReport,
    ParseError,
    cell_text,
    find_cell,
    find_header_row,
    normalize_code,
    parse_amount,
    parse_date,
)

REPORT_TYPE = "FINACLE_GLWISE"

TITLE_PATTERN = r"GL\s*IT\s*2\.?0\s+Transaction\s+GL\s*Wise\s+Report.*Consolidated"

HEADER_FRAGMENTS = {
    "code": r"A/?C\s*Code$|IT2\.?0\s*A/?C\s*Code",
    "desc": r"Acct\s*Code\s*Desc|Description",
    "deposits": r"Deposit",
    "withdrawals": r"Withdrawal",
}


def fingerprint(grid: list[list[object]]) -> bool:
    return find_cell(grid, TITLE_PATTERN) is not None


def _find_report_date(grid: list[list[object]]) -> tuple[object, int, int] | None:
    """Find the 'Date :' label near the top and the date value beside/after it."""
    loc = find_cell(grid, r"^Date\s*:?\s*$|^Date\s*:")
    if loc is None:
        return None
    r, c = loc
    # The value may be embedded in the label cell ("Date : 02-05-2026") or in one
    # of the next few cells to the right.
    candidates = [grid[r][c]] + list(grid[r][c + 1 : c + 5])
    for value in candidates:
        parsed = parse_date(value)
        if parsed:
            return parsed, r, c
    return None


def extract(grid: list[list[object]], file_name: str = "") -> ParsedReport:
    if not fingerprint(grid):
        raise ParseError("Not a GL IT 2.0 GL Wise Consolidated report")

    date_info = _find_report_date(grid)
    if date_info is None:
        raise ParseError("Report date not found (looked for a 'Date :' header cell)")
    report_date = date_info[0]

    header = find_header_row(
        grid,
        [HEADER_FRAGMENTS["code"], HEADER_FRAGMENTS["deposits"], HEADER_FRAGMENTS["withdrawals"]],
        max_rows=MAX_SCAN_ROWS,
    )
    if header is None:
        raise ParseError("Data table header row not found (A/C Code / Deposits / Withdrawals)")
    header_row, cols = header
    code_col = cols[HEADER_FRAGMENTS["code"]]
    dep_col = cols[HEADER_FRAGMENTS["deposits"]]
    wd_col = cols[HEADER_FRAGMENTS["withdrawals"]]

    # Description sits between the code and deposits columns; find it by header if
    # possible, otherwise take the column right after the code column.
    desc_col = code_col + 1
    desc_header = find_header_row(grid, [HEADER_FRAGMENTS["desc"]], max_rows=header_row + 1)
    if desc_header and desc_header[0] == header_row:
        desc_col = desc_header[1][HEADER_FRAGMENTS["desc"]]

    report = ParsedReport(report_type=REPORT_TYPE, report_date=report_date)
    for row in grid[header_row + 1 :]:
        code = normalize_code(row[code_col] if code_col < len(row) else None)
        if not code.isdigit() or len(code) < 6:
            # Blank separators, "Total" rows, page footers — stop only on a clearly
            # terminal marker, otherwise skip.
            text = cell_text(row[code_col] if code_col < len(row) else None)
            if text.lower().startswith(("total", "grand total")):
                break
            continue
        amount = parse_amount(row[dep_col] if dep_col < len(row) else None) + parse_amount(
            row[wd_col] if wd_col < len(row) else None
        )
        report.rows.append(
            {
                "date": report_date,
                "account_code": code,
                "description": cell_text(row[desc_col] if desc_col < len(row) else None),
                "amount": round(amount, 2),
            }
        )

    if not report.rows:
        report.warnings.append("No data rows found below the table header")
    return report
