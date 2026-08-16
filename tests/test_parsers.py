from __future__ import annotations

import datetime as dt

import pytest

from sbco_recon.parsers import cashbook, glwise, read_grid
from sbco_recon.parsers.base import ParseError

from .fixtures import make_cashbook_file, make_glwise_file

DATE = dt.date(2026, 7, 31)


def test_glwise_fingerprint_and_extract(tmp_path):
    f = make_glwise_file(
        tmp_path / "gl.xlsx",
        DATE,
        [
            ("8001000100", "Post Office Savings Bank Account -Receipts", 13472207.00, 0),
            ("8001000200", "Post Office Savings Bank Account -Payments", 0, 7180450.00),
            ("8671004800", "ATM Cash Loaded", 0, 490000.00),
        ],
    )
    grid = read_grid(f)
    assert glwise.fingerprint(grid)
    assert not cashbook.fingerprint(grid)

    parsed = glwise.extract(grid)
    assert parsed.report_date == DATE
    assert len(parsed.rows) == 3
    by_code = {r["account_code"]: r for r in parsed.rows}
    # deposits + withdrawals merged into one amount, as in the legacy tool
    assert by_code["8001000100"]["amount"] == 13472207.00
    assert by_code["8001000200"]["amount"] == 7180450.00
    assert all(r["date"] == DATE for r in parsed.rows)
    # the Total row must not be ingested
    assert "" not in by_code


def test_glwise_rejects_foreign_file(tmp_path):
    f = make_cashbook_file(
        tmp_path / "cb.xlsx", DATE, [("8001000100", "POSB Receipts", "Receipts", 100.0, 0, 0)]
    )
    grid = read_grid(f)
    assert not glwise.fingerprint(grid)
    with pytest.raises(ParseError):
        glwise.extract(grid)


def test_cashbook_extract(tmp_path):
    f = make_cashbook_file(
        tmp_path / "cb.xlsx",
        DATE,
        [
            ("8001000100", "POSB -Receipts", "Receipts", 5000.0, 2000.0, 1000.0),
            ("8001000200", "POSB -Payments", "Payments", 3000.0, 0.0, 500.0),
        ],
    )
    grid = read_grid(f)
    assert cashbook.fingerprint(grid)

    parsed = cashbook.extract(grid)
    assert parsed.report_date == DATE
    assert len(parsed.rows) == 2
    first = parsed.rows[0]
    assert first["account_code"] == "8001000100"
    assert first["total"] == 8000.0
    assert first["ho_amt"] == 5000.0
    assert first["office_id"] == "12345600"


def test_cashbook_dd_mm_yyyy_dates_are_day_first(tmp_path):
    # 04/07/2026 must parse as 4 July, never April 7.
    ambiguous = dt.date(2026, 7, 4)
    f = make_cashbook_file(
        tmp_path / "cb.xlsx", ambiguous, [("8001000100", "POSB", "Receipts", 10.0, 0, 0)]
    )
    parsed = cashbook.extract(read_grid(f))
    assert parsed.report_date == ambiguous
