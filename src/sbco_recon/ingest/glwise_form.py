"""Form-style GL IT 2.0 GL-Wise report: the raw Finacle export.

The columnar detector expects every row to carry its own date and SOL ID. The
report as Finacle actually emits it (SB Order 09/2026, Annexure-III, page 11)
does neither: the date and SOL sit in a *header block* of label/value pairs,

    Date :            02-05-2026
    Sol ID :          60001700
    Set ID / Desc :   TAMI1 - TAMI1
    Sol ID / Desc :   60001700 - Thygarayanagar H.O

and the table splits the amount into Deposits (Cr) and Withdrawals (Dr):

    S.No | GL Sub Head Code | IT2.0 A/C Code | IT2.0 Acct Code Desc |
    Deposits (Cr) | Withdrawals (Dr)

A report generated with a Set ID repeats the "Sol ID / Desc :" block and the
table once per SOL in the set, all in one sheet, which is what feeds the
office-wise reconciliation.

This module recognises that shape and turns it into Entry records: the header
date is stamped on every row, each section's SOL comes from its own label, and
deposits + withdrawals are summed into one amount per row — each IT 2.0 code is
inherently receipt- or payment-side, so the split carries no information the
account-code master does not already hold (same reduction the legacy tool made
in TEMP.FIN).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..model import Entry, Source, ZERO
from ..normalize import clean_text, parse_account_code, parse_amount, parse_date

TITLE_RX = re.compile(
    r"GL\s*IT\s*2\.?0\s+Transaction\s+GL\s*Wise\s+Report.*Consolidated", re.IGNORECASE)
DATE_LABEL_RX = re.compile(r"^Date\s*:", re.IGNORECASE)
SOL_LABEL_RX = re.compile(r"^Sol\s*ID(\s*/\s*Desc)?\s*:?$", re.IGNORECASE)
TOTAL_RX = re.compile(r"^(grand\s+)?total", re.IGNORECASE)

CODE_HDR = ("accode", "acctcode", "accountcode")
DESC_HDR = ("desc",)
DEPOSIT_HDR = ("deposit",)
WITHDRAWAL_HDR = ("withdrawal",)

HEADER_SEARCH_ROWS = 40      # the title and date block sit near the top
MIN_PARSE_RATE = 0.50        # same bar as the columnar parser


def _norm(text) -> str:
    return "".join(ch for ch in clean_text(text).lower() if ch.isalnum())


@dataclass
class Section:
    """One SOL's table inside the report."""

    header_row: int
    code_col: int
    desc_col: int
    deposit_col: int
    withdrawal_col: int
    sol_id: str = ""


@dataclass
class FormLayout:
    """Everything needed to parse a form-style GL-wise file."""

    report_date: "object"
    sections: list = field(default_factory=list)

    @property
    def header_row(self) -> int:
        return self.sections[0].header_row if self.sections else -1


def _find_table_headers(rows) -> list:
    """Every table header row in the sheet — one per SOL section."""
    out = []
    for idx, row in enumerate(rows):
        if not row:
            continue
        code_col = desc_col = dep_col = wd_col = None
        for col, cell in enumerate(row):
            h = _norm(cell)
            if not h:
                continue
            if code_col is None and any(k in h for k in CODE_HDR):
                code_col = col
            elif desc_col is None and any(k in h for k in DESC_HDR):
                desc_col = col
            elif dep_col is None and any(k in h for k in DEPOSIT_HDR):
                dep_col = col
            elif wd_col is None and any(k in h for k in WITHDRAWAL_HDR):
                wd_col = col
        if code_col is not None and dep_col is not None and wd_col is not None:
            out.append(Section(idx, code_col,
                               desc_col if desc_col is not None else code_col + 1,
                               dep_col, wd_col))
    return out


def _value_beside(row, col) -> str:
    """The value paired with a label: embedded after the colon, or in the next cells."""
    own = clean_text(row[col])
    after = own.split(":", 1)[1].strip() if ":" in own else ""
    if after:
        return after
    for cell in row[col + 1: col + 4]:
        text = clean_text(cell)
        if text:
            return text
    return ""


