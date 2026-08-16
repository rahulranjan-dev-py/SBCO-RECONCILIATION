"""Local application server.

Runs on the clerk's own PC and serves the interface to their browser. Nothing
leaves the machine: no network calls, no accounts, no cloud. The server binds
to 127.0.0.1 only, so it is not reachable from anywhere else on the network.

Built on the Python standard library so there is nothing extra to install on a
locked-down office PC.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import socket
import tempfile
import threading
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, refdata
from ..annexure import build_table1, entries_from_reconciliation
from ..fiscal import Period, fy_label, month_end, month_start, quarter_label
from ..ingest.batch import load_one
from ..model import Source
from ..normalize import parse_amount, parse_date
from ..reconcile import (coverage, reconcile_by_code, reconcile_by_date,
                         reconcile_by_office, reconcile_clearing)
from ..reports import (write_annexure_iv_table1, write_discrepancy_register,
                       write_discrepancy_report, write_recon_sheet)
from ..store import Store, adopt_legacy_database, default_db_path

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 80 * 1024 * 1024

# Issued once per run and handed to the page that the server itself serves.
# Any other origin cannot read it, so it cannot forge a mutating request.
SESSION_TOKEN = secrets.token_urlsafe(24)

# Only files this session generated may be downloaded. Serving anything present
# in the output folder meant the database itself was retrievable (QA-07).
DOWNLOADABLE = set()


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value))


class Api:
    """All application logic the interface can reach. One method per route."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        # Reports go to a folder the clerk can find, never into the program
        # directory (QA-09).
        self.outdir = Path(self.db_path).resolve().parent / "reports"
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _store(self):
        return Store(self.db_path)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _period(q) -> Period:
        start = parse_date(q.get("start", [""])[0], allow_month_only=True)
        end = parse_date(q.get("end", [""])[0], allow_month_only=True)
        if start and end:
            return Period(start, end)
        month = parse_date(q.get("month", [""])[0], allow_month_only=True) or date.today()
        return Period(month_start(month), month_end(month))

    @staticmethod
    def _rows(result):
        return [{
            "code": r.account_code,
            "description": r.description,
            "finacle": r.finacle,
            "cashbook": r.cashbook,
            "difference": r.difference,
            "matched": r.matched,
        } for r in result.rows]

    # -------------------------------------------------------------- routes

    def state(self, q):
        with self._store() as store:
            batches = store.batches()
            return {
                "version": __version__,
                "folder": str(self.outdir),
                "config": {
                    "ddo": store.get("ddo_code", ""),
                    "ho": store.get("ho_name", ""),
                    "division": store.get("division", ""),
                },
                "offices": [{"name": o.name, "office_id": o.office_id,
                             "sol_id": o.sol_id, "sol_group": o.sol_group,
                             "is_bo": o.is_branch_office} for o in store.offices()],
                "batches": [dict(b) for b in batches],
                "today": date.today().isoformat(),
                "codes": refdata.dashboard_codes(),
            }

    def reconcile(self, q):
        period = self._period(q)
        with self._store() as store:
            result = reconcile_by_code(store, period,
                                       include_zero_rows=q.get("all", ["0"])[0] == "1")
            cov = coverage(store, period)
            return {
                "period": {"start": period.start, "end": period.end,
                           "label": str(period), "quarter": quarter_label(period.start)},
                "rows": self._rows(result),
                "warnings": result.warnings,
                "coverage": {
                    "complete": cov.complete,
                    "missing_finacle": cov.missing_finacle[:40],
                    "missing_cashbook": cov.missing_cashbook[:40],
                    "missing_finacle_count": len(cov.missing_finacle),
                    "missing_cashbook_count": len(cov.missing_cashbook),
                },
                "totals": {
                    "finacle": result.total_finacle,
                    "cashbook": result.total_cashbook,
                    "difference": result.total_difference,
                    "breaks": len(result.differences),
                    "codes": len(result.rows),
                },
            }

    def datewise(self, q):
        period = self._period(q)
        code = q.get("code", [""])[0]
        with self._store() as store:
            rows = reconcile_by_date(store, code, period,
                                     only_differences=q.get("all", ["0"])[0] != "1")
            return {"code": code, "description": refdata.describe(code),
                    "rows": [{"day": r.day, "finacle": r.finacle,
                              "cashbook": r.cashbook, "difference": r.difference,
                              "matched": r.matched} for r in rows]}

    def officewise(self, q):
        period = self._period(q)
        code = q.get("code", [""])[0]
        with self._store() as store:
            result = reconcile_by_office(store, code, period)
            return {"code": code, "description": refdata.describe(code),
                    "warnings": result.warnings,
                    "rows": [{"name": r.office.name, "office_id": r.office.office_id,
                              "sol_id": r.office.sol_id, "is_bo": r.office.is_branch_office,
                              "finacle": r.finacle, "apt": r.apt,
                              "difference": r.difference, "matched": r.matched}
                             for r in result.rows]}

    def clearing(self, q):
        period = self._period(q)
        with self._store() as store:
            rows = reconcile_clearing(store, period)
            return {"rows": [{"category": r.category, "side": r.side,
                              "mismatch_code": r.mismatch_code,
                              "cleared_code": r.cleared_code,
                              "mismatch": r.mismatch, "cleared": r.cleared,
                              "outstanding": r.outstanding, "matched": r.matched}
                             for r in rows]}

    def transfer_entries(self, q):
        with self._store() as store:
            month = q.get("month", [""])[0]
            rows = store.transfer_entries(month or None)
            return {"rows": [dict(r) for r in rows]}

    # ---------------------------------------------------------- mutations

    def upload(self, filename, body):
        """Write the uploaded bytes to a temp file and run it through ingest."""
        safe = Path(unquote(filename)).name or "upload.dat"
        # QA-15: the copy used to be left in /tmp for ever, one directory per
        # upload, holding a full duplicate of every financial report.
        with tempfile.TemporaryDirectory(prefix="sbco_") as tmpdir:
            target = Path(tmpdir) / safe
            target.write_bytes(body)
            with self.lock, self._store() as store:
                outcome = load_one(store, target)
        return {
            "file": safe, "status": outcome.status, "reason": outcome.reason,
            "detail": outcome.detail, "rows": outcome.rows,
            "batch_id": outcome.batch_id,
        }

    def save_config(self, payload):
        with self._store() as store:
            for key, field in (("ddo_code", "ddo"), ("ho_name", "ho"),
                               ("division", "division")):
                if field in payload:
                    store.set(key, str(payload[field]).strip())
        return self.state({})

    def reverse(self, payload):
        try:
            batch_id = int(payload["batch_id"])
        except (TypeError, ValueError):
            return {"error": "That upload reference is not valid."}
        with self.lock, self._store() as store:
            row = store.conn.execute(
                "SELECT * FROM batch WHERE id=?", (batch_id,)).fetchone()
            if row is None:
                return {"error": f"There is no upload numbered {batch_id}."}
            if row["reversed_at"]:
                return {"error": f"Upload {batch_id} was already undone on "
                                 f"{row['reversed_at']}."}
            removed = store.reverse_batch(batch_id)
        return {"removed": removed}

    def add_transfer_entry(self, payload):
        # QA-17: parse_amount already handles lakh grouping, brackets, trailing
        # minus and the rupee sign. Decimal(str(...)) rejected "1,000" with a
        # raw ConversionSyntax error shown to the clerk.
        amount = parse_amount(payload.get("amount"))
        if amount is None:
            return {"error": "Enter the amount in digits, for example 1000 or "
                             "1,000.50."}
        for field, label in (("month", "month"), ("from_code", "from code"),
                             ("to_code", "to code")):
            if not str(payload.get(field, "")).strip():
                return {"error": f"The {label} is needed."}
        with self._store() as store:
            store.add_transfer_entry(
                str(payload["month"]).strip(), str(payload["from_code"]).strip(),
                str(payload["to_code"]).strip(), amount,
                payload.get("remarks", ""))
        return {"ok": True}

    def annexure(self, payload):
        month = parse_date(payload.get("month", ""), allow_month_only=True) or date.today()
        period = Period(month_start(month), month_end(month))
        with self._store() as store:
            result = reconcile_by_code(store, period)
            cfg = (store.get("ddo_code", ""), store.get("ho_name", ""),
                   store.get("division", ""))
            if not all(cfg):
                return {"error": "Add your DDO code, HO name and division in "
                                 "Settings before generating the return."}
            month_label = f"{month:%b-%Y}"
            transfer_entries = store.transfer_entries(month_label)
            result = build_table1(result, month_label, transfer_entries)

            name = f"CBS-MRR-TABLE1-{month:%b-%y}.xlsx"
            write_annexure_iv_table1(
                self.outdir / name, result, ddo_code=cfg[0], ho_name=cfg[1],
                division=cfg[2], month=month,
                include_matched=bool(payload.get("include_matched")))
            DOWNLOADABLE.add(name)
            totals = result.totals()
            return {"file": name, "breaks": len(result.differences),
                    "difference": result.total_difference,
                    "difference_receipt": totals["difference_receipt"],
                    "difference_payment": totals["difference_payment"],
                    "transfer_entries": len(transfer_entries)}

    def export(self, payload):
        with self._store() as store:
            kind = payload.get("kind", "reconcile")
            if kind == "table3":
                fy = str(payload.get("fy", "")).strip() or fy_label(date.today())
                entries = store.register_entries(fy=fy)
                if not entries:
                    return {"error": f"The register has no entries for {fy}."}
                name = f"Table3-Register-{fy.replace('/', '-')}.xlsx"
                write_discrepancy_register(self.outdir / name, entries,
                                           financial_year=fy,
                                           ho_name=store.get("ho_name", ""))
            elif kind == "discrepancy":
                name = f"Discrepancy-Report-{date.today():%Y-%m-%d}.xlsx"
                write_discrepancy_report(self.outdir / name, store.discrepancies())
            else:
                period = Period(parse_date(payload["start"]), parse_date(payload["end"]))
                result = reconcile_by_code(store, period, check_coverage=False,
                                           include_zero_rows=bool(payload.get("all")))
                name = f"Reconciliation-{period.start:%d%b%y}-{period.end:%d%b%y}.xlsx"
                write_recon_sheet(self.outdir / name, result,
                                  include_matched=bool(payload.get("all")))
        DOWNLOADABLE.add(name)
        return {"file": name}

    # ------------------------------------------------------ Table-3 register

    @staticmethod
    def _register_row(entry) -> dict:
        return {
            "id": entry.id, "fy": entry.financial_year, "serial": entry.serial,
            "date": entry.entry_date, "code": entry.account_code,
            "description": entry.description, "office": entry.office_name,
            "cbs_receipt": entry.cbs_receipt, "cbs_payment": entry.cbs_payment,
            "cashbook_receipt": entry.cashbook_receipt,
            "cashbook_payment": entry.cashbook_payment,
            "difference_receipt": entry.difference_receipt,
            "difference_payment": entry.difference_payment,
            "settled": entry.is_settled, "rectified_date": entry.rectified_date,
            "misc_transaction": entry.misc_transaction,
            "transfer_entry": entry.transfer_entry,
            "days_outstanding": entry.days_outstanding,
        }

    def register(self, q):
        with self._store() as store:
            years = store.register_years()
            fy = q.get("fy", [""])[0] or (years[-1] if years else fy_label(date.today()))
            entries = store.register_entries(fy=fy)
            return {
                "fy": fy, "years": years or [fy],
                "rows": [self._register_row(e) for e in entries],
                "open": sum(1 for e in entries if not e.is_settled),
                "settled": sum(1 for e in entries if e.is_settled),
            }

    def record_discrepancies(self, payload):
        """Save the period's differences into the Table-3 register.

        The differences are recomputed here rather than trusted from the page,
        and a code that already has an open entry for the same date is skipped,
        so pressing the button twice cannot double-enter a discrepancy.
        """
        period = Period(parse_date(payload["start"]), parse_date(payload["end"]))
        entry_date = parse_date(payload.get("date", "")) or period.end
        with self._store() as store:
            result = reconcile_by_code(store, period, check_coverage=False)
            candidates = entries_from_reconciliation(
                result, entry_date, office_name=str(payload.get("office", "")).strip())
            already = store.open_register_codes(entry_date)
            fresh = [e for e in candidates if e.account_code not in already]
            store.add_register_entries(fresh)
            return {"added": len(fresh),
                    "skipped": len(candidates) - len(fresh),
                    "fy": fy_label(entry_date)}

    def settle_register(self, payload):
        try:
            entry_id = int(payload.get("id"))
        except (TypeError, ValueError):
            raise ValueError("That register entry reference is not valid.")
        rectified = parse_date(payload.get("date", ""))
        if rectified is None:
            raise ValueError("Enter the date of rectification as dd-mm-yyyy.")
        with self._store() as store:
            entry = store.settle_register_entry(
                entry_id, rectified,
                misc_transaction=str(payload.get("misc", "")).strip(),
                transfer_entry=str(payload.get("te", "")).strip())
            return {"ok": True, "row": self._register_row(entry)}


