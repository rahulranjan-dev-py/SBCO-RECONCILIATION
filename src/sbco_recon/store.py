"""Durable store for ledger entries.

Replaces the legacy tool's staging sheets (TEMP, TEMP.FIN, TEMP.FIN.GL,
TEMP.FIN.TR, TEMP.CBR, TEMP.CLR). Those sheets were the database, which is
why the workbook carried 1.77 MB of empty formatted cells and why a crash
mid-pipeline could leave half-imported data behind.

Three guarantees this provides that the workbook could not:

1. Atomicity - a file's rows are committed in one transaction or not at all.
2. Idempotency - the SHA-256 of every loaded file is recorded, so uploading
   the same cashbook twice is detected instead of silently double-counting.
3. Auditability - every entry knows which batch, which file and which
   timestamp it came from, and batches can be reversed individually.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from .model import Entry, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    loaded_at    TEXT NOT NULL,
    period_start TEXT,
    period_end   TEXT,
    row_count    INTEGER NOT NULL DEFAULT 0,
    reversed_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_batch_sha ON batch(sha256, source)
    WHERE reversed_at IS NULL;

CREATE TABLE IF NOT EXISTS entry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     INTEGER NOT NULL REFERENCES batch(id),
    txn_date     TEXT NOT NULL,
    account_code TEXT NOT NULL,
    amount       TEXT NOT NULL,          -- Decimal as text: exact, no float drift
    source       TEXT NOT NULL,
    office_id    TEXT NOT NULL DEFAULT '',
    sol_id       TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_entry_lookup ON entry(source, txn_date, account_code);
CREATE INDEX IF NOT EXISTS ix_entry_batch  ON entry(batch_id);
CREATE INDEX IF NOT EXISTS ix_entry_office ON entry(source, account_code, office_id);

CREATE TABLE IF NOT EXISTS office (
    office_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    sol_id     TEXT NOT NULL,
    sol_group  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discrepancy (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    account_code TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    finacle      TEXT NOT NULL,
    cashbook     TEXT NOT NULL,
    difference   TEXT NOT NULL,
    remarks      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS register (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fy               TEXT NOT NULL,          -- '2026/27'; serials reset each FY
    serial           INTEGER NOT NULL,
    entry_date       TEXT NOT NULL,
    account_code     TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    office_name      TEXT NOT NULL DEFAULT '',
    cbs_receipt      TEXT NOT NULL DEFAULT '0',
    cbs_payment      TEXT NOT NULL DEFAULT '0',
    cashbook_receipt TEXT NOT NULL DEFAULT '0',
    cashbook_payment TEXT NOT NULL DEFAULT '0',
    rectified_date   TEXT,
    misc_transaction TEXT NOT NULL DEFAULT '',
    transfer_entry   TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    UNIQUE (fy, serial)
);

CREATE TABLE IF NOT EXISTS transfer_entry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    month        TEXT NOT NULL,
    from_code    TEXT NOT NULL,
    to_code      TEXT NOT NULL,
    amount       TEXT NOT NULL,
    remarks      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def file_digest(path) -> str:
    """SHA-256 of a file, streamed so large exports do not load into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


_MIGRATED = set()


def default_db_path() -> Path:
    """Where the data file lives when nobody says otherwise.

    QA-09: the Windows launcher does `cd /d "%~dp0"`, so the database was
    created inside the extracted program folder. Re-extracting the archive to
    upgrade, or tidying the install directory, destroyed every loaded report
    and the whole discrepancy register. Keep data out of the program folder.
    """
    base = os.environ.get("SBCO_DATA_DIR")
    if not base:
        base = (os.environ.get("LOCALAPPDATA")            # Windows
                or os.environ.get("XDG_DATA_HOME")        # Linux
                or str(Path.home() / ".local" / "share"))
    folder = Path(base) / "SBCO"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "sbco_recon.db"


LEGACY_NAME = "sbco_recon.db"


