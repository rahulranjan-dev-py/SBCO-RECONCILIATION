"""File import pipeline.

Replaces the legacy batch-upload macros: each selected file is read, its report
type auto-detected by fingerprint, validated, guarded against duplicate dates and
duplicate content (checksum), then inserted transactionally with an audit entry —
the persistent equivalent of the old 'Processing Summary' sheet.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, distinct, select
from sqlalchemy.orm import Session

from ..db.models import AptOfficeDaily, CashbookDaily, FinacleGlDaily, FinacleSolDaily, ImportLog
from ..parsers import PARSERS, ParseError, apt_details, cashbook, glwise, read_grid

#: main data store per report type (finacle_sol is an auxiliary store fed by glwise)
STORES = {
    glwise.REPORT_TYPE: FinacleGlDaily,
    cashbook.REPORT_TYPE: CashbookDaily,
    apt_details.REPORT_TYPE: AptOfficeDaily,
}


@dataclass
class ImportResult:
    file_name: str
    report_type: str | None
    report_date: dt.date | None
    status: str  # PROCESSED / INVALID / DUPLICATE / ERROR
    message: str
    row_count: int = 0


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect(grid) -> str | None:
    for report_type, module in PARSERS.items():
        if module.fingerprint(grid):
            return report_type
    return None


def _dates_present(session: Session, report_type: str) -> set[dt.date]:
    model = STORES[report_type]
    return set(session.scalars(select(distinct(model.date))).all())


def _date_code_pairs_present(session: Session, pairs: set[tuple[dt.date, str]]) -> set[tuple[dt.date, str]]:
    """Which (date, account_code) pairs already exist in the APT details store.

    Accounting Details files cover one account code over a range, so the duplicate
    guard is per (date, code) — a different code for the same dates is fine.
    """
    if not pairs:
        return set()
    codes = {code for _, code in pairs}
    dates = {date for date, _ in pairs}
    stmt = (
        select(AptOfficeDaily.date, AptOfficeDaily.account_code)
        .where(AptOfficeDaily.account_code.in_(codes), AptOfficeDaily.date.in_(dates))
        .distinct()
    )
    existing = {(date, code) for date, code in session.execute(stmt)}
    return existing & pairs


def _log(session: Session, result: ImportResult, checksum: str | None) -> None:
    session.add(
        ImportLog(
            file_name=result.file_name,
            report_type=result.report_type or "UNKNOWN",
            report_date=result.report_date,
            status=result.status,
            message=result.message,
            row_count=result.row_count,
            checksum=checksum,
        )
    )


def import_file(session: Session, path: str | Path) -> ImportResult:
    """Import one report file. Commits its own log entry; data commits atomically."""
    path = Path(path)
    name = path.name

    try:
        checksum = _checksum(path)
    except OSError as exc:
        result = ImportResult(name, None, None, "ERROR", f"Cannot read file: {exc}")
        _log(session, result, None)
        session.commit()
        return result

    # Same file content already processed? (renamed re-uploads included)
    dup = session.scalar(
        select(ImportLog).where(ImportLog.checksum == checksum, ImportLog.status == "PROCESSED")
    )
    if dup:
        result = ImportResult(
            name, dup.report_type, dup.report_date, "DUPLICATE",
            f"Identical file already imported on {dup.imported_at:%d/%m/%Y %H:%M} as '{dup.file_name}'",
        )
        _log(session, result, checksum)
        session.commit()
        return result

    try:
        grid = read_grid(path)
    except Exception as exc:  # unreadable / not an Excel file
        result = ImportResult(name, None, None, "ERROR", f"Cannot open as Excel: {exc}")
        _log(session, result, checksum)
        session.commit()
        return result

    report_type = _detect(grid)
    if report_type is None:
        result = ImportResult(
            name, None, None, "INVALID",
            "Unrecognized report (expected GL IT 2.0 GL-Wise Consolidated, APT Cashbook, "
            "or APT Accounting Details)",
        )
        _log(session, result, checksum)
        session.commit()
        return result

    try:
        parsed = PARSERS[report_type].extract(grid, name)
    except ParseError as exc:
        result = ImportResult(name, report_type, None, "INVALID", str(exc))
        _log(session, result, checksum)
        session.commit()
        return result

    # Duplicate guard, same rule as the legacy tool ("UPLOAD RESTRICTED").
    if report_type == apt_details.REPORT_TYPE:
        pairs = {(row["date"], row["account_code"]) for row in parsed.rows}
        clashing = _date_code_pairs_present(session, pairs)
        if clashing:
            dates = sorted({d for d, _ in clashing})
            codes = sorted({c for _, c in clashing})
            result = ImportResult(
                name, report_type, parsed.report_date, "DUPLICATE",
                f"A/c {', '.join(codes)} already loaded for "
                f"{dates[0]:%d/%m/%Y}..{dates[-1]:%d/%m/%Y}. Delete that range first to re-import.",
            )
            _log(session, result, checksum)
            session.commit()
            return result
    else:
        dates_in_file = {row["date"] for row in parsed.rows}
        already = dates_in_file & _dates_present(session, report_type)
        if already:
            datestr = ", ".join(d.strftime("%d/%m/%Y") for d in sorted(already))
            result = ImportResult(
                name, report_type, parsed.report_date, "DUPLICATE",
                f"Data already loaded for: {datestr}. Delete that date range first to re-import.",
            )
            _log(session, result, checksum)
            session.commit()
            return result

    model = STORES[report_type]
    for row in parsed.rows:
        session.add(model(**row))
    # A Set-ID GL-wise file also carries the per-SOL breakdown for office-wise recon.
    if report_type == glwise.REPORT_TYPE:
        for row in parsed.sol_rows:
            session.add(FinacleSolDaily(**row))

    message = "; ".join(parsed.warnings) if parsed.warnings else "OK"
    result = ImportResult(name, report_type, parsed.report_date, "PROCESSED", message, len(parsed.rows))
    _log(session, result, checksum)
    session.commit()
    return result


def import_files(session: Session, paths: list[str | Path]) -> list[ImportResult]:
    return [import_file(session, p) for p in paths]


def delete_date_range(
    session: Session, report_type: str, start: dt.date, end: dt.date
) -> int:
    """Delete loaded data for a date range (parity with the legacy delete tools)."""
    model = STORES[report_type]
    count = len(session.scalars(select(model.id).where(model.date >= start, model.date <= end)).all())
    session.execute(delete(model).where(model.date >= start, model.date <= end))
    # GL-wise data lives in two stores; keep them in step.
    if report_type == glwise.REPORT_TYPE:
        session.execute(
            delete(FinacleSolDaily).where(FinacleSolDaily.date >= start, FinacleSolDaily.date <= end)
        )
    session.commit()
    return count


def loaded_date_summary(session: Session) -> dict[str, tuple[dt.date | None, dt.date | None, int]]:
    """Per store: (min date, max date, distinct day count) — for the dashboard."""
    out: dict[str, tuple[dt.date | None, dt.date | None, int]] = {}
    for report_type, model in STORES.items():
        dates = sorted(session.scalars(select(distinct(model.date))).all())
        out[report_type] = (dates[0] if dates else None, dates[-1] if dates else None, len(dates))
    return out
