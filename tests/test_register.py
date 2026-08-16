from __future__ import annotations

import datetime as dt

from sbco_recon.services import register_service


def test_financial_year_boundaries():
    assert register_service.financial_year(dt.date(2026, 4, 1)) == "2026-27"
    assert register_service.financial_year(dt.date(2026, 3, 31)) == "2025-26"
    assert register_service.financial_year(dt.date(2027, 1, 15)) == "2026-27"


def test_serials_reset_per_fy(session):
    e1 = register_service.add_entry(session, dt.date(2026, 3, 30), "8001000100", cbs_receipt=100)
    e2 = register_service.add_entry(session, dt.date(2026, 3, 31), "8001000200", cbs_payment=50)
    e3 = register_service.add_entry(session, dt.date(2026, 4, 1), "8001000100", cbs_receipt=10)
    assert (e1.fy, e1.serial) == ("2025-26", 1)
    assert (e2.fy, e2.serial) == ("2025-26", 2)
    assert (e3.fy, e3.serial) == ("2026-27", 1)  # reset at new FY


def test_description_autofilled_and_settlement(session):
    entry = register_service.add_entry(
        session, dt.date(2026, 7, 31), "8001000100", cbs_receipt=5000, cb_receipt=4500
    )
    assert "Savings Bank" in entry.description
    assert entry.diff_receipt == 500.0
    assert entry.status == "OPEN"

    settled = register_service.settle_entry(
        session, entry.id, dt.date(2026, 8, 1), misc_txn_particulars="TE 12/2026"
    )
    assert settled.status == "SETTLED"
    assert settled.rectified_on == dt.date(2026, 8, 1)

    df = register_service.register_frame(session)
    assert len(df) == 1
    assert df.iloc[0]["Status"] == "SETTLED"