def adopt_legacy_database(target=None) -> bool:
    """Carry a v2.0 data file over to the v2.1 location, once.

    Before 2.1 the launcher ran `cd /d "%~dp0"`, so the database was created
    wherever the tool was started from - usually the program folder. Upgrading
    would otherwise look like total data loss: the tool opens, finds nothing,
    and every loaded report appears to have vanished.

    Call this once, deliberately, at the point the default location is about
    to be used. It must not run as a side effect of computing a path: doing so
    fired it during unrelated commands and copied a half-written database,
    carrying the settings over but none of the loaded reports.

    The old file is copied, never moved, so a rollback to 2.0 still works.

    The copy goes through SQLite's own backup API rather than shutil. The
    database runs in WAL mode, so the most recent commits live in a
    sbco_recon.db-wal sidecar; copying the main file alone silently drops
    them, which looked exactly like a successful migration that had lost every
    uploaded report.
    """
    target = Path(target) if target else default_db_path()
    if target.exists():
        return False
    for candidate in (Path.cwd() / LEGACY_NAME,
                      Path(__file__).resolve().parents[2] / LEGACY_NAME):
        if not candidate.is_file() or candidate.resolve() == target.resolve():
            continue
        try:
            source = sqlite3.connect(f"file:{candidate}?mode=ro", uri=True)
            try:
                destination = sqlite3.connect(str(target))
                try:
                    source.backup(destination)      # includes un-checkpointed WAL
                finally:
                    destination.close()
            finally:
                source.close()
        except sqlite3.Error as exc:
            target.unlink(missing_ok=True)
            print(f"  Could not carry over the data at {candidate}: {exc}")
            return False
        print(f"  Carried your existing data over from {candidate}")
        print(f"  to {target}. The original has been left where it was.")
        return True
    return False


