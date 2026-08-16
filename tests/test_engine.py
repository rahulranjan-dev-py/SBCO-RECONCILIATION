"""Test suite.

Sections marked REGRESSION correspond to numbered findings in the review of
CASHBOOK_TOOL_for_SBCO_1_09_6.xlsb. Each one fails if the old behaviour ever
comes back.
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sbco_recon.fiscal import Period, quarter_label
from sbco_recon.ingest import detect_kind, read_rows
from sbco_recon.ingest.batch import load_files, load_one, summarise
from sbco_recon.model import Source
from sbco_recon.normalize import parse_account_code, parse_amount, parse_date
from sbco_recon.reconcile import (coverage, reconcile_by_code, reconcile_by_date,
                                  reconcile_by_office, reconcile_clearing,
                                  rollup_branch_offices)
from sbco_recon.store import Store

D = Decimal


# ------------------------------------------------------------------ fixtures

def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


CASHBOOK_HEADER = ["Date", "Office Name", "Office ID", "Account Code",
                   "Account Code Description", "Part", "Receipts/Payments",
                   "HO", "SO", "BO", "Total", "Progressive Total", "Grand Total"]

FINACLE_HEADER = ["DATE", "SOL ID", "OFFICE", "ACCOUNT CODE", "DESCRIPRTION",
                  "RECEIPT", "VALIDATOR"]

APT_HEADER = ["DEDUCT_DATE", "OFFICE_ID", "OFFICE_NAME", "DATE", "ACCT_CODE",
              "AMT", "REMARKS", "VALIDATOR"]

OFFICE_HEADER = ["OFFICE_NAME", "OFFICE_ID", "SOL_ID/BO_CODE", "SOL_ID_GROUP"]


def make_cashbook(tmp, name="cashbook.csv", rows=None):
    rows = rows or [
        ["01-07-2026", "MODEL HO", "12345600", "8001000100", "POSB Receipts",
         "Part I", "Receipt", 1000, 0, 0, "1,00,000.00", "100000", "100000"],
        ["01-07-2026", "MODEL HO", "12345600", "8001000200", "POSB Payments",
         "Part I", "Payment", 0, 0, 0, "50000", "150000", "150000"],
    ]
    return write_csv(tmp / name, CASHBOOK_HEADER, rows)


def make_finacle(tmp, name="finacle.csv", rows=None):
    rows = rows or [
        ["01-07-2026", "58345610", "MODEL HO", "8001000100", "POSB Receipts", "100000", ""],
        ["01-07-2026", "58345610", "MODEL HO", "8001000200", "POSB Payments", "50024", ""],
    ]
    return write_csv(tmp / name, FINACLE_HEADER, rows)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as st:
        yield st


# ------------------------------------------------------- REGRESSION: F-13

def test_quarters_work_after_the_legacy_expiry_date():
    """The VALIDATOR sheet stopped at 31-Mar-2029. These must never stop."""
    assert quarter_label(date(2026, 7, 15)) == "Q2 - 2026/27"
    assert quarter_label(date(2029, 4, 1)) == "Q1 - 2029/30"
    assert quarter_label(date(2040, 12, 31)) == "Q3 - 2040/41"
    assert Period.for_quarter(date(2031, 5, 9)) == Period(date(2031, 4, 1), date(2031, 6, 30))


@pytest.mark.parametrize("d,expected", [
    (date(2026, 4, 1), 1), (date(2026, 6, 30), 1),
    (date(2026, 7, 1), 2), (date(2026, 9, 30), 2),
    (date(2026, 10, 1), 3), (date(2026, 12, 31), 3),
    (date(2027, 1, 1), 4), (date(2027, 3, 31), 4),
])
def test_quarter_boundaries(d, expected):
    from sbco_recon.fiscal import quarter
    assert quarter(d) == expected


# ------------------------------------------------------- REGRESSION: F-24

def test_dates_parse_the_same_regardless_of_machine_locale():
    """03-04-2026 is 3 April everywhere. The legacy tool needed a Windows setting."""
    assert parse_date("03-04-2026") == date(2026, 4, 3)
    assert parse_date("03/04/2026") == date(2026, 4, 3)
    assert parse_date(46204) == date(2026, 7, 1)          # Excel serial from the workbook
    assert parse_date("01-Jul-2026") == date(2026, 7, 1)
    assert parse_date("Jul-26", allow_month_only=True) == date(2026, 7, 1)
    assert parse_date("") is None
    assert parse_date("not a date") is None
    assert parse_date(12) is None                          # too small to be a real serial


def test_amounts_parse_indian_and_accounting_formats():
    assert parse_amount("1,00,000.00") == D("100000.00")   # Indian lakh grouping
    assert parse_amount("(1,615,000.00)") == D("-1615000.00")
    assert parse_amount("269-") == D("-269")
    assert parse_amount("\u20b9 1,234.56") == D("1234.56")
    assert parse_amount("-") is None
    assert parse_amount(None) is None


def test_amounts_are_exact_not_floating_point():
    """Float arithmetic turns an exact match into a phantom difference."""
    total = sum((parse_amount("0.1") for _ in range(10)), D(0))
    assert total == D("1.0")
    assert total - D(1) == 0


def test_account_codes_normalise_from_excel_floats():
    assert parse_account_code(8001000100.0) == "8001000100"
    assert parse_account_code("8001000100.0") == "8001000100"
    assert parse_account_code(" 8001000100 ") == "8001000100"
    assert parse_account_code("abc") is None


# ------------------------------------------------------- REGRESSION: F-11

def test_detection_survives_an_inserted_column(tmp_path):
    """The legacy check read L2 by position; one extra column broke it."""
    header = CASHBOOK_HEADER[:3] + ["NEW COLUMN"] + CASHBOOK_HEADER[3:]
    rows = [["01-07-2026", "MODEL HO", "12345600", "x", "8001000100", "POSB",
             "Part I", "Receipt", 0, 0, 0, "100000", "100000", "100000"]]
    path = write_csv(tmp_path / "shifted.csv", header, rows)
    detection = detect_kind(read_rows(path))
    assert detection.kind.value == "cashbook"
    assert detection.columns["account_code"] == 4   # found by name, not position


def test_detection_finds_header_below_title_banners(tmp_path):
    """Portal exports carry title rows above the real header."""
    path = tmp_path / "banner.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Department of Posts"])
        w.writerow(["Cashbook Report for July 2026"])
        w.writerow([])
        w.writerow(CASHBOOK_HEADER)
        w.writerow(["01-07-2026", "HO", "12345600", "8001000100", "POSB",
                    "Part I", "Receipt", 0, 0, 0, "100000", "100000", "100000"])
    detection = detect_kind(read_rows(path))
    assert detection.kind.value == "cashbook"
    assert detection.header_row == 3


def test_unrecognised_file_is_rejected_with_a_specific_reason(tmp_path, store):
    path = write_csv(tmp_path / "junk.csv", ["Alpha", "Beta", "Gamma"], [[1, 2, 3]])
    outcome = load_one(store, path)
    assert outcome.status == "rejected"
    assert outcome.reason == "unrecognised report"
    assert outcome.reason and outcome.detail != ""


# ------------------------------------------------------- REGRESSION: F-04

def test_every_submitted_file_produces_exactly_one_outcome(tmp_path, store):
    """The legacy summary reported 3 selected, 2 processed, 0 failed."""
    paths = [
        make_cashbook(tmp_path),
        make_finacle(tmp_path),
        write_csv(tmp_path / "junk.csv", ["A", "B", "C"], [[1, 2, 3]]),
        tmp_path / "does_not_exist.xls",
    ]
    outcomes = load_files(store, paths)
    assert len(outcomes) == len(paths)

    counts = summarise(outcomes)
    assert counts["submitted"] == 4
    assert (counts["loaded"] + counts["rejected"]
            + counts["duplicate"] + counts["failed"]) == 4


def test_single_file_batch_reports_one_not_zero(tmp_path, store):
    """The legacy 0-based single-file path reported 'TOTAL FILES SELECTED: 0'."""
    counts = summarise(load_files(store, [make_cashbook(tmp_path)]))
    assert counts["submitted"] == 1
    assert counts["loaded"] == 1


def test_reloading_the_same_file_is_detected_not_double_counted(tmp_path, store):
    path = make_cashbook(tmp_path)
    first, second = load_one(store, path), load_one(store, path)
    assert first.status == "loaded"
    assert second.status == "duplicate"

    period = Period(date(2026, 7, 1), date(2026, 7, 31))
    totals = store.totals_by_code(Source.CASHBOOK, period.start, period.end)
    assert totals["8001000100"] == D("100000.00")   # not 200000


def test_a_failed_file_leaves_no_partial_data(tmp_path, store):
    """Atomicity: a rejected file contributes nothing at all."""
    bad = write_csv(tmp_path / "bad.csv", CASHBOOK_HEADER,
                    [["not-a-date", "HO", "1", "not-a-code", "x", "", "", 0, 0, 0,
                      "abc", "", ""]])
    outcome = load_one(store, bad)
    assert outcome.status == "rejected"
    assert store.conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0] == 0


def test_batch_reversal_removes_only_that_file(tmp_path, store):
    """Legacy deletes worked by date range and took correct data with them."""
    a = load_one(store, make_cashbook(tmp_path, "a.csv"))
    b = load_one(store, make_cashbook(tmp_path, "b.csv", rows=[
        ["01-07-2026", "HO", "12345600", "8001000300", "RD Receipts",
         "Part I", "Receipt", 0, 0, 0, "7500", "7500", "7500"]]))
    assert a.ok and b.ok

    store.reverse_batch(a.batch_id)
    totals = store.totals_by_code(Source.CASHBOOK, date(2026, 7, 1), date(2026, 7, 31))
    assert "8001000100" not in totals        # file a is gone
    assert totals["8001000300"] == D("7500")  # file b, same date, untouched


# ---------------------------------------------------------- core engine

def test_reconciliation_finds_the_difference(tmp_path, store):
    load_files(store, [make_cashbook(tmp_path), make_finacle(tmp_path)])
    result = reconcile_by_code(store, Period(date(2026, 7, 1), date(2026, 7, 31)))

    by_code = {r.account_code: r for r in result.rows}
    assert by_code["8001000100"].difference == 0
    assert by_code["8001000100"].matched
    assert by_code["8001000200"].difference == D("24")   # 50024 - 50000
    assert not by_code["8001000200"].matched
    assert [r.account_code for r in result.differences] == ["8001000200"]
    assert result.total_difference == D("24")


def test_reconciliation_respects_the_period(tmp_path, store):
    load_files(store, [
        make_finacle(tmp_path, rows=[
            ["01-07-2026", "58345610", "HO", "8001000100", "POSB", "100", ""],
            ["15-08-2026", "58345610", "HO", "8001000100", "POSB", "999", ""]])])
    july = reconcile_by_code(store, Period(date(2026, 7, 1), date(2026, 7, 31)),
                             check_coverage=False)
    assert {r.account_code: r.finacle for r in july.rows}["8001000100"] == D("100")


def test_unknown_account_code_is_reported_never_dropped(tmp_path, store):
    load_files(store, [make_finacle(tmp_path, rows=[
        ["01-07-2026", "58345610", "HO", "9999999999", "Invented code", "500", ""]])])
    result = reconcile_by_code(store, Period(date(2026, 7, 1), date(2026, 7, 31)),
                               check_coverage=False)
    assert "9999999999" in {r.account_code for r in result.rows}
    assert any("9999999999" in w for w in result.warnings)


def test_missing_days_produce_a_coverage_warning(tmp_path, store):
    """A day with no cashbook upload must not masquerade as a real difference."""
    load_files(store, [make_cashbook(tmp_path), make_finacle(tmp_path)])
    period = Period(date(2026, 7, 1), date(2026, 7, 3))
    cov = coverage(store, period)
    assert not cov.complete
    assert cov.missing_cashbook == [date(2026, 7, 2), date(2026, 7, 3)]
    assert any("not reliable" in w for w in cov.warnings())


def test_datewise_drilldown_locates_the_day(tmp_path, store):
    load_files(store, [
        make_cashbook(tmp_path, rows=[
            ["01-07-2026", "HO", "1", "8001000100", "POSB", "", "", 0, 0, 0, "100", "", ""],
            ["02-07-2026", "HO", "1", "8001000100", "POSB", "", "", 0, 0, 0, "200", "", ""]]),
        make_finacle(tmp_path, rows=[
            ["01-07-2026", "58345610", "HO", "8001000100", "POSB", "100", ""],
            ["02-07-2026", "58345610", "HO", "8001000100", "POSB", "275", ""]])])
    rows = reconcile_by_date(store, "8001000100",
                             Period(date(2026, 7, 1), date(2026, 7, 2)),
                             only_differences=True)
    assert len(rows) == 1
    assert rows[0].day == date(2026, 7, 2)
    assert rows[0].difference == D("75")


# --------------------------------------------------------- office-wise

def test_office_master_import_and_office_wise_reconciliation(tmp_path, store):
    offices = write_csv(tmp_path / "offices.csv", OFFICE_HEADER, [
        ["MODEL HO", "12345600", "58345610", "58345610"],
        ["MODEL SO 1", "12345601", "58345611", "58345611"],
        ["MODEL BO 1.1", "12345602", "A1234", "58345611"],
    ])
    assert load_one(store, offices).ok
    assert len(store.offices()) == 3

    write_csv(tmp_path / "gl.csv", FINACLE_HEADER, [
        ["01-07-2026", "58345610", "HO", "8001000100", "POSB", "1000", ""],
        ["01-07-2026", "A1234", "BO", "8001000100", "POSB", "250", ""]])
    write_csv(tmp_path / "apt.csv", APT_HEADER, [
        ["01-07-2026", "12345600", "HO", "01-07-2026", "8001000100", "1000", "", ""],
        ["01-07-2026", "12345602", "BO", "01-07-2026", "8001000100", "200", "", ""]])
    load_files(store, [tmp_path / "gl.csv", tmp_path / "apt.csv"])

    result = reconcile_by_office(store, "8001000100",
                                 Period(date(2026, 7, 1), date(2026, 7, 31)))
    by_name = {r.office.name: r for r in result.rows}
    assert by_name["MODEL HO"].difference == 0
    assert by_name["MODEL BO 1.1"].difference == D("50")


def test_branch_offices_roll_up_to_their_parent_so(tmp_path, store):
    load_one(store, write_csv(tmp_path / "offices.csv", OFFICE_HEADER, [
        ["MODEL SO 1", "12345601", "58345611", "58345611"],
        ["MODEL BO 1.1", "12345602", "A1234", "58345611"],
        ["MODEL BO 1.2", "12345603", "B8765", "58345611"]]))
    load_one(store, write_csv(tmp_path / "gl.csv", FINACLE_HEADER, [
        ["01-07-2026", "58345611", "SO", "8001000100", "POSB", "100", ""],
        ["01-07-2026", "A1234", "BO", "8001000100", "POSB", "20", ""],
        ["01-07-2026", "B8765", "BO", "8001000100", "POSB", "5", ""]]))
    result = reconcile_by_office(store, "8001000100",
                                 Period(date(2026, 7, 1), date(2026, 7, 31)))
    rolled = rollup_branch_offices(result.rows)
    assert len(rolled) == 1
    assert rolled[0].finacle == D("125")


def test_office_master_with_orphan_sol_group_is_rejected(tmp_path, store):
    path = write_csv(tmp_path / "bad_offices.csv", OFFICE_HEADER, [
        ["MODEL SO 1", "12345601", "58345611", "58345611"],
        ["MODEL BO 1.1", "12345602", "A1234", "99999999"],   # parent does not exist
    ])
    outcome = load_one(store, path)
    assert outcome.status == "rejected"
    assert "SOL ID group" in outcome.detail


# ------------------------------------------------------ clearing accounts

def test_clearing_pairs_reconcile_mismatch_against_cleared(tmp_path, store):
    load_one(store, write_csv(tmp_path / "cb.csv", CASHBOOK_HEADER, [
        ["01-07-2026", "HO", "1", "8671002400", "CBS Receipts Mismatch",
         "", "", 0, 0, 0, "5000", "", ""],
        ["01-07-2026", "HO", "1", "8671002500", "CBS Receipts Mismatch Cleared",
         "", "", 0, 0, 0, "3000", "", ""]]))
    rows = reconcile_clearing(store, Period(date(2026, 7, 1), date(2026, 7, 31)))
    assert len(rows) == 8
    cbs_receipts = next(r for r in rows if r.mismatch_code == "8671002400")
    assert cbs_receipts.outstanding == D("2000")
    assert not cbs_receipts.matched


# ----------------------------------------------------------- reference data

def test_reference_data_loaded_from_the_legacy_workbook():
    from sbco_recon import refdata
    assert len(refdata.account_codes()) == 3006
    assert len(refdata.dashboard_codes()) == 428
    assert len(refdata.clearing_pairs()) == 8
    assert refdata.describe("8001000100") == "Post Office Savings Bank Account -Receipts"


def test_transfer_entries_adjust_the_reconciliation(tmp_path, store):
    from sbco_recon.reconcile import apply_transfer_entries
    load_files(store, [make_cashbook(tmp_path), make_finacle(tmp_path)])
    period = Period(date(2026, 7, 1), date(2026, 7, 31))

    before = reconcile_by_code(store, period, check_coverage=False)
    assert {r.account_code: r.difference for r in before.rows}["8001000200"] == D("24")

    store.add_transfer_entry("Jul-2026", "8001000100", "8001000200", D("24"),
                             "TE approved by SPOs")
    after = apply_transfer_entries(
        reconcile_by_code(store, period, check_coverage=False), store, "Jul-2026")
    by_code = {r.account_code: r for r in after.rows}
    assert by_code["8001000200"].difference == 0
    assert by_code["8001000100"].difference == D("24")