def _find_report_date(rows):
    for row in rows[:HEADER_SEARCH_ROWS]:
        if not row:
            continue
        for col, cell in enumerate(row):
            if DATE_LABEL_RX.match(clean_text(cell)):
                parsed = parse_date(_value_beside(row, col))
                if parsed:
                    return parsed
    return None


def _sol_for_section(rows, header_row: int) -> str:
    """The nearest 'Sol ID / Desc :' (or 'Sol ID :') label above the table that
    actually carries a SOL number."""
    for idx in range(header_row - 1, -1, -1):
        row = rows[idx]
        if not row:
            continue
        for col, cell in enumerate(row):
            text = clean_text(cell)
            label = text.split(":", 1)[0] + ":" if ":" in text else text
            if not SOL_LABEL_RX.match(label.strip()):
                continue
            m = re.search(r"\d{4,}", _value_beside(row, col))
            if m:
                return m.group(0)
    return ""


def detect_form(rows) -> Optional[FormLayout]:
    """Recognise a form-style GL-wise report, or return None.

    Requires the report title, a parsable header date, and at least one
    Deposits/Withdrawals table.
    """
    if not rows:
        return None
    if not any(TITLE_RX.search(clean_text(c))
               for row in rows[:HEADER_SEARCH_ROWS] if row for c in row):
        return None
    report_date = _find_report_date(rows)
    if report_date is None:
        return None
    sections = _find_table_headers(rows)
    if not sections:
        return None
    for section in sections:
        section.sol_id = _sol_for_section(rows, section.header_row)
    return FormLayout(report_date=report_date, sections=sections)


def parse_form(rows, layout: FormLayout, path="") -> tuple:
    """Turn a form-style report into Entry records. Returns (entries, warnings).

    Mirrors the columnar parser's accounting: unreadable rows are counted per
    reason, and a file where most rows fail is rejected, not half-loaded.
    """
    from ..errors import FileRejected

    entries, warnings = [], []
    skipped_no_code = 0
    considered = 0
    boundaries = [s.header_row for s in layout.sections[1:]] + [len(rows)]

    for section, end in zip(layout.sections, boundaries):
        for row in rows[section.header_row + 1: end]:
            if not row or not any(clean_text(c) for c in row):
                continue

            code_text = clean_text(row[section.code_col]) if section.code_col < len(row) else ""
            desc_text = clean_text(row[section.desc_col]) if section.desc_col < len(row) else ""
            if TOTAL_RX.match(code_text) or TOTAL_RX.match(desc_text):
                break  # this section's footer; anything after belongs to the next

            deposit = parse_amount(row[section.deposit_col]) if section.deposit_col < len(row) else None
            withdrawal = parse_amount(row[section.withdrawal_col]) if section.withdrawal_col < len(row) else None
            code = parse_account_code(row[section.code_col] if section.code_col < len(row) else None)

            if code is None:
                # Only a row that carries money can be a lost data row; label
                # rows between sections carry none and are skipped silently.
                if deposit is not None or withdrawal is not None:
                    skipped_no_code += 1
                    considered += 1
                continue

            considered += 1
            entries.append(Entry(
                txn_date=layout.report_date,
                account_code=code,
                amount=(deposit or ZERO) + (withdrawal or ZERO),
                source=Source.FINACLE_GL,
                sol_id=section.sol_id,
                description=desc_text,
            ))

    if considered and len(entries) / considered < MIN_PARSE_RATE:
        raise FileRejected(
            path, "too many unreadable rows",
            f"{len(entries)} of {considered} rows parsed; "
            f"{skipped_no_code} rows had amounts but no readable account code")
    if not entries:
        raise FileRejected(path, "no data rows found",
                           "form-style GL-wise report with an empty table")

    if skipped_no_code:
        warnings.append(f"skipped {skipped_no_code} row(s) with amounts but no "
                        f"readable account code")
    if len(layout.sections) > 1:
        warnings.append(f"{len(layout.sections)} SOL sections read "
                        f"(Set-ID report); office-wise figures available")
    return entries, warnings
