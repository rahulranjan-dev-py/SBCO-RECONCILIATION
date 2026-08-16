"""CBS Monthly Reconciliation Report to PAO (SB Order 09/2026 Annexure-IV).

Table-1: per account code — Finacle R/P, Monthly Cash Account R/P, Difference R/P,
where Monthly Cash Account = sum of Daily Cash Books + approved Transfer Entries
of the DDO (the SOP's own footnote).

Table-2: per account code — Opening Balance in the Difference, Current Month
Difference, Rectified During the Month, Pending for Rectification (R/P each).
"Rectified" is taken from Discrepancy Register entries settled in that month;
the opening balance is accumulated from the earliest loaded month forward.

Receipt/Payment column placement follows the account-code master's side
("Receipt Side" / "Payment Side"); codes missing from the master fall back on
their description containing "Receipt".
"""

from __future__ import annotations

import calendar
import datetime as dt

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db.models import (
    AccountCode,
    CashbookDaily,
    DiscrepancyEntry,
    FinacleGlDaily,
    TransferEntry,
)

TOLERANCE = 0.005

TABLE1_COLUMNS = [
    "Sl", "Account Code", "Account Code Description",
    "Finacle Receipts", "Finacle Payments",
    "Cash Account Receipts", "Cash Account Payments",
    "Difference Receipts", "Difference Payments",
]

TABLE2_COLUMNS = [
    "Sl", "Account Code", "Account Code Description",
    "Opening Receipts", "Opening Payments",
    "Current Month Receipts", "Current Month Payments",
    "Rectified Receipts", "Rectified Payments",
    "Pending Receipts", "Pending Payments",
]


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    """'2026-07' -> (2026-07-01, 2026-07-31)."""
    year, mon = int(month[:4]), int(month[5:7])
    return dt.date(year, mon, 1), dt.date(year, mon, calendar.monthrange(year, mon)[1])


def _sums(session: Session, model, amount_col, start: dt.date, end: dt.date) -> dict[str, float]:
    stmt = (
        select(model.account_code, func.sum(amount_col))
        .where(model.date >= start, model.date <= end)
        .group_by(model.account_code)
    )
    return {code: float(total or 0) for code, total in session.execute(stmt)}


def _te_sums(session: Session, month: str) -> dict[str, float]:
    stmt = (
        select(TransferEntry.account_code, func.sum(TransferEntry.direction * TransferEntry.amount))
        .where(TransferEntry.month == month)
        .group_by(TransferEntry.account_code)
    )
    return {code: float(total or 0) for code, total in session.execute(stmt)}


def _sides(session: Session, codes: set[str]) -> dict[str, tuple[str, str]]:
    """code -> (description, 'R'|'P')."""
    out: dict[str, tuple[str, str]] = {}
    if not codes:
        return out
    stmt = select(AccountCode.code, AccountCode.description, AccountCode.side).where(
        AccountCode.code.in_(codes)
    )
    for code, desc, side in session.execute(stmt):
        out[code] = (desc or "", "R" if (side or "").lower().startswith("receipt") else "P")
    return out


def _split(code: str, amount: float, sides: dict[str, tuple[str, str]], fallback_desc: str = "") -> tuple[float, float]:
    desc, side = sides.get(code, (fallback_desc, "R" if "receipt" in fallback_desc.lower() else "P"))
    return (amount, 0.0) if side == "R" else (0.0, amount)


def _month_diffs(session: Session, month: str) -> dict[str, dict]:
    """Per-code {desc, fin_r, fin_p, cash_r, cash_p, diff_r, diff_p} for a month."""
    start, end = month_bounds(month)
    fin = _sums(session, FinacleGlDaily, FinacleGlDaily.amount, start, end)
    cash = _sums(session, CashbookDaily, CashbookDaily.total, start, end)
    te = _te_sums(session, month)
    codes = set(fin) | set(cash) | set(te)
    sides = _sides(session, codes)

    out: dict[str, dict] = {}
    for code in sorted(codes):
        fin_amt = round(fin.get(code, 0.0), 2)
        cash_amt = round(cash.get(code, 0.0) + te.get(code, 0.0), 2)  # + approved TEs
        fin_r, fin_p = _split(code, fin_amt, sides)
        cash_r, cash_p = _split(code, cash_amt, sides)
        desc = sides.get(code, ("", ""))[0]
        out[code] = {
            "desc": desc,
            "fin_r": fin_r, "fin_p": fin_p,
            "cash_r": cash_r, "cash_p": cash_p,
            "diff_r": round(fin_r - cash_r, 2), "diff_p": round(fin_p - cash_p, 2),
        }
    return out


def _data_months(session: Session, upto: str) -> list[str]:
    """All months with loaded data, earliest first, up to and including `upto`."""
    months: set[str] = set()
    for model in (FinacleGlDaily, CashbookDaily):
        for d in session.scalars(select(model.date).distinct()):
            months.add(f"{d.year:04d}-{d.month:02d}")
    for m in session.scalars(select(TransferEntry.month).distinct()):
        months.add(m)
    return sorted(m for m in months if m <= upto)