class Store:
    """Connection wrapper. Use as a context manager."""

    def __init__(self, path="sbco_recon.db"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 15000")
        # QA-18: the whole schema was re-executed on every HTTP request, a
        # dozen DDL statements per page load, and two first-run requests could
        # race on index creation.
        if self.path not in _MIGRATED:
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()
            _MIGRATED.add(self.path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.conn.close()

    # ---------------------------------------------------------------- batches

    def find_batch_by_digest(self, sha256: str, source: Source) -> Optional[sqlite3.Row]:
        """Has this exact file already been loaded for this source?"""
        return self.conn.execute(
            "SELECT * FROM batch WHERE sha256=? AND source=? AND reversed_at IS NULL",
            (sha256, source.value),
        ).fetchone()

    class Duplicate(Exception):
        """Raised when an identical file is already loaded for this source."""

        def __init__(self, batch_id, loaded_at):
            self.batch_id, self.loaded_at = batch_id, loaded_at
            super().__init__(f"already loaded as batch {batch_id}")

    def add_batch(self, source: Source, path, sha256: str,
                  entries: Iterable[Entry]) -> int:
        """Insert a batch and all its entries atomically.

        Either every row lands or none does. The legacy tool appended rows
        sheet by sheet with no transaction, so an error midway left a partial
        import that looked complete.
        """
        rows = list(entries)
        dates = [e.txn_date for e in rows]
        try:
            return self._insert_batch(source, path, sha256, rows, dates)
        except sqlite3.IntegrityError:
            # QA-19: find-then-insert was not atomic, so a second uploader
            # (another tab, or the CLI) got a raw IntegrityError and an HTTP
            # 500 instead of being told the file was a duplicate.
            existing = self.find_batch_by_digest(sha256, source)
            if existing is None:
                raise
            raise Store.Duplicate(existing["id"], existing["loaded_at"]) from None

    def _insert_batch(self, source, path, sha256, rows, dates) -> int:
        with self.conn:  # BEGIN ... COMMIT / ROLLBACK
            cur = self.conn.execute(
                """INSERT INTO batch
                   (source, file_name, file_path, sha256, loaded_at,
                    period_start, period_end, row_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (source.value, Path(path).name, str(path), sha256,
                 datetime.now().isoformat(timespec="seconds"),
                 min(dates).isoformat() if dates else None,
                 max(dates).isoformat() if dates else None,
                 len(rows)),
            )
            batch_id = cur.lastrowid
            self.conn.executemany(
                """INSERT INTO entry
                   (batch_id, txn_date, account_code, amount, source,
                    office_id, sol_id, description)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(batch_id, e.txn_date.isoformat(), e.account_code, str(e.amount),
                  e.source.value, e.office_id, e.sol_id, e.description) for e in rows],
            )
        return batch_id

    def reverse_batch(self, batch_id: int) -> int:
        """Undo one upload. Returns rows removed.

        The legacy delete routines removed rows by scanning a date range,
        which also deleted correct data that happened to share those dates.
        Reversing a batch removes exactly what that file contributed.
        """
        with self.conn:
            n = self.conn.execute(
                "DELETE FROM entry WHERE batch_id=?", (batch_id,)).rowcount
            self.conn.execute(
                "UPDATE batch SET reversed_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), batch_id))
        return n

    def batches(self, source: Optional[Source] = None, include_reversed=False):
        sql = "SELECT * FROM batch WHERE 1=1"
        args = []
        if source:
            sql += " AND source=?"
            args.append(source.value)
        if not include_reversed:
            sql += " AND reversed_at IS NULL"
        return self.conn.execute(sql + " ORDER BY id DESC", args).fetchall()

    # ---------------------------------------------------------------- queries

    def totals_by_code(self, source: Source, start: date, end: date) -> dict:
        """{account_code: Decimal} summed over the period."""
        rows = self.conn.execute(
            """SELECT account_code, amount FROM entry
               WHERE source=? AND txn_date BETWEEN ? AND ?""",
            (source.value, start.isoformat(), end.isoformat()),
        ).fetchall()
        out = {}
        for r in rows:
            out[r["account_code"]] = out.get(r["account_code"], Decimal(0)) + Decimal(r["amount"])
        return out

    def totals_by_office(self, source: Source, account_code: str,
                         start: date, end: date) -> dict:
        rows = self.conn.execute(
            """SELECT office_id, sol_id, amount FROM entry
               WHERE source=? AND account_code=? AND txn_date BETWEEN ? AND ?""",
            (source.value, account_code, start.isoformat(), end.isoformat()),
        ).fetchall()
        out = {}
        for r in rows:
            key = r["office_id"] or r["sol_id"]
            out[key] = out.get(key, Decimal(0)) + Decimal(r["amount"])
        return out

    def totals_by_date(self, source: Source, account_code: str,
                       start: date, end: date) -> dict:
        rows = self.conn.execute(
            """SELECT txn_date, amount FROM entry
               WHERE source=? AND account_code=? AND txn_date BETWEEN ? AND ?""",
            (source.value, account_code, start.isoformat(), end.isoformat()),
        ).fetchall()
        out = {}
        for r in rows:
            d = date.fromisoformat(r["txn_date"])
            out[d] = out.get(d, Decimal(0)) + Decimal(r["amount"])
        return out

    def loaded_dates(self, source: Source) -> set:
        """Dates that actually carry at least one entry."""
        return {date.fromisoformat(r[0]) for r in self.conn.execute(
            "SELECT DISTINCT txn_date FROM entry WHERE source=?", (source.value,))}

    def covered_days(self, source: Source) -> set:
        """Every day the loaded reports claim to span, whether or not that day
        carried transactions.

        A post office is shut on Sundays and gazetted holidays, so those days
        have no rows. Treating "no rows" as "no report uploaded" raised a false
        alarm four to six times a month and taught users to ignore the one
        warning that matters (QA-06). A batch's span is the authority on what
        was uploaded; the entries only say what happened inside it.
        """
        days = set()
        for row in self.conn.execute(
                """SELECT period_start, period_end FROM batch
                   WHERE source=? AND reversed_at IS NULL
                     AND period_start IS NOT NULL""", (source.value,)):
            start = date.fromisoformat(row["period_start"])
            end = date.fromisoformat(row["period_end"])
            day = start
            while day <= end:
                days.add(day)
                day += timedelta(days=1)
        return days

    # ---------------------------------------------------------------- offices

    def replace_offices(self, offices: Iterable) -> int:
        offices = list(offices)
        with self.conn:
            self.conn.execute("DELETE FROM office")
            self.conn.executemany(
                "INSERT INTO office (office_id, name, sol_id, sol_group) VALUES (?,?,?,?)",
                [(o.office_id, o.name, o.sol_id, o.sol_group) for o in offices])
        return len(offices)

    def offices(self) -> list:
        from .model import Office
        return [Office(name=r["name"], office_id=r["office_id"],
                       sol_id=r["sol_id"], sol_group=r["sol_group"])
                for r in self.conn.execute("SELECT * FROM office ORDER BY office_id")]

    # ----------------------------------------------------------- discrepancy

    def add_discrepancy(self, period, row, remarks="") -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO discrepancy
                   (period_start, period_end, account_code, description,
                    finacle, cashbook, difference, remarks, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (period.start.isoformat(), period.end.isoformat(),
                 row.account_code, row.description, str(row.finacle),
                 str(row.cashbook), str(row.difference), remarks,
                 datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def discrepancies(self) -> list:
        return self.conn.execute(
            "SELECT * FROM discrepancy ORDER BY period_start, account_code").fetchall()

    # --------------------------------------------- Table-3 register (SB 09/2026)

    def _register_entry(self, row) -> "object":
        from .annexure import RegisterEntry

        return RegisterEntry(
            id=row["id"],
            serial=row["serial"],
            entry_date=date.fromisoformat(row["entry_date"]),
            account_code=row["account_code"],
            description=row["description"],
            office_name=row["office_name"],
            cbs_receipt=Decimal(row["cbs_receipt"]),
            cbs_payment=Decimal(row["cbs_payment"]),
            cashbook_receipt=Decimal(row["cashbook_receipt"]),
            cashbook_payment=Decimal(row["cashbook_payment"]),
            rectified_date=(date.fromisoformat(row["rectified_date"])
                            if row["rectified_date"] else None),
            misc_transaction=row["misc_transaction"],
            transfer_entry=row["transfer_entry"],
        )

    def add_register_entries(self, entries) -> list:
        """Record entries in the Table-3 register, assigning serials.

        Serial numbers restart from 1 each financial year (the order's own
        footnote), so the next serial is read per entry's FY inside the same
        transaction that inserts it - two tabs saving at once cannot mint the
        same number.
        """
        ids = []
        with self.conn:
            for entry in entries:
                fy = entry.financial_year
                serial = self.conn.execute(
                    "SELECT COALESCE(MAX(serial), 0) + 1 FROM register WHERE fy=?",
                    (fy,)).fetchone()[0]
                cur = self.conn.execute(
                    """INSERT INTO register
                       (fy, serial, entry_date, account_code, description,
                        office_name, cbs_receipt, cbs_payment,
                        cashbook_receipt, cashbook_payment, rectified_date,
                        misc_transaction, transfer_entry, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fy, serial, entry.entry_date.isoformat(),
                     entry.account_code, entry.description, entry.office_name,
                     str(entry.cbs_receipt), str(entry.cbs_payment),
                     str(entry.cashbook_receipt), str(entry.cashbook_payment),
                     entry.rectified_date.isoformat() if entry.rectified_date else None,
                     entry.misc_transaction, entry.transfer_entry,
                     datetime.now().isoformat(timespec="seconds")))
                ids.append(cur.lastrowid)
        return ids

    def register_entries(self, fy: Optional[str] = None,
                         only_open: bool = False) -> list:
        sql = "SELECT * FROM register WHERE 1=1"
        args = []
        if fy:
            sql += " AND fy=?"
            args.append(fy)
        if only_open:
            sql += " AND rectified_date IS NULL"
        rows = self.conn.execute(sql + " ORDER BY fy, serial", args).fetchall()
        return [self._register_entry(r) for r in rows]

    def register_years(self) -> list:
        return [r["fy"] for r in self.conn.execute(
            "SELECT DISTINCT fy FROM register ORDER BY fy")]

    def open_register_codes(self, entry_date: date) -> set:
        """Codes that already have an unsettled entry for this date - the
        save-from-reconciliation dedupe guard."""
        rows = self.conn.execute(
            """SELECT account_code FROM register
               WHERE entry_date=? AND rectified_date IS NULL""",
            (entry_date.isoformat(),)).fetchall()
        return {r["account_code"] for r in rows}

    def settle_register_entry(self, entry_id: int, rectified_date: date,
                              misc_transaction: str = "",
                              transfer_entry: str = "") -> "object":
        """Mark one entry rectified. The order treats a discrepancy as settled
        only after the rectification is verified, which the date records."""
        row = self.conn.execute(
            "SELECT * FROM register WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise ValueError(f"There is no register entry numbered {entry_id}.")
        if row["rectified_date"]:
            raise ValueError(
                f"Entry {row['fy']} Sl.{row['serial']} was already settled "
                f"on {row['rectified_date']}.")
        if rectified_date < date.fromisoformat(row["entry_date"]):
            raise ValueError("The rectification date is before the entry's own date.")
        with self.conn:
            self.conn.execute(
                """UPDATE register SET rectified_date=?, misc_transaction=?,
                   transfer_entry=? WHERE id=?""",
                (rectified_date.isoformat(), misc_transaction,
                 transfer_entry, entry_id))
        return self._register_entry(self.conn.execute(
            "SELECT * FROM register WHERE id=?", (entry_id,)).fetchone())

    # -------------------------------------------------------- transfer entry

    def add_transfer_entry(self, month: str, from_code: str, to_code: str,
                           amount: Decimal, remarks="") -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO transfer_entry
                   (month, from_code, to_code, amount, remarks, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (month, from_code, to_code, str(amount), remarks,
                 datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def transfer_entries(self, month: Optional[str] = None) -> list:
        if month:
            return self.conn.execute(
                "SELECT * FROM transfer_entry WHERE month=? ORDER BY id", (month,)).fetchall()
        return self.conn.execute("SELECT * FROM transfer_entry ORDER BY id").fetchall()

    # -------------------------------------------------------------- settings

    def set(self, key: str, value: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO setting(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
