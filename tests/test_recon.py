from __future__ import annotations

import datetime as dt

from sbco_recon.services import import_service, recon_service

from .fixtures import make_cashbook_file, make_glwise_file

D1 = dt.date(2026, 7, 30)
D2 = dt.date(2026, 7, 31)


def _load(session, tmp_path):
    # Day 1: POSB receipts match, payments differ by 500
    make_glwise_file(
        tmp_path / "gl1.xlsx", D1,
        [("8001000100", "POSB -Receipts", 10000.0, 0), ("8001000200", "POSB -Payments", 0, 4000.0)],
    )
    make_cashbook_file(
        tmp_path / "cb1.xlsx", D1,
        [
            ("8001000100", "POSB -Receipts", "Receipts", 10000.0, 0, 0),
            ("8001000200", "POSB -Payments", "Payments", 3500.0, 0, 0),
        ],
    )
    # Day 2: an account present only in Finacle
    make_glwise_file(tmp_path / "gl2.xlsx", D2, [("8001000100", "POSB -Receipts", 2000.0, 0)])
    make_cashbook_file(
        tmp_path / "cb2.xlsx", D2, [("8001000100", "POSB -Receipts", "Receipts", 2000.0, 0, 0)]
    )
    results = import_service.import_files(
        session,
        [tmp_path / "gl1.xlsx", tmp_path / "cb1.xlsx", tmp_path / "gl2.xlsx", tmp_path / "cb2.xlsx"],
    )
    assert all(r.status == "PROCESSED" for r in results)


def test_daily_codewise(session, tmp_path):
    _load(session, tmp_path)
    df = recon_service.daily_codewise(session, D1, D2)
    row = df[df["Account Code"] == "8001000200"].iloc[0]
    assert row["Finacle"] == 4000.0
    assert row["Cashbook"] == 3500.0
    assert row["Difference"] == 500.0
    # description joined from the seeded master
    posb = df[df["Account Code"] == "8001000100"].iloc[0]
    assert "Savings Bank" in posb["Description"]
    assert posb["Difference"] == 0.0


def test_nonzero_filter(session, tmp_path):
    _load(session, tmp_path)
    df = recon_service.daily_codewise(session, D1, D2, nonzero_only=True)
    assert list(df["Account Code"]) == ["8001000200"]


def test_datewise_drilldown(session, tmp_path):
    _load(session, tmp_path)
    df = recon_service.datewise(session, "8001000100", D1, D2)
    assert len(df) == 2
    assert df.iloc[0]["Finacle"] == 10000.0
    assert df.iloc[1]["Difference"] == 0.0


def test_mismatch_summary_has_eight_pairs(session, tmp_path):
    _load(session, tmp_path)
    df = recon_service.mismatch_summary(session, D1, D2)
    assert len(df) == 8
    assert set(df["Outstanding"]) == {0.0}
