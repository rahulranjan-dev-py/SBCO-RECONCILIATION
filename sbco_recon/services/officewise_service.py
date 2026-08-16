"""Office-wise reconciliation for one account code
(legacy compare.glwise.report sheet).

CBS side:  FinacleSolDaily — per-SOL figures from a Set-ID GL-wise report.
APT side:  AptOfficeDaily — per-office figures from the Accounting Details report.

Finacle can only see SOLs: BO transactions post under the parent SO's SOL. The
office master (Office.sol_group) says which SOL each office rolls up to, so the
true comparison happens per SOL group; member offices are listed with their APT
amounts underneath each group line.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import AptOfficeDaily, FinacleSolDaily, Office

COLUMNS = ["Office / SOL group", "Code", "Finacle", "APT", "Difference"]


def _finacle_by_sol(session: Session, code: str, start: dt.date, end: dt.date) -> dict[str, float]:
    stmt = (
        select(FinacleSolDaily.sol_id, func.sum(FinacleSolDaily.amount))
        .where(
            FinacleSolDaily.account_code == code,
            FinacleSolDaily.date >= start,
            FinacleSolDaily.date <= end,
        )
        .group_by(FinacleSolDaily.sol_id)
    )
    return {sol: float(total or 0) for sol, total in session.execute(stmt)}


def _apt_by_office(session: Session, code: str, start: dt.date, end: dt.date) -> dict[tuple[str, str], float]:
    stmt = (
        select(AptOfficeDaily.office_id, AptOfficeDaily.office_name, func.sum(AptOfficeDaily.amount))
        .where(
            AptOfficeDaily.account_code == code,
            AptOfficeDaily.date >= start,
            AptOfficeDaily.date <= end,
        )
        .group_by(AptOfficeDaily.office_id, AptOfficeDaily.office_name)
    )
    return {(oid or "", oname or ""): float(total or 0) for oid, oname, total in session.execute(stmt)}


def compare(session: Session, account_code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Group-level comparison with per-office APT breakdown.

    Group rows carry Finacle, APT and Difference; member office rows carry the
    office's APT amount (Finacle cannot attribute below SOL level).
    """
    fin = _finacle_by_sol(session, account_code, start, end)
    apt = _apt_by_office(session, account_code, start, end)
    offices = session.scalars(select(Office).order_by(Office.id)).all()

    # office_id -> (name, group); offices without a sol_group fall back on their own code
    by_office_id = {o.office_id: o for o in offices}
    groups: dict[str, list[Office]] = {}
    for o in offices:
        group = o.sol_group or o.sol_or_bo_code or o.office_id
        groups.setdefault(group, []).append(o)

    # APT amounts keyed to master offices where possible; strays kept separately.
    apt_by_master: dict[str, float] = {}
    strays: dict[tuple[str, str], float] = {}
    for (oid, oname), amount in apt.items():
        if oid in by_office_id:
            apt_by_master[oid] = apt_by_master.get(oid, 0.0) + amount
        else:
            strays[(oid, oname)] = amount

    rows: list[dict] = []
    seen_sols: set[str] = set()
    for group, members in groups.items():
        seen_sols.add(group)
        fin_amt = round(fin.get(group, 0.0), 2)
        apt_amt = round(sum(apt_by_master.get(o.office_id, 0.0) for o in members), 2)
        rows.append(
            {
                "Office / SOL group": f"SOL {group}",
                "Code": group,
                "Finacle": fin_amt,
                "APT": apt_amt,
                "Difference": round(fin_amt - apt_amt, 2),
            }
        )
        for o in members:
            rows.append(
                {
                    "Office / SOL group": f"    {o.name}",
                    "Code": o.sol_or_bo_code or o.office_id,
                    "Finacle": None,
                    "APT": round(apt_by_master.get(o.office_id, 0.0), 2),
                    "Difference": None,
                }
            )

    # SOLs with Finacle data but no offices mapped to them
    for sol, amount in sorted(fin.items()):
        if sol not in seen_sols:
            rows.append(
                {
                    "Office / SOL group": f"SOL {sol} (not in office master)",
                    "Code": sol,
                    "Finacle": round(amount, 2),
                    "APT": 0.0,
                    "Difference": round(amount, 2),
                }
            )
    # APT offices missing from the master
    for (oid, oname), amount in sorted(strays.items()):
        rows.append(
            {
                "Office / SOL group": f"{oname or oid} (not in office master)",
                "Code": oid,
                "Finacle": 0.0,
                "APT": round(amount, 2),
                "Difference": round(-amount, 2),
            }
        )

    return pd.DataFrame(rows, columns=COLUMNS)
