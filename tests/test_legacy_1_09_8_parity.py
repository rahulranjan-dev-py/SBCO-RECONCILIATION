"""Behaviour recovered from CASHBOOK_TOOL_for_SBCO 1.09.8 / 1.09.81 and the
recorded demo of that tool (docs/LEGACY_DEMO_ANALYSIS.md).

Each test pins one thing the legacy workflow relied on:
  * the form-style *Transaction Report* (office-wise source) is read as a
    Finacle report of its own, with bare "NNNN - Office" section labels;
  * the raw APT "Accounting Details Office Wise" header, whose DEDUCT_DATE
    column sits left of DATE and whose OFFICE_ID may be blank;
  * the date-level duplicate guard ("Duplicate Found: UPLOAD RESTRICTED");
  * Table-2 carried forward month by month, seeded once, with transfer
    entries scoped to either Table-1 (current) or Table-2 (prior);
  * office attribution on register entries, in the legacy remark style.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sbco_recon.fiscal import Period
from sbco_recon.ingest.batch import load_files, load_one
from sbco_recon.ingest.detect import ReportKind, detect_kind
from sbco_recon.ingest.parse import parse_entries
from sbco_recon.model import Source
from sbco_recon.reconcile import office_attribution, reconcile_by_office
from sbco_recon.store import Store
from sbco_recon.table2 import table2_for_month
from sbco_recon.webapp.server import parse_table2_opening

D = Decimal
JULY = Period(date(2026, 7, 1), date(2026, 7, 31))


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "t.db") as st:
        yield st


# ────────────────────────────────────────── Transaction Report (form style)

def txn_report_rows(sections):
    """The 'GL IT2.0 Transaction Report' as the legacy Set-ID sheet saw it:
    title in row 5, date in row 8, bare 'NNNN - Office' labels per SOL,
    Credit/Debit amount headers."""
    rows = [[], [], [], [],
            ["", "", "", "GL IT2.0 Transaction Report - Consolidated(Previous Day)"],
            [], [],
            ["", "Date :", "01-07-2026"],
            []]
    for label, data in sections:
        rows.append(["", label])
        rows.append(["S.No", "GL Sub Head Code", "IT2.0 A/C Code",
                     "IT2.0 Acct Code Desc", "Credit", "Debit"])
        rows.extend(list(r) for r in data)
        rows.append(["", "", "", "Total", "", ""])
        rows.append([])
    return rows


def test_transaction_report_is_its_own_finacle_source():
    rows = txn_report_rows([
        ("60001700 - Manipal H.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "94,000.00", "0.00")]),
        ("60001801 - Barkur S.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "40,000.00", "0.00"),
            (2, "30001", "8001000200", "POSB -Payments", "0.00", "1,500.00")]),
    ])
    detection = detect_kind(rows)
    assert detection.kind is ReportKind.FINACLE_TXN
    assert detection.source is Source.FINACLE_TXN

    entries, _ = parse_entries(rows, detection, "txn.xls")
    assert {(e.sol_id, e.account_code, e.amount) for e in entries} == {
        ("60001700", "8001000100", D("94000.00")),
        ("60001801", "8001000100", D("40000.00")),
        ("60001801", "8001000200", D("1500.00")),
    }
    assert all(e.source is Source.FINACLE_TXN and e.txn_date == date(2026, 7, 1)
               for e in entries)


def test_transaction_report_and_daily_glwise_coexist(tmp_path, store):
    """The legacy sheets held both for the same day; so must the store."""
    glwise = write_csv(tmp_path / "gl.csv", [
        ["DATE", "SOL ID", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT"],
        ["01-07-2026", "60001700", "8001000100", "POSB -Receipts", "134000"]])
    txn = write_csv(tmp_path / "txn.csv", txn_report_rows([
        ("60001700 - Manipal H.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "94,000.00", "0.00")]),
        ("60001801 - Barkur S.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "40,000.00", "0.00")])]))
    a, b = load_files(store, [glwise, txn])
    assert a.ok and b.ok, (a, b)
    assert store.totals_by_office(Source.FINACLE_TXN, "8001000100", JULY.start, JULY.end) == {
        "60001700": D("94000.00"), "60001801": D("40000.00")}


# ─────────────────────────────────────────── APT Accounting Details header

APT_RAW_HEADER = ["DEDUCT_DATE", "OFFICE_ID", "OFFICE_NAME", "DATE",
                  "ACCT_CODE", "AMT", "REMARKS"]


def test_apt_raw_header_binds_date_not_deduct_date():
    rows = [APT_RAW_HEADER,
            ["03-07-2026", "12345600", "Manipal HO", "01-07-2026", "8001000100", "94000", ""]]
    detection = detect_kind(rows)
    assert detection.source is Source.APT_DETAILS
    (entry,), _ = parse_entries(rows, detection, "export(3).xls")
    assert entry.txn_date == date(2026, 7, 1)
    assert entry.office_id == "12345600"
    assert entry.office_name == "Manipal HO"
    assert entry.amount == D("94000")


def test_apt_without_office_id_matches_the_master_by_name(tmp_path, store):
    """The portal export can leave OFFICE_ID blank; 'Barkur S.O' must still
    land on the master's 'Barkur SO'."""
    write_csv(tmp_path / "offices.csv", [
        ["OFFICE_NAME", "OFFICE_ID", "SOL_ID/BO_CODE", "SOL_ID_GROUP"],
        ["Manipal HO", "12345600", "60001700", "60001700"],
        ["Barkur SO", "12345601", "60001801", "60001801"]])
    write_csv(tmp_path / "txn.csv", txn_report_rows([
        ("60001700 - Manipal H.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "94,000.00", "0.00")]),
        ("60001801 - Barkur S.O", [
            (1, "30001", "8001000100", "POSB -Receipts", "40,000.00", "0.00")])]))
    write_csv(tmp_path / "apt.csv", [
        ["DEDUCT_DATE", "OFFICE_NAME", "DATE", "ACCT_CODE", "AMT", "REMARKS"],
        ["01-07-2026", "Manipal H.O", "01-07-2026", "8001000100", "94000", ""],
        ["01-07-2026", "Barkur S.O", "01-07-2026", "8001000100", "39000", ""]])
    outcomes = load_files(store, [tmp_path / "offices.csv", tmp_path / "txn.csv",
                                  tmp_path / "apt.csv"])
    assert all(o.ok for o in outcomes), outcomes

    result = reconcile_by_office(store, "8001000100", JULY)
    by_name = {r.office.name: r for r in result.rows}
    assert by_name["Manipal HO"].difference == 0
    assert by_name["Barkur SO"].difference == D("1000")
    assert office_attribution(result) == "Barkur SO (1,000)"


# ───────────────────────────────────────────── date-level duplicate guard

def glwise_csv(tmp, name, day="01-07-2026", code="8001000100", amount="1000", run="1"):
    return write_csv(tmp / name, [
        ["DATE", "SOL ID", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT", "RUN"],
        [day, "60001700", code, "POSB", amount, run]])


def test_a_redownloaded_report_for_a_loaded_date_is_refused(tmp_path, store):
    first = load_one(store, glwise_csv(tmp_path, "export.csv"))
    again = load_one(store, glwise_csv(tmp_path, "export(1).csv", run="2"))
    assert first.ok
    assert again.status == "duplicate"
    assert "01-07-2026" in again.reason
    assert f"#{first.batch_id}" in again.detail and "undo" in again.detail
    assert len(store.batches()) == 1


def test_the_guard_is_per_source_and_per_date(tmp_path, store):
    assert load_one(store, glwise_csv(tmp_path, "gl.csv")).ok
    # another day: fine
    assert load_one(store, glwise_csv(tmp_path, "gl2.csv", day="02-07-2026")).ok
    # the cashbook for the same day: a different source, fine
    cashbook = write_csv(tmp_path / "cb.csv", [
        ["Date", "Office Name", "Office ID", "Account Code",
         "Account Code Description", "Part", "Receipts/Payments",
         "HO", "SO", "BO", "Total", "Progressive Total", "Grand Total"],
        ["01-07-2026", "MODEL HO", "12345600", "8001000100", "POSB Receipts",
         "Part I", "Receipt", 1000, 0, 0, "1000", "1000", "1000"]])
    assert load_one(store, cashbook).ok


def test_undoing_the_upload_lifts_the_guard(tmp_path, store):
    first = load_one(store, glwise_csv(tmp_path, "gl.csv"))
    store.reverse_batch(first.batch_id)
    assert load_one(store, glwise_csv(tmp_path, "gl-again.csv", run="2")).ok


def test_allow_duplicate_bypasses_the_guard(tmp_path, store):
    assert load_one(store, glwise_csv(tmp_path, "gl.csv")).ok
    assert load_one(store, glwise_csv(tmp_path, "gl2.csv", run="2"),
                    allow_duplicate=True).ok


def test_apt_guard_is_per_account_code(tmp_path, store):
    """One APT file carries one code for a date range; a second code for the
    same dates is a new report, the same code again is a duplicate."""
    def apt(name, code, amount):
        return write_csv(tmp_path / name, [APT_RAW_HEADER,
            ["01-07-2026", "12345600", "HO", "01-07-2026", code, amount, ""]])
    assert load_one(store, apt("a.csv", "8001000100", "100")).ok
    assert load_one(store, apt("b.csv", "8001000200", "200")).ok
    again = load_one(store, apt("c.csv", "8001000100", "150"))   # fresh content
    assert again.status == "duplicate"
    assert "8001000100" in again.reason


# ───────────────────────────────────────────────── Table-2 month chain

def month_files(tmp, tag, day, *codes):
    """Finacle + cashbook files for one day; codes = (code, finacle, cashbook)."""
    fin = write_csv(tmp / f"gl-{tag}.csv", [
        ["DATE", "SOL ID", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT"],
        *[[day, "60001700", code, "POSB", finacle] for code, finacle, _ in codes]])
    cb = write_csv(tmp / f"cb-{tag}.csv", [
        ["Date", "Office Name", "Office ID", "Account Code",
         "Account Code Description", "Part", "Receipts/Payments",
         "HO", "SO", "BO", "Total", "Progressive Total", "Grand Total"],
        *[[day, "MODEL HO", "12345600", code, "POSB", "Part I", "Receipt",
           0, 0, 0, cashbook, cashbook, cashbook] for code, _, cashbook in codes]])
    return fin, cb


RECEIPTS = "8001000100"      # POSB Receipts  (receipt side)
PAYMENTS = "8001000200"      # POSB Payments  (payment side)


def test_table2_carries_last_months_closing_forward(tmp_path, store):
    load_files(store, month_files(tmp_path, "jun", "15-06-2026", (RECEIPTS, "5000", "4000")))
    load_files(store, month_files(tmp_path, "jul", "15-07-2026", (RECEIPTS, "9000", "8700")))

    june = table2_for_month(store, "Jun-2026")
    (row,) = june.rows
    assert (row.opening_receipt, row.current_receipt, row.closing_receipt) == (0, D("1000"), D("1000"))

    july = table2_for_month(store, "Jul-2026")
    (row,) = july.rows
    assert row.opening_receipt == D("1000")
    assert row.current_receipt == D("300")
    assert row.closing_receipt == D("1300")
    assert row.first_month == "Jun-2026"


def test_prior_scope_te_rectifies_table2_without_touching_table1(tmp_path, store):
    """June booked 1,000 of receipts under Payments by mistake: +1,000 on the
    receipts code, -1,000 on the payments code. July's TE moves it back. The
    TE belongs to Table-2 (scope 'prior'), so July's Table-1 stays clean."""
    load_files(store, month_files(tmp_path, "jun", "15-06-2026",
                                  (RECEIPTS, "5000", "4000"), (PAYMENTS, "1000", "2000")))
    load_files(store, month_files(tmp_path, "jul", "15-07-2026",
                                  (RECEIPTS, "9000", "9000"), (PAYMENTS, "700", "700")))
    store.add_transfer_entry("Jul-2026", PAYMENTS, RECEIPTS, D("1000"),
                             "TE 12 dt 20-07-2026", scope="prior")

    july = table2_for_month(store, "Jul-2026")
    by_code = {r.account_code: r for r in july.rows}
    rec, pay = by_code[RECEIPTS], by_code[PAYMENTS]
    assert (rec.opening_receipt, rec.current_receipt, rec.rectified_receipt, rec.closing_receipt) \
        == (D("1000"), 0, D("1000"), 0)
    assert (pay.opening_payment, pay.current_payment, pay.rectified_payment, pay.closing_payment) \
        == (D("-1000"), 0, D("-1000"), 0)
    assert july.pending == [] and july.balances and not july.warnings

    assert [r["scope"] for r in store.transfer_entries("Jul-2026")] == ["prior"]
    assert store.transfer_entries("Jul-2026", scope="current") == []


def test_a_seed_replaces_the_computed_opening(tmp_path, store):
    load_files(store, month_files(tmp_path, "jul", "15-07-2026", (RECEIPTS, "9000", "8700")))
    rows = parse_table2_opening([
        ["AC_CODE", "DESCRIPTION", "RECEIPT_DIFF", "PAYMENT_DIFF"],
        ["8001000100", "POSB Receipts", "2,500.00", "0"],
        ["8001000200", "POSB Payments", "0", "750"],
        ["8001000300", "settled", "0", "0"],          # zero rows are dropped
        ["", "junk", "1", "1"],
    ])
    assert [r[0] for r in rows] == ["8001000100", "8001000200"]
    assert store.replace_table2_opening("Jul-2026", rows) == 2
    assert "Jul-2026" in store.months_with_data()

    july = table2_for_month(store, "Jul-2026")
    by_code = {r.account_code: r for r in july.rows}
    assert by_code["8001000100"].opening_receipt == D("2500.00")
    assert by_code["8001000100"].current_receipt == D("300")
    assert by_code["8001000100"].closing_receipt == D("2800.00")
    assert by_code["8001000200"].opening_payment == D("750")
    assert by_code["8001000200"].closing_payment == D("750")


def test_store_scope_rejects_anything_but_current_or_prior(store):
    with pytest.raises(ValueError):
        store.add_transfer_entry("Jul-2026", "8001000100", "8001000200", D(1), scope="both")


# ────────────────────────────────────────────────────── schema migration

def test_an_older_database_gains_the_new_columns(tmp_path):
    """A v2.6 data file must open and keep working after the upgrade."""
    old = tmp_path / "old.db"
    with Store(old) as st:
        pass
    with sqlite3.connect(old) as raw:
        raw.execute("ALTER TABLE entry DROP COLUMN office_name")
        raw.execute("ALTER TABLE transfer_entry DROP COLUMN scope")
        raw.execute("DROP TABLE table2_opening")
    import sbco_recon.store as store_mod
    store_mod._MIGRATED.discard(str(old))     # forget the in-process schema cache

    with Store(old) as st:
        cols = {r[1] for r in st.conn.execute("PRAGMA table_info(entry)")}
        assert "office_name" in cols
        st.add_transfer_entry("Jul-2026", "8001000100", "8001000200", D(5))
        assert st.transfer_entries("Jul-2026")[0]["scope"] == "current"
        assert st.table2_opening("Jul-2026") == []


# ─────────────────────────────────────────────────────────── over HTTP

@pytest.fixture
def server(tmp_path):
    from sbco_recon.webapp import server as srv

    srv.Handler.api = srv.Api(tmp_path / "web.db")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", srv
    httpd.shutdown()
    httpd.server_close()


def _post(base, srv, path, payload):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-SBCO-Token": srv.SESSION_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def _upload(base, srv, path, filename, body, **extra):
    req = urllib.request.Request(
        f"{base}{path}", data=body, method="POST",
        headers={"X-Filename": filename, "X-SBCO-Token": srv.SESSION_TOKEN, **extra})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_table2_over_http(server, tmp_path):
    base, srv = server
    _post(base, srv, "/api/config",
          {"ddo": "DDO1", "ho": "Manipal HO", "division": "Udupi"})
    for path in month_files(tmp_path, "jul", "15-07-2026", (RECEIPTS, "9000", "8700")):
        status, out = _upload(base, srv, "/api/upload", path.name, path.read_bytes())
        assert status == 200 and out["status"] == "loaded", out

    # the opening seed needs a month
    seed = (b"AC_CODE,DESCRIPTION,RECEIPT_DIFF,PAYMENT_DIFF\n"
            b"8001000100,POSB Receipts,2500,0\n"
            b"8001000200,POSB Payments,0,-2500\n")
    status, out = _upload(base, srv, "/api/table2-opening", "opening.csv", seed)
    assert status == 400
    status, out = _upload(base, srv, "/api/table2-opening", "opening.csv", seed,
                          **{"X-Month": "Jul-2026"})
    assert status == 200 and out == {"month": "Jul-2026", "rows": 2}

    status, out = _post(base, srv, "/api/annexure2", {"month": "Jul-2026"})
    assert status == 200, out
    assert out["file"] == "CBS-MRR-TABLE2-Jul-26.xlsx"
    assert out["seeded"] is True
    assert out["rows"] == 2 and out["pending"] == 2
    assert D(str(out["current"])) == D("300")
    assert D(str(out["closing"])) == D("300")        # +2,800 and -2,500, signed
    assert (srv.Handler.api.outdir / out["file"]).exists()

    # a prior-scope TE lands in 'rectified'
    status, out = _post(base, srv, "/api/transfer-entry",
                        {"month": "Jul-2026", "from_code": "8001000200", "to_code": "8001000100",
                         "amount": "2500", "remarks": "TE 7", "scope": "prior"})
    assert status == 200, out
    status, out = _post(base, srv, "/api/annexure2", {"month": "Jul-2026"})
    assert out["pending"] == 1 and out["warnings"] == []    # only July's own 300 left
    assert D(str(out["closing"])) == D("300")


def test_recorded_discrepancies_name_the_office(server, tmp_path):
    base, srv = server
    files = [
        write_csv(tmp_path / "offices.csv", [
            ["OFFICE_NAME", "OFFICE_ID", "SOL_ID/BO_CODE", "SOL_ID_GROUP"],
            ["Manipal HO", "12345600", "60001700", "60001700"],
            ["Barkur SO", "12345601", "60001801", "60001801"]]),
        write_csv(tmp_path / "txn.csv", txn_report_rows([
            ("60001700 - Manipal H.O", [
                (1, "30001", "8001000100", "POSB -Receipts", "94,000.00", "0.00")]),
            ("60001801 - Barkur S.O", [
                (1, "30001", "8001000100", "POSB -Receipts", "40,000.00", "0.00")])])),
        write_csv(tmp_path / "apt.csv", [APT_RAW_HEADER,
            ["01-07-2026", "12345600", "Manipal HO", "01-07-2026", "8001000100", "94000", ""],
            ["01-07-2026", "12345601", "Barkur SO", "01-07-2026", "8001000100", "39000", ""]]),
        write_csv(tmp_path / "gl.csv", [
            ["DATE", "SOL ID", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT"],
            ["01-07-2026", "60001700", "8001000100", "POSB -Receipts", "134000"]]),
    ]
    for path in files:
        status, out = _upload(base, srv, "/api/upload", path.name, path.read_bytes())
        assert status == 200 and out["status"] == "loaded", (path.name, out)

    status, out = _post(base, srv, "/api/record-discrepancies",
                        {"start": "01-07-2026", "end": "31-07-2026"})
    assert status == 200 and out["added"] == 1, out
    with urllib.request.urlopen(f"{base}/api/register?fy=2026/27", timeout=10) as res:
        (row,) = json.loads(res.read())["rows"]
    assert row["office"] == "Barkur SO (1,000)"