def _rectified(session: Session, month: str) -> dict[str, tuple[float, float]]:
    start, end = month_bounds(month)
    stmt = select(DiscrepancyEntry).where(
        DiscrepancyEntry.status == "SETTLED",
        DiscrepancyEntry.rectified_on >= start,
        DiscrepancyEntry.rectified_on <= end,
    )
    out: dict[str, tuple[float, float]] = {}
    for e in session.scalars(stmt):
        r, p = out.get(e.account_code, (0.0, 0.0))
        out[e.account_code] = (round(r + e.diff_receipt, 2), round(p + e.diff_payment, 2))
    return out


def table1(session: Session, month: str, include_zero: bool = False) -> pd.DataFrame:
    diffs = _month_diffs(session, month)
    rows = []
    sl = 0
    for code, d in diffs.items():
        significant = any(
            abs(d[k]) >= TOLERANCE for k in ("fin_r", "fin_p", "cash_r", "cash_p", "diff_r", "diff_p")
        )
        if not (significant or include_zero):
            continue
        sl += 1
        rows.append(
            {
                "Sl": sl,
                "Account Code": code,
                "Account Code Description": d["desc"],
                "Finacle Receipts": d["fin_r"],
                "Finacle Payments": d["fin_p"],
                "Cash Account Receipts": d["cash_r"],
                "Cash Account Payments": d["cash_p"],
                "Difference Receipts": d["diff_r"],
                "Difference Payments": d["diff_p"],
            }
        )
    return pd.DataFrame(rows, columns=TABLE1_COLUMNS)


def table2(session: Session, month: str) -> pd.DataFrame:
    """Carry-forward view: opening + current − rectified = pending, per code.

    Opening balances accumulate from the earliest month that has any loaded data,
    so Table-2 is self-consistent with the data actually in the database.
    """
    months = _data_months(session, month)
    opening: dict[str, tuple[float, float]] = {}
    current: dict[str, dict] = {}
    rectified: dict[str, tuple[float, float]] = {}

    for m in months:
        diffs = _month_diffs(session, m)
        rect = _rectified(session, m)
        if m == month:
            current = diffs
            rectified = rect
            break
        # roll this month's outcome into the opening balances
        for code in set(diffs) | set(rect) | set(opening):
            o_r, o_p = opening.get(code, (0.0, 0.0))
            d = diffs.get(code, {})
            r_r, r_p = rect.get(code, (0.0, 0.0))
            opening[code] = (
                round(o_r + d.get("diff_r", 0.0) - r_r, 2),
                round(o_p + d.get("diff_p", 0.0) - r_p, 2),
            )

    codes = set(opening) | set(current) | set(rectified)
    sides = _sides(session, codes)
    rows = []
    sl = 0
    for code in sorted(codes):
        o_r, o_p = opening.get(code, (0.0, 0.0))
        c = current.get(code, {})
        c_r, c_p = c.get("diff_r", 0.0), c.get("diff_p", 0.0)
        r_r, r_p = rectified.get(code, (0.0, 0.0))
        p_r, p_p = round(o_r + c_r - r_r, 2), round(o_p + c_p - r_p, 2)
        if all(abs(v) < TOLERANCE for v in (o_r, o_p, c_r, c_p, r_r, r_p, p_r, p_p)):
            continue
        sl += 1
        rows.append(
            {
                "Sl": sl,
                "Account Code": code,
                "Account Code Description": c.get("desc") or sides.get(code, ("", ""))[0],
                "Opening Receipts": o_r,
                "Opening Payments": o_p,
                "Current Month Receipts": c_r,
                "Current Month Payments": c_p,
                "Rectified Receipts": r_r,
                "Rectified Payments": r_p,
                "Pending Receipts": p_r,
                "Pending Payments": p_p,
            }
        )
    return pd.DataFrame(rows, columns=TABLE2_COLUMNS)


# --- Transfer entries -----------------------------------------------------------


def add_transfer_entry(
    session: Session, month: str, account_code: str, amount: float, direction: int,
    remarks: str = "",
) -> TransferEntry:
    description = (
        session.scalar(select(AccountCode.description).where(AccountCode.code == account_code)) or ""
    )
    entry = TransferEntry(
        month=month, account_code=account_code, description=description,
        direction=1 if direction >= 0 else -1, amount=abs(amount), remarks=remarks,
    )
    session.add(entry)
    session.commit()
    return entry


def delete_transfer_entry(session: Session, entry_id: int) -> bool:
    entry = session.get(TransferEntry, entry_id)
    if entry is None:
        return False
    session.execute(delete(TransferEntry).where(TransferEntry.id == entry_id))
    session.commit()
    return True


def transfer_entries_frame(session: Session, month: str) -> pd.DataFrame:
    entries = session.scalars(
        select(TransferEntry).where(TransferEntry.month == month).order_by(TransferEntry.id)
    ).all()
    rows = [
        {
            "ID": e.id,
            "Account Code": e.account_code,
            "Description": e.description,
            "To(+)/From(−)": "TO (+)" if e.direction >= 0 else "FROM (−)",
            "Amount": e.amount,
            "Remarks": e.remarks,
        }
        for e in entries
    ]
    return pd.DataFrame(rows, columns=["ID", "Account Code", "Description", "To(+)/From(−)", "Amount", "Remarks"])
