"""Load the bundled master data (extracted from the legacy tool) on first run."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..paths import seed_dir
from .models import AccountCode, MismatchPair


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f) if any(cell.strip() for cell in row)]


def seed_account_codes(session: Session, path: Path) -> int:
    rows = _read_csv(path)
    count = 0
    seen: set[str] = set()
    for row in rows[1:]:  # skip header
        code = row[0].strip()
        if not code or code in seen:
            continue
        seen.add(code)
        session.add(
            AccountCode(
                code=code,
                hoa=row[1].strip() or None if len(row) > 1 else None,
                description=row[2].strip() if len(row) > 2 else "",
                side=row[3].strip() or None if len(row) > 3 else None,
                sign=row[4].strip() or None if len(row) > 4 else None,
                part=row[5].strip() or None if len(row) > 5 else None,
            )
        )
        count += 1
    return count


def seed_mismatch_pairs(session: Session, path: Path) -> int:
    rows = _read_csv(path)
    count = 0
    for row in rows[1:]:
        if len(row) < 3 or not row[0].strip():
            continue
        session.add(
            MismatchPair(
                mismatch_code=row[0].strip(),
                mismatch_desc=row[1].strip() if len(row) > 1 else "",
                cleared_code=row[2].strip(),
                cleared_desc=row[3].strip() if len(row) > 3 else "",
            )
        )
        count += 1
    return count


def seed_if_empty(session: Session) -> None:
    base = seed_dir()
    if session.scalar(select(func.count()).select_from(AccountCode)) == 0:
        ac_file = base / "ac_codes.csv"
        if ac_file.exists():
            seed_account_codes(session, ac_file)
    if session.scalar(select(func.count()).select_from(MismatchPair)) == 0:
        mm_file = base / "mismatch_pairs.csv"
        if mm_file.exists():
            seed_mismatch_pairs(session, mm_file)
