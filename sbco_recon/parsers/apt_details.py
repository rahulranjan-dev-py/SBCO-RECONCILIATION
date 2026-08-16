"""Parser for the APT 2.0 *Accounting Details* report
(APT: Treasury >> Reports >> Accounting Details >> A/c Code, date range, office: all).

The APT side of the office-wise reconciliation: office-wise rows for ONE account
code over a date range. Layout knowledge from the legacy tool's stores (APT_ALL /
TEMP.CLR: OFFICE ID, OFFICE, DATE, ACCOUNT CODE, AMOUNT, ...) and its upload
instructions on the compare.* sheets.

The account code is taken from the rows' own Account Code column when present,
otherwise from an "A/c Code : NNNNNNNNNN" header cell.
"""

from __future__ import annotations

import re

from .base import (
    ParsedReport,
    ParseError,
    cell_text,
    find_cell,
    find_header_row,
    normalize_code,
    parse_amount,
    parse_date,
)

REPORT_TYPE = "APT_DETAILS"

H = {
    "office_id": r"Office\s*_?\s*ID",
    "office_name": r"^Office(\s*Name)?$|Office\s*Name",
    "date": r"^(Deduct[_\s]*)?Date$",
    "code": r"A/?c(?:count)?\s*_?\s*Code",
    "amount": r"^(Amount|AMT)$",
    "remarks": r"Remarks",
}

REQUIRED = [H["office_name"], H["date"], H["amount"]]

TITLE_PATTERN = r"Accounting\s+Details"


def fingerprint(grid: list[list[object]]) -> bool:
    header = find_header_row(grid, REQUIRED)
    if header is None:
        return False
    # Distinguish from the APT cashbook, which also has Office/Date columns but
    # carries HO/SO/BO/Progressive Total columns instead of a single Amount.
    row = grid[header[0]]
    texts = [cell_text(v) for v in row]
    if any(re.fullmatch(r"Progressive\s*Total", t, re.IGNORECASE) for t in texts if t):
        return False
    return True


def _code_from_header(grid: list[list[object]]) -> str:
    loc = find_cell(grid, r"A/?c\s*Code\s*:")
    if loc is None:
        return ""
    r, c = loc
    for value in [grid[r][c]] + list(grid[r][c + 1 : c + 4]):
        m = re.search(r"\d{6,}", cell_text(value))
        if m:
            return m.group(0)
    return ""


def extract(grid: list[list[object]], file_name: str = "") -> ParsedReport:
    header = find_header_row(grid, REQUIRED)
    if header is None or not fingerprint(grid):
        raise ParseError("Not an APT Accounting Details report (header row not found)")
    header_row = header[0]

    cols: dict[str, int | None] = {}
    for key, pattern in H.items():
        got = find_header_row(grid, [pattern], max_rows=header_row + 1)
        cols[key] = got[1][pattern] if got and got[0] == header_row else None

    header_code = _code_from_header(grid)

    def get(row: list[object], key: str):
        idx = cols[key]
        return row[idx] if idx is not None and idx < len(row) else None

    report = ParsedReport(report_type=REPORT_TYPE, report_date=None)
    for row in grid[header_row + 1 :]:
        row_date = parse_date(get(row, "date"))
        amount_cell = get(row, "amount")
        code = normalize_code(get(row, "code")) if cols["code"] is not None else ""
        if not (code.isdigit() and len(code) >= 6):
            code = header_code
        office_name = cell_text(get(row, "office_name"))
        if row_date is None or not code:
            if office_name.lower().startswith(("total", "grand total")):
                break
            continue
        if report.report_date is None:
            report.report_date = row_date
        report.rows.append(
            {
                "date": row_date,
                "office_id": normalize_code(get(row, "office_id")),
                "office_name": office_name,
                "account_code": code,
                "amount": parse_amount(amount_cell),
                "remarks": cell_text(get(row, "remarks")),
            }
        )

    if not report.rows:
        raise ParseError("No data rows found in Accounting Details report")
    return report
