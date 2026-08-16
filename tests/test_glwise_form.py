"""Form-style GL-wise ingestion.

The raw Finacle export (SB Order 09/2026, Annexure-III, page 11) is a form:
the date and SOL sit in a label/value header block and the amount is split
into Deposits (Cr) / Withdrawals (Dr). The columnar detector cannot match it
— it wants per-row date and SOL columns — so detection falls through to the
form parser. These tests pin that path, using the order's own sample figures.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sbco_recon.fiscal import Period
from sbco_recon.ingest.batch import load_one
from sbco_recon.ingest.detect import ReportKind, detect_kind
from sbco_recon.ingest.parse import parse_entries
from sbco_recon.model import Source
from sbco_recon.reconcile import reconcile_by_office
from sbco_recon.store import Store

SAMPLE_DATE = dt.date(2026, 5, 2)


def form_rows(*, date_text="02-05-2026", sections=None):
    """A faithful raw GL-wise sheet; sections = [(sol_desc, data_rows)]."""
    if sections is None:
        sections = [("60001700 - Thygarayanagar H.O", [
            (1, "10003", "8671004800", "ATM Cash Loaded", "0.00", "490,000.00"),
            (2, "24023", "8671004900", "POSB Payment Cheque requested", "7,011,592.00", "0.00"),
            (3, "30001", "8001000200", "Post Office Savings Bank Account -Payments", "0.00", "7,180,450.00"),
            (4, "30001", "8001000100", "Post Office Savings Bank Account -Receipts", "13,472,207.00", "0.00"),
        ])]
    rows = [
        ["", "GL IT2.0 Transaction GL Wise Report - Consolidated(Previous Day)",
         "", "", "Run Date : 04/05/2026 11.25 AM"],
        ["Date :", date_text],
        ["Sol ID :", "60001700"],
        ["BO Code :", ""],
        ["Channel ID :", ""],
        ["Set ID / Desc :", "TAMI1 - TAMI1"],
    ]
    for sol_desc, data in sections:
        rows.append(["Sol ID / Desc :", sol_desc])
        rows.append(["S.No", "GL Sub Head Code", "IT2.0 A/C Code",
                     "IT2.0 Acct Code Desc", "Deposits (Cr)", "Withdrawals (Dr)"])
        rows.extend([list(r) for r in data])
        deposits = sum(Decimal(str(r[4]).replace(",", "")) for r in data)
        withdrawals = sum(Decimal(str(r[5]).replace(",", "")) for r in data)
        rows.append(["", "", "", "Total", f"{deposits:,}", f"{withdrawals:,}"])
        rows.append([])
    return rows


def test_detects_raw_export_as_finacle_gl_wise():
    detection = detect_kind(form_rows())
    assert detection.kind is ReportKind.FINACLE_GL_WISE
    assert detection.form is not None
    assert detection.source is Source.FINACLE_GL


def test_parses_the_orders_own_sample_figures():
    rows = form_rows()
    detection = detect_kind(rows)
    entries, warnings = parse_entries(rows, detection, "sample.xls")

    assert len(entries) == 4
    by_code = {e.account_code: e for e in entries}
    # deposits + withdrawals folded into one exact Decimal amount
    assert by_code["8001000100"].amount == Decimal("13472207.00")
    assert by_code["8001000200"].amount == Decimal("7180450.00")
    assert by_code["8671004800"].amount == Decimal("490000.00")
    # the header date is stamped on every entry; 02-05-2026 is 2 May, day-first
    assert all(e.txn_date == SAMPLE_DATE for e in entries)
    # the header SOL is stamped on every entry
    assert all(e.sol_id == "60001700" for e in entries)
    # the Total footer row was not ingested
    assert sum(e.amount for e in entries) == Decimal("28154249.00")


def test_setid_report_keeps_each_sections_sol():
    rows = form_rows(sections=[
        ("60001700 - Model H.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "1,000.00", "0.00")]),
        ("60001801 - Model S.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "600.00", "0.00"),
            (2, "30001", "8001000200", "POSB -Payments", "0.00", "250.00")]),
    ])
    entries, warnings = parse_entries(rows, detect_kind(rows), "set.xls")

    assert len(entries) == 3
    by_sol_code = {(e.sol_id, e.account_code): e.amount for e in entries}
    assert by_sol_code[("60001700", "8001000100")] == Decimal("1000.00")
    assert by_sol_code[("60001801", "8001000100")] == Decimal("600.00")
    assert by_sol_code[("60001801", "8001000200")] == Decimal("250.00")
    assert any("2 SOL sections" in w for w in warnings)


def test_form_without_a_date_stays_unknown():
    rows = form_rows(date_text="")
    detection = detect_kind(rows)
    assert detection.kind is ReportKind.UNKNOWN


def test_end_to_end_load_and_officewise(tmp_path):
    """A Set-ID form file loads through the normal batch path and feeds the
    office-wise reconciliation."""
    import csv

    rows = form_rows(sections=[
        ("60001700 - Model H.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "1,000.00", "0.00")]),
        ("60001801 - Model S.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "600.00", "0.00")]),
    ])
    report = tmp_path / "glwise.csv"
    with report.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)

    offices = tmp_path / "offices.csv"
    with offices.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["OFFICE_NAME", "OFFICE_ID", "SOL_ID/BO_CODE", "SOL_ID_GROUP"])
        writer.writerow(["Model HO", "12345600", "60001700", "60001700"])
        writer.writerow(["Model SO", "12345601", "60001801", "60001801"])

    store = Store(tmp_path / "t.db")
    assert load_one(store, offices).ok
    outcome = load_one(store, report)
    assert outcome.ok, outcome.reason
    assert outcome.rows == 2

    period = Period(dt.date(2026, 5, 1), dt.date(2026, 5, 31))
    result = reconcile_by_office(store, "8001000100", period)
    by_office = {r.office.name: r.finacle for r in result.rows}
    assert by_office["Model HO"] == Decimal("1000.00")
    assert by_office["Model SO"] == Decimal("600.00")


def test_columnar_glwise_still_detected_columnar():
    """The staging-sheet layout (per-row date and SOL) must keep using the
    columnar path — the form fallback only runs when that fails."""
    rows = [
        ["DATE", "SOL ID", "OFFICE", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT"],
        ["02-05-2026", "60001700", "Model HO", "8001000100", "POSB -Receipts", "1000.00"],
        ["02-05-2026", "60001700", "Model HO", "8001000200", "POSB -Payments", "500.00"],
    ]
    detection = detect_kind(rows)
    assert detection.kind is ReportKind.FINACLE_GL_WISE
    assert detection.form is None
    assert "sol_id" in detection.columns
