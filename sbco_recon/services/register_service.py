"""Discrepancy Register workflow (Annexure-IV Table-3).

Serial numbers restart at 1 each financial year (April–March), per the SOP:
"The Register shall be closed at the end of each financial year, and the serial
numbering shall reset from S No.1 at the beginning of the next financial year."
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import AccountCode, DiscrepancyEntry


def financial_year(date: dt.date) -> str:
    """Indian FY label for a date: 2026-04-01 → '2026-27'."""
    start_year = date.year if date.month >= 4 else date.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def next_serial(session: Session, fy: str) -> int:
    current = session.scalar(
        select(func.max(DiscrepancyEntry.serial)).where(DiscrepancyEntry.fy == fy)
    )
    return (current or 0) + 1


def add_entry(
    session: Session,
    date: dt.date,
    account_code: str,
    office_name: str = "",
    cbs_receipt: float = 0.0,
    cbs_payment: float = 0.0,
    cb_receipt: float = 0.0,
    cb_payment: float = 0.0,
    remarks: str = "",
) -> DiscrepancyEntry:
    fy = financial_year(date)
    description = (
        session.scalar(select(AccountCode.description).where(AccountCode.code == account_code)) or ""
    )
    entry = DiscrepancyEntry(
        fy=fy,
        serial=next_serial(session, fy),
        date=date,
        account_code=account_code,
        description=description,
        office_name=office_name,
        cbs_receipt=cbs_receipt,
        cbs_payment=cbs_payment,
        cb_receipt=cb_receipt,
        cb_payment=cb_payment,
        remarks=remarks,
    )
    session.add(entry)
    session.commit()
    return entry


def settle_entry(
    session: Session,
    entry_id: int,
    rectified_on: dt.date,
    misc_txn_particulars: str = "",
    te_particulars: str = "",
) -> DiscrepancyEntry | None:
    entry = session.get(DiscrepancyEntry, entry_id)
    if entry is None:
        return None
    entry.status = "SETTLED"
    entry.rectified_on = rectified_on
    entry.misc_txn_particulars = misc_txn_particulars
    entry.te_particulars = te_particulars
    session.commit()
    return entry


def register_frame(
    session: Session,
    start: dt.date | None = None,
    end: dt.date | None = None,
    status: str | None = None,
) -> pd.DataFrame:
    """The register as a DataFrame in Table-3 column order (for display/export)."""
    stmt = select(DiscrepancyEntry).order_by(DiscrepancyEntry.fy, DiscrepancyEntry.serial)
    if start:
        stmt = stmt.where(DiscrepancyEntry.date >= start)
    if end:
        stmt = stmt.where(DiscrepancyEntry.date <= end)
    if status:
        stmt = stmt.where(DiscrepancyEntry.status == status)
    entries = session.scalars(stmt).all()
    rows = [
        {
            "ID": e.id,
            "FY": e.fy,
            "Sl No": e.serial,
            "Date": e.date.strftime("%d/%m/%Y"),
            "Account Code": e.account_code,
            "Description": e.description,
            "Office": e.office_name,
            "Receipt (CBS)": e.cbs_receipt,
            "Payment (CBS)": e.cbs_payment,
            "Receipt (Cash Book)": e.cb_receipt,
            "Payment (Cash Book)": e.cb_payment,
            "Diff Receipt": e.diff_receipt,
            "Diff Payment": e.diff_payment,
            "Status": e.status,
            "Rectified On": e.rectified_on.strftime("%d/%m/%Y") if e.rectified_on else "",
            "Misc. Txn": e.misc_txn_particulars,
            "Transfer Entries": e.te_particulars,
            "Remarks": e.remarks,
        }
        for e in entries
    ]
    return pd.DataFrame(rows)