class Handler(BaseHTTPRequestHandler):
    server_version = f"SBCO/{__version__}"
    api: Api = None

    def log_message(self, fmt, *args):
        pass  # keep the console clean for the person watching it

    # ---------------------------------------------------------------- guards

    def _same_origin(self) -> bool:
        """Reject requests that another website made on the user's behalf.

        text/plain is a CORS-simple content type, so a cross-origin POST never
        triggers a preflight. The handler parsed JSON regardless of
        Content-Type, so any page the clerk had open could rewrite settings or
        undo uploads (QA-03).
        """
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if origin not in (f"http://{host}", f"https://{host}"):
                return False
        return True

    def _known_host(self) -> bool:
        """Only answer to loopback names, so a domain that re-resolves to
        127.0.0.1 cannot become same-origin (QA-07)."""
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1", "")

    def _authorised(self) -> bool:
        return self.headers.get("X-SBCO-Token") == SESSION_TOKEN

    # ------------------------------------------------------------- plumbing

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, default=jsonable).encode(), "application/json")

    def _fail(self, message, code=400):
        self._json({"error": message}, code)

    def _read_body(self) -> bytes:
        """Read the request body, whether it arrives sized or chunked.

        QA-16: a chunked body was previously read as zero bytes, so a good file
        was reported empty. Rejecting it with 411 fixed the silent truncation
        but replaced it with a broken pipe - the server answered while the
        browser was still writing. Decoding the chunks handles both.
        """
        encoding = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in encoding:
            chunks, total = [], 0
            while True:
                line = self.rfile.readline(65536).strip()
                if not line:
                    break
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError:
                    raise ValueError("The upload was malformed. Try again.")
                if size == 0:
                    while True:                      # consume trailers
                        trailer = self.rfile.readline(65536)
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    break
                total += size
                if total > MAX_UPLOAD:
                    raise ValueError("That file is larger than 80 MB.")
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)                   # trailing CRLF
            return b"".join(chunks)

        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        try:
            length = int(raw)
        except ValueError:
            raise ValueError("Could not read that request.")
        if length > MAX_UPLOAD:
            raise ValueError("That file is larger than 80 MB.")
        return self.rfile.read(length) if length else b""

    @staticmethod
    def _opaque(exc) -> str:
        """Log the detail, show the user something they can act on (QA-14)."""
        ref = secrets.token_hex(3)
        print(f"  [error {ref}] {type(exc).__name__}: {exc}")
        return (f"Something went wrong and the step was stopped. Nothing was "
                f"changed. Reference {ref} - it is printed in the tool's window.")

    # ---------------------------------------------------------------- GET

    def do_GET(self):
        if not self._known_host():
            return self._fail("This address is not served here.", 421)
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)

        if path.startswith("/api/"):
            name = path[5:]
            routes = {
                "state": self.api.state, "reconcile": self.api.reconcile,
                "datewise": self.api.datewise, "officewise": self.api.officewise,
                "clearing": self.api.clearing,
                "transfer-entries": self.api.transfer_entries,
                "register": self.api.register,
            }
            if name not in routes:
                return self._fail("No such action.", 404)
            try:
                return self._json(routes[name](query))
            except ValueError as exc:
                return self._fail(str(exc), 400)      # written, user-facing text
            except Exception as exc:
                return self._fail(self._opaque(exc), 500)

        if path == "/download":
            name = Path(unquote(query.get("f", [""])[0])).name
            target = self.api.outdir / name
            if name not in DOWNLOADABLE:
                return self._fail("That file was not produced by this session.", 403)
            if not target.exists():
                return self._fail("That file is no longer in the folder.", 404)
            ctype = (mimetypes.guess_type(name)[0]
                     or "application/octet-stream")
            return self._send(200, target.read_bytes(), ctype,
                              {"Content-Disposition": f'attachment; filename="{name}"'})

        return self._static(path)

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._fail("Not found.", 404)
        ctype = mimetypes.guess_type(target.name)[0] or "text/plain"
        data = target.read_bytes()
        if target.name == "index.html":
            data = data.replace(b"__SBCO_TOKEN__", SESSION_TOKEN.encode())
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    # --------------------------------------------------------------- POST

    def do_POST(self):
        if not self._known_host():
            return self._fail("This address is not served here.", 421)
        if not self._same_origin():
            return self._fail("Refused: that request came from another website.", 403)
        if not self._authorised():
            return self._fail("Refused: this page is out of date. Reload the tool.",
                              403)

        url = urlparse(self.path)
        try:
            body = self._read_body()
        except ValueError as exc:
            return self._fail(str(exc), 413 if "80 MB" in str(exc) else 400)

        if url.path == "/api/upload":
            filename = self.headers.get("X-Filename", "upload.dat")
            try:
                return self._json(self.api.upload(filename, body))
            except Exception as exc:
                return self._fail(self._opaque(exc), 500)

        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return self._fail("Could not read that request.")

        routes = {
            "/api/config": self.api.save_config,
            "/api/reverse": self.api.reverse,
            "/api/annexure": self.api.annexure,
            "/api/export": self.api.export,
            "/api/transfer-entry": self.api.add_transfer_entry,
            "/api/record-discrepancies": self.api.record_discrepancies,
            "/api/register-settle": self.api.settle_register,
        }
        if url.path not in routes:
            return self._fail("No such action.", 404)
        try:
            return self._json(routes[url.path](payload))
        except ValueError as exc:
            return self._fail(str(exc), 400)
        except KeyError as exc:
            return self._fail(f"A required value was missing: {exc}.", 400)
        except Exception as exc:
            return self._fail(self._opaque(exc), 500)


def _free_port(preferred=8765):
    for port in range(preferred, preferred + 40):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0   # let the OS choose; serve() reads the real port back


def serve(db_path=None, port=None, open_browser=True):
    """Start the application and open it in the default browser."""
    if db_path is None:
        db_path = default_db_path()
        adopt_legacy_database(db_path)
    Handler.api = Api(db_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", port or _free_port()), Handler)
    # QA-20: when every candidate port was busy the printed URL said ":0",
    # which no browser can reach. Read the bound port back instead.
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    print(f"\n  SBCO Reconciliation Tool {__version__}")
    print(f"  Working folder: {Handler.api.outdir}")
    print(f"  Open in your browser: {url}")
    print("  Keep this window open while you work. Close it to stop.\n")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("  Stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve(os.environ.get("SBCO_DB") or None)
