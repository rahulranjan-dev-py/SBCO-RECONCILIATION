"""Reconciliation engine.

Implements the distilled logic from docs/ANALYSIS.md §3 as SQL aggregations
returned as pandas DataFrames for display/export:

    daily code-wise:  Finacle vs Cashbook vs Difference per account code
    datewise:         per-day breakdown for one account code
    mismatch heads:   accounted vs cleared vs outstanding for the 8 pairs
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import AccountCode, CashbookDaily, FinacleGlDaily, MismatchPair

TOLERANCE = 0.005  # rupee amounts; anything below half a paisa is rounding noise


def _finacle_sums(session: Session, start: dt.date, end: dt.date) -> dict[str, float]:
    stmt = (
        select(FinacleGlDaily.account_code, func.sum(FinacleGlDaily.amount))
        .where(FinacleGlDaily.date >= start, FinacleGlDaily.date <= end)
        .group_by(FinacleGlDaily.account_code)
    )
    return {code: float(total or 0) for code, total in session.execute(stmt)}


def _cashbook_sums(session: Session, start: dt.date, end: dt.date) -> dict[str, float]:
    stmt = (
        select(CashbookDaily.account_code, func.sum(CashbookDaily.total))
        .where(CashbookDaily.date >= start, CashbookDaily.date <= end)
        .group_by(CashbookDaily.account_code)
    )
    return {code: float(total or 0) for code, total in session.execute(stmt)}


def _descriptions(session: Session, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    stmt = select(AccountCode.code, AccountCode.description).where(AccountCode.code.in_(codes))
    return dict(session.execute(stmt).all())


def daily_codewise(
    session: Session,
    start: dt.date,
    end: dt.date,
    nonzero_only: bool = False,
) -> pd.DataFrame:
    """The main reconciliation view (legacy 'CBS' sheet): per account code over a range."""
    fin = _finacle_sums(session, start, end)
    cb = _cashbook_sums(session, start, end)
    codes = set(fin) | set(cb)
    descs = _descriptions(session, codes)

    rows = []
    for code in sorted(codes):
        f, c = round(fin.get(code, 0.0), 2), round(cb.get(code, 0.0), 2)
        diff = round(f - c, 2)
        if nonzero_only and abs(diff) < TOLERANCE:
            continue
        rows.append(
            {
                "Account Code": code,
                "Description": descs.get(code, ""),
                "Finacle": f,
                "Cashbook": c,
                "Difference": diff,
            }
        )
    return pd.DataFrame(rows, columns=["Account Code", "Description", "Finacle", "Cashbook", "Difference"])


def datewise(session: Session, account_code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Day-by-day drilldown for one account code (legacy DATEWISE_DATA sheet)."""
    fin_stmt = (
        select(FinacleGlDaily.date, func.sum(FinacleGlDaily.amount))
        .where(
            FinacleGlDaily.account_code == account_code,
            FinacleGlDaily.date >= start,
            FinacleGlDaily.date <= end,
        )
        .group_by(FinacleGlDaily.date)
    )
    cb_stmt = (
        select(CashbookDaily.date, func.sum(CashbookDaily.total))
        .where(
            CashbookDaily.account_code == account_code,
            CashbookDaily.date >= start,
            CashbookDaily.date <= end,
        )
        .group_by(CashbookDaily.date)
    )
    fin = {d: float(v or 0) for d, v in session.execute(fin_stmt)}
    cb = {d: float(v or 0) for d, v in session.execute(cb_stmt)}

    rows = []
    day = start
    while day <= end:
        f, c = round(fin.get(day, 0.0), 2), round(cb.get(day, 0.0), 2)
        rows.append(
            {
                "Date": day.strftime("%d/%m/%Y"),
                "Finacle": f,
                "Cashbook": c,
                "Difference": round(f - c, 2),
            }
        )
        day += dt.timedelta(days=1)
    return pd.DataFrame(rows, columns=["Date", "Finacle", "Cashbook", "Difference"])


def mismatch_summary(session: Session, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Accounted vs cleared per mismatch head (legacy MISMATCH ENTRIES sheet).

    Amounts come from the cashbook store, where the mismatch heads are accounted.
    """
    cb = _cashbook_sums(session, start, end)
    pairs = session.scalars(select(MismatchPair)).all()
    rows = []
    for p in sorted(pairs, key=lambda p: p.mismatch_desc):
        accounted = round(cb.get(p.mismatch_code, 0.0), 2)
        cleared = round(cb.get(p.cleared_code, 0.0), 2)
        rows.append(
            {
                "Type": p.mismatch_desc or p.mismatch_code,
                "Mismatch A/c": p.mismatch_code,
                "Accounted": accounted,
                "Cleared A/c": p.cleared_code,
                "Cleared": cleared,
                "Outstanding": round(accounted - cleared, 2),
            }
        )
    return pd.DataFrame(
        rows, columns=["Type", "Mismatch A/c", "Accounted", "Cleared A/c", "Cleared", "Outstanding"]
    )
