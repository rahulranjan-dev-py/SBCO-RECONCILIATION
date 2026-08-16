"""The Table-3 register workflow: record, serial numbering, settlement, export.

SB Order 09/2026 para 4(vi): SBCO maintains the CBS Daily Discrepancy
Reconciliation Register for every discrepancy detected, preserved permanently,
serials restarting each financial year. Para 4(viii): a discrepancy is treated
as settled only after the rectification (Misc. transaction / transfer entry)
is verified, which the rectified date records.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import date
from decimal import Decimal
from http.server import ThreadingHTTPServer

import pytest
from openpyxl import load_workbook

from sbco_recon.annexure import RegisterEntry
from sbco_recon.reports import write_discrepancy_register
from sbco_recon.store import Store

D = Decimal


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "reg.db") as s:
        yield s


def entry(day, code, cbs_r=0, cb_r=0, cbs_p=0, cb_p=0, office=""):
    return RegisterEntry(
        entry_date=day, account_code=code, office_name=office,
        cbs_receipt=D(cbs_r), cashbook_receipt=D(cb_r),
        cbs_payment=D(cbs_p), cashbook_payment=D(cb_p))


# ─────────────────────────────────────────────────────── serials and storage

def test_serials_restart_each_financial_year(store):
    store.add_register_entries([
        entry(date(2026, 3, 30), "8001000100", cbs_r=100),
        entry(date(2026, 3, 31), "8001000200", cbs_p=50),
        entry(date(2026, 4, 1), "8001000100", cbs_r=10),   # new FY
    ])
    old = store.register_entries(fy="2025/26")
    new = store.register_entries(fy="2026/27")
    assert [e.serial for e in old] == [1, 2]
    assert [e.serial for e in new] == [1]              # reset from 1
    assert store.register_years() == ["2025/26", "2026/27"]


def test_amounts_round_trip_exactly(store):
    store.add_register_entries(
        [entry(date(2026, 7, 31), "8001000100", cbs_r="13472207.07", cb_r="13472207.00")])
    (loaded,) = store.register_entries()
    assert loaded.cbs_receipt == D("13472207.07")
    assert loaded.difference_receipt == D("0.07")      # Decimal, no float drift
    assert not loaded.is_settled


# ─────────────────────────────────────────────────────────────── settlement

def test_settle_records_the_rectification(store):
    (eid,) = store.add_register_entries(
        [entry(date(2026, 7, 31), "8001000100", cbs_r=5000, cb_r=4500)])
    settled = store.settle_register_entry(
        eid, date(2026, 8, 1), misc_transaction="Misc txn 42/2026",
        transfer_entry="TE 7/2026")
    assert settled.is_settled
    assert settled.rectified_date == date(2026, 8, 1)
    assert settled.misc_transaction == "Misc txn 42/2026"
    # settled entries drop out of the open view but stay on the register
    assert store.register_entries(only_open=True) == []
    assert len(store.register_entries()) == 1


def test_settling_twice_is_refused(store):
    (eid,) = store.add_register_entries(
        [entry(date(2026, 7, 31), "8001000100", cbs_r=100)])
    store.settle_register_entry(eid, date(2026, 8, 1), misc_transaction="x")
    with pytest.raises(ValueError, match="already settled"):
        store.settle_register_entry(eid, date(2026, 8, 2), misc_transaction="y")


def test_settling_before_the_entry_date_is_refused(store):
    (eid,) = store.add_register_entries(
        [entry(date(2026, 7, 31), "8001000100", cbs_r=100)])
    with pytest.raises(ValueError, match="before the entry's own date"):
        store.settle_register_entry(eid, date(2026, 7, 1), misc_transaction="x")


def test_open_codes_guard_feeds_the_dedupe(store):
    day = date(2026, 7, 31)
    store.add_register_entries([entry(day, "8001000100", cbs_r=100)])
    assert store.open_register_codes(day) == {"8001000100"}
    # a settled entry no longer blocks re-recording the same code
    (eid,) = [e.id for e in store.register_entries()]
    store.settle_register_entry(eid, date(2026, 8, 1), misc_transaction="x")
    assert store.open_register_codes(day) == set()


# ─────────────────────────────────────────────────────────────── the export

def test_table3_export_layout(store, tmp_path):
    store.add_register_entries([
        entry(date(2026, 7, 31), "8001000100", cbs_r=5000, cb_r=4500, office="Model SO"),
    ])
    (eid,) = [e.id for e in store.register_entries()]
    store.settle_register_entry(eid, date(2026, 8, 1), misc_transaction="Misc 1/2026")

    target = tmp_path / "t3.xlsx"
    write_discrepancy_register(target, store.register_entries(fy="2026/27"),
                               financial_year="2026/27", ho_name="Manipal")
    ws = load_workbook(target).active
    text = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("CBS Daily Discrepancy Reconciliation Register" in t for t in text)
    assert any("Financial Year 2026/27" in t for t in text)
    # the order's own column letters, and the differences kept as formulas
    for letter in ("a", "f", "o", "(f) - (h)", "(g) - (i)"):
        assert letter in text
    assert any(t.startswith("=F") for t in text)
    assert "Misc 1/2026" in text


# ──────────────────────────────────────────────────────────── HTTP workflow

@pytest.fixture
def server(tmp_path):
    from sbco_recon.webapp import server as srv

    srv.Handler.api = srv.Api(tmp_path / "web.db")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", srv
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as res:
        return res.status, json.loads(res.read())


def _post(base, srv, path, payload):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "X-SBCO-Token": srv.SESSION_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_register_workflow_over_http(server, tmp_path):
    """Record from a reconciliation, list, settle, export - the whole loop."""
    base, srv = server

    # Load one Finacle file so the period has a genuine difference.
    import csv

    report = tmp_path / "fin.csv"
    with report.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["DATE", "SOL ID", "ACCOUNT CODE", "DESCRIPRTION", "RECEIPT"])
        writer.writerow(["31-07-2026", "60001700", "8001000100", "POSB -Receipts", "5000"])
    body = report.read_bytes()
    req = urllib.request.Request(
        f"{base}/api/upload", data=body, method="POST",
        headers={"X-Filename": "fin.csv", "X-SBCO-Token": srv.SESSION_TOKEN})
    with urllib.request.urlopen(req, timeout=10) as res:
        assert json.loads(res.read())["status"] == "loaded"

    # Record the period's differences into the register - twice. The second
    # press adds nothing: same date, same code, still open.
    payload = {"start": "01-07-2026", "end": "31-07-2026"}
    status, first = _post(base, srv, "/api/record-discrepancies", payload)
    assert status == 200 and first["added"] == 1 and first["fy"] == "2026/27"
    status, second = _post(base, srv, "/api/record-discrepancies", payload)
    assert status == 200 and second["added"] == 0 and second["skipped"] == 1

    status, listing = _get(f"{base}/api/register?fy=2026/27")
    assert status == 200
    assert listing["open"] == 1 and listing["settled"] == 0
    (row,) = listing["rows"]
    assert row["code"] == "8001000100"
    assert row["difference_receipt"] == 5000.0
    assert row["serial"] == 1

    # Settling without saying how it was rectified is fine at the API level
    # only if a particular is given; the store requires a valid date.
    status, err = _post(base, srv, "/api/register-settle",
                        {"id": row["id"], "date": "not-a-date"})
    assert status == 400

    status, settled = _post(base, srv, "/api/register-settle",
                            {"id": row["id"], "date": "02-08-2026",
                             "misc": "Misc 9/2026", "te": ""})
    assert status == 200 and settled["row"]["settled"] is True

    status, again = _post(base, srv, "/api/register-settle",
                          {"id": row["id"], "date": "03-08-2026", "misc": "x"})
    assert status == 400 and "already settled" in again["error"]

    # Export Table-3 and download it through the session allow-list.
    status, exported = _post(base, srv, "/api/export",
                             {"kind": "table3", "fy": "2026/27"})
    assert status == 200
    with urllib.request.urlopen(
            f"{base}/download?f={exported['file']}", timeout=10) as res:
        assert res.status == 200
        assert res.read(4) == b"PK\x03\x04"          # a real .xlsx


def test_register_empty_export_reports_cleanly(server):
    base, srv = server
    status, data = _post(base, srv, "/api/export", {"kind": "table3", "fy": "2031/32"})
    assert "no entries" in data["error"]
