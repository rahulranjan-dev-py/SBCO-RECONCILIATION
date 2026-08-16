"""Parser for the APT 2.0 *Daily Cash Book* Excel download
(APT: Accounts >> Accounts Consolidation >> Cashbook >> Download Cashbook (XLS)).

This is the cashbook side of the daily reconciliation. Layout knowledge from the
legacy tool (`cashbook_cashbookreport_1/2` and the TEMP.CBR store): two leading
title rows, then a header row followed by data with columns:

    Date | Office Name | Office ID | Account Code | Account Code Description |
    Part | Receipts/Payments | HO | SO | BO | Total | Progressive Total

The report date is taken from the first data row's Date column (the VBA read A4
after dropping the two title rows).
"""

from __future__ import annotations

from .base import (
    ParsedReport,
    ParseError,
    cell_text,
    find_header_row,
    normalize_code,
    parse_amount,
    parse_date,
)

REPORT_TYPE = "APT_CASHBOOK"

H = {
    "date": r"^Date$",
    "office_name": r"Office\s*Name",
    "office_id": r"Office\s*ID",
    "code": r"^Account\s*Code$",
    "desc": r"Account\s*Code\s*Description|Description",
    "part": r"^Part$",
    "side": r"Receipts?\s*/\s*Payments?",
    "ho": r"^HO$",
    "so": r"^SO$",
    "bo": r"^BO$",
    "total": r"^Total$",
}

REQUIRED = [H["office_name"], H["code"], H["total"]]


def fingerprint(grid: list[list[object]]) -> bool:
    return find_header_row(grid, REQUIRED) is not None


def extract(grid: list[list[object]], file_name: str = "") -> ParsedReport:
    header = find_header_row(grid, REQUIRED)
    if header is None:
        raise ParseError("Not an APT cashbook export (header row not found)")
    header_row, _ = header

    # Resolve every known column on that header row (missing optional columns are None).
    cols: dict[str, int | None] = {}
    for key, pattern in H.items():
        got = find_header_row(grid, [pattern], max_rows=header_row + 1)
        cols[key] = got[1][pattern] if got and got[0] == header_row else None
    if cols["date"] is None or cols["code"] is None or cols["total"] is None:
        raise ParseError("Cashbook header incomplete (need Date, Account Code, Total)")

    def get(row: list[object], key: str):
        idx = cols[key]
        return row[idx] if idx is not None and idx < len(row) else None

    report = ParsedReport(report_type=REPORT_TYPE, report_date=None)
    for row in grid[header_row + 1 :]:
        code = normalize_code(get(row, "code"))
        row_date = parse_date(get(row, "date"))
        if not code.isdigit() or len(code) < 6:
            text = cell_text(get(row, "code")) or cell_text(row[0] if row else None)
            if text.lower().startswith(("total", "grand total")):
                break
            continue
        if row_date is None:
            report.warnings.append(f"Row with account code {code} has no parsable date; skipped")
            continue
        if report.report_date is None:
            report.report_date = row_date
        report.rows.append(
            {
                "date": row_date,
                "office_name": cell_text(get(row, "office_name")),
                "office_id": normalize_code(get(row, "office_id")),
                "account_code": code,
                "description": cell_text(get(row, "desc")),
                "part": cell_text(get(row, "part")),
                "side": cell_text(get(row, "side")),
                "ho_amt": parse_amount(get(row, "ho")),
                "so_amt": parse_amount(get(row, "so")),
                "bo_amt": parse_amount(get(row, "bo")),
                "total": parse_amount(get(row, "total")),
            }
        )

    if not report.rows:
        raise ParseError("No data rows found in cashbook export")
    return report
