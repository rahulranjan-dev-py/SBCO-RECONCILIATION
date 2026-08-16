from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from sbco_recon.db.models import CashbookDaily, FinacleGlDaily, ImportLog
from sbco_recon.parsers import cashbook, glwise
from sbco_recon.services import import_service

from .fixtures import make_cashbook_file, make_glwise_file

DATE = dt.date(2026, 7, 31)

GL_ROWS = [
    ("8001000100", "POSB -Receipts", 13472207.00, 0),
    ("8001000200", "POSB -Payments", 0, 7180450.00),
]
CB_ROWS = [("8001000100", "POSB -Receipts", "Receipts", 13000000.0, 472207.0, 0.0)]


def test_import_glwise_and_cashbook(session, tmp_path):
    gl = make_glwise_file(tmp_path / "gl.xlsx", DATE, GL_ROWS)
    cb = make_cashbook_file(tmp_path / "cb.xlsx", DATE, CB_ROWS)

    results = import_service.import_files(session, [gl, cb])
    assert [r.status for r in results] == ["PROCESSED", "PROCESSED"]
    assert results[0].report_type == glwise.REPORT_TYPE
    assert results[1].report_type == cashbook.REPORT_TYPE

    assert session.scalars(select(FinacleGlDaily)).all()
    assert session.scalars(select(CashbookDaily)).all()
    logs = session.scalars(select(ImportLog)).all()
    assert len(logs) == 2 and all(l.status == "PROCESSED" for l in logs)


def test_duplicate_date_guard(session, tmp_path):
    f1 = make_glwise_file(tmp_path / "gl1.xlsx", DATE, GL_ROWS)
    assert import_service.import_file(session, f1).status == "PROCESSED"

    # Same date, different content -> refused, like the legacy "UPLOAD RESTRICTED"
    f2 = make_glwise_file(tmp_path / "gl2.xlsx", DATE, GL_ROWS[:1])
    result = import_service.import_file(session, f2)
    assert result.status == "DUPLICATE"
    assert "31/07/2026" in result.message

    # Only the first file's rows are stored
    assert len(session.scalars(select(FinacleGlDaily)).all()) == len(GL_ROWS)


def test_identical_file_checksum_guard(session, tmp_path):
    f1 = make_glwise_file(tmp_path / "gl.xlsx", DATE, GL_ROWS)
    assert import_service.import_file(session, f1).status == "PROCESSED"
    result = import_service.import_file(session, f1)
    assert result.status == "DUPLICATE"


def test_unrecognized_file_is_invalid(session, tmp_path):
    from openpyxl import Workbook

    junk = tmp_path / "junk.xlsx"
    wb = Workbook()
    wb.active["A1"] = "hello"
    wb.save(junk)

    result = import_service.import_file(session, junk)
    assert result.status == "INVALID"


def test_delete_date_range_allows_reimport(session, tmp_path):
    f1 = make_glwise_file(tmp_path / "gl.xlsx", DATE, GL_ROWS)
    assert import_service.import_file(session, f1).status == "PROCESSED"

    deleted = import_service.delete_date_range(session, glwise.REPORT_TYPE, DATE, DATE)
    assert deleted == len(GL_ROWS)

    f2 = make_glwise_file(tmp_path / "gl2.xlsx", DATE, GL_ROWS[:1])
    assert import_service.import_file(session, f2).status == "PROCESSED"
