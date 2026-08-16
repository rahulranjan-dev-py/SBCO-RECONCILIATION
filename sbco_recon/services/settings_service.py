"""Key/value app settings (HO name, DDO code, division) and the office master."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import Office, Setting

KEYS = ("ho_name", "ddo_code", "division")


def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.commit()


def all_settings(session: Session) -> dict[str, str]:
    return {key: get_setting(session, key) for key in KEYS}


# --- Office master --------------------------------------------------------------


def offices_frame(session: Session) -> pd.DataFrame:
    offices = session.scalars(select(Office).order_by(Office.id)).all()
    rows = [
        {
            "ID": o.id,
            "Office Name": o.name,
            "Office ID": o.office_id,
            "SOL / BO Code": o.sol_or_bo_code or "",
            "SOL Group": o.sol_group or "",
        }
        for o in offices
    ]
    return pd.DataFrame(rows, columns=["ID", "Office Name", "Office ID", "SOL / BO Code", "SOL Group"])


def upsert_office(
    session: Session, name: str, office_id: str, sol_or_bo_code: str, sol_group: str,
    row_id: int | None = None,
) -> Office:
    office = session.get(Office, row_id) if row_id else None
    if office is None:
        office = session.scalar(select(Office).where(Office.office_id == office_id))
    if office is None:
        office = Office(name=name, office_id=office_id)
        session.add(office)
    office.name = name
    office.office_id = office_id
    office.sol_or_bo_code = sol_or_bo_code or None
    office.sol_group = sol_group or None
    session.commit()
    return office


def delete_office(session: Session, row_id: int) -> bool:
    office = session.get(Office, row_id)
    if office is None:
        return False
    session.execute(delete(Office).where(Office.id == row_id))
    session.commit()
    return True
