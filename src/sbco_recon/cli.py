"""Command-line interface.

Every command is a thin wrapper over the engine, so anything the CLI can do a
future GUI can do by calling the same functions.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from . import __version__, refdata
from .annexure import build_table1, entries_from_reconciliation
from .fiscal import Period, fy_label, quarter_label
from .ingest.batch import load_files, summarise
from .model import Source
from .normalize import parse_date
from .reconcile import (coverage, office_attribution, reconcile_by_code,
                        reconcile_by_date, reconcile_by_office, reconcile_clearing)
from .reports import (write_annexure_iv_table1, write_annexure_iv_table2,
                      write_discrepancy_register, write_discrepancy_report,
                      write_recon_sheet)
from .table2 import table2_for_month
from .store import Store, adopt_legacy_database, default_db_path

DB_DEFAULT = str(default_db_path())


def _date(text) -> date:
    parsed = parse_date(text, allow_month_only=True)
    if parsed is None:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a valid date - use DD-MM-YYYY")
    return parsed


def _period(args) -> Period:
    if args.month:
        return Period.for_month(args.month)
    if not (args.start and args.end):
        raise SystemExit("error: give either --month, or both --start and --end")
    return Period(args.start, args.end)


def _money(value) -> str:
    return f"{value:>18,.2f}"


# ---------------------------------------------------------------- commands

def cmd_load(args):
    with Store(args.db) as store:
        outcomes = load_files(store, args.files, allow_duplicate=args.allow_duplicate)
        counts = summarise(outcomes)

        width = max((len(Path(o.path).name) for o in outcomes), default=10)
        for outcome in outcomes:
            marker = {"loaded": "OK", "duplicate": "DUP",
                      "rejected": "REJ", "failed": "ERR"}[outcome.status]
            print(f"  [{marker:>3}] {Path(outcome.path).name:<{width}}  "
                  f"{outcome.reason}"
                  + (f" - {outcome.detail}" if outcome.detail else "")
                  + (f"  ({outcome.rows} rows)" if outcome.rows else ""))

        print(f"\n  submitted {counts['submitted']} | loaded {counts['loaded']} | "
              f"duplicate {counts['duplicate']} | rejected {counts['rejected']} | "
              f"failed {counts['failed']} | {counts['rows']} rows")
        # The invariant the legacy tool could not hold.
        print(f"  every submitted file accounted for: "
              f"{counts['loaded'] + counts['duplicate'] + counts['rejected'] + counts['failed']}"
              f"/{counts['submitted']}")
    return 0 if counts["failed"] == 0 else 1


def cmd_reconcile(args):
    period = _period(args)
    with Store(args.db) as store:
        result = reconcile_by_code(store, period,
                                   include_zero_rows=args.show_all)
        print(f"\n  Reconciliation {period}   ({quarter_label(period.start)})\n")
        for warning in result.warnings:
            print(f"  ! {warning}\n")

        rows = result.rows if args.show_all else result.differences
        if not rows:
            print("  No differences. Finacle and the cashbook agree for this period.")
        else:
            print(f"  {'A/C CODE':<12}{'DESCRIPTION':<44}"
                  f"{'FINACLE':>18}{'CASHBOOK':>18}{'DIFFERENCE':>18}")
            print("  " + "-" * 108)
            for row in rows:
                print(f"  {row.account_code:<12}{row.description[:42]:<44}"
                      f"{_money(row.finacle)}{_money(row.cashbook)}{_money(row.difference)}")
            print("  " + "-" * 108)
            print(f"  {'':<12}{'TOTAL':<44}{_money(result.total_finacle)}"
                  f"{_money(result.total_cashbook)}{_money(result.total_difference)}")
        print(f"\n  {result.summary()}")

        if args.export:
            path = write_recon_sheet(args.export, result,
                                     include_matched=args.show_all)
            print(f"  written: {path}")
    return 0


def cmd_datewise(args):
    period = _period(args)
    with Store(args.db) as store:
        rows = reconcile_by_date(store, args.code, period,
                                 only_differences=not args.show_all)
        print(f"\n  {args.code} - {refdata.describe(args.code)}")
        print(f"  {period}\n")
        print(f"  {'DATE':<14}{'FINACLE':>18}{'CASHBOOK':>18}{'DIFFERENCE':>18}")
        print("  " + "-" * 68)
        for row in rows:
            print(f"  {row.day:%d-%m-%Y}    {_money(row.finacle)}"
                  f"{_money(row.cashbook)}{_money(row.difference)}")
        if not rows:
            print("  No differences on any day in this period.")
    return 0


def cmd_officewise(args):
    period = _period(args)
    with Store(args.db) as store:
        result = reconcile_by_office(store, args.code, period)
        for warning in result.warnings:
            print(f"  ! {warning}")
        if not result.rows:
            return 1
        print(f"\n  {args.code} - {refdata.describe(args.code)}")
        print(f"  {period}\n")
        print(f"  {'OFFICE':<34}{'FINACLE':>18}{'APT':>18}{'DIFFERENCE':>18}")
        print("  " + "-" * 88)
        for row in result.rows:
            print(f"  {row.office.name[:32]:<34}{_money(row.finacle)}"
                  f"{_money(row.apt)}{_money(row.difference)}")
    return 0


def cmd_clearing(args):
    period = _period(args)
    with Store(args.db) as store:
        rows = reconcile_clearing(store, period)
        print(f"\n  Clearing accounts {period}\n")
        print(f"  {'CATEGORY':<12}{'SIDE':<11}{'MISMATCH':>18}"
              f"{'CLEARED':>18}{'OUTSTANDING':>18}")
        print("  " + "-" * 77)
        for row in rows:
            print(f"  {row.category:<12}{row.side:<11}{_money(row.mismatch)}"
                  f"{_money(row.cleared)}{_money(row.outstanding)}")
    return 0


def cmd_annexure(args):
    month = args.month or date.today().replace(day=1)
    if args.table == 2:
        return _annexure_table2(args, month)
    period = Period.for_month(month)
    with Store(args.db) as store:
        recon = reconcile_by_code(store, period)
        month_label = f"{month:%b-%Y}"
        transfer_entries = store.transfer_entries(month_label, scope="current")
        # SB Order 09/2026: Monthly Cash Account = daily cash books + approved
        # transfer entries of the DDO, so TEs belong in that column.
        result = build_table1(recon, month_label, transfer_entries)
        for warning in result.warnings:
            print(f"  ! {warning}")

        ddo = args.ddo or store.get("ddo_code", "")
        ho = args.ho or store.get("ho_name", "")
        division = args.division or store.get("division", "")
        missing = [n for n, v in (("--ddo", ddo), ("--ho", ho),
                                  ("--division", division)) if not v]
        if missing:
            raise SystemExit(f"error: missing {', '.join(missing)} "
                             f"(or set them once with 'sbco config')")

        out = args.output or f"CBS-MRR-TABLE1-{month:%b-%y}.xlsx"
        path = write_annexure_iv_table1(
            out, result, ddo_code=ddo, ho_name=ho, division=division, month=month,
            include_matched=args.show_all)
        print(f"\n  Annexure-IV Table-1 for {month:%B %Y}")
        if transfer_entries:
            print(f"  {len(transfer_entries)} approved transfer "
                  f"entr{'y' if len(transfer_entries) == 1 else 'ies'} applied")
        totals = result.totals()
        print(f"  {len(result.differences)} account code(s) with differences: "
              f"receipts {totals['difference_receipt']:,}, "
              f"payments {totals['difference_payment']:,}")
        print(f"  written: {path}")
    return 0


def cmd_doctor(args):
    """Check the environment and say plainly what, if anything, is wrong."""
    from .webapp.doctor import main as doctor_main
    return doctor_main()


def cmd_gui(args):
    """Open the application in the browser."""
    from .webapp.server import serve
    serve(args.db, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_config(args):
    with Store(args.db) as store:
        for key, value in (("ddo_code", args.ddo), ("ho_name", args.ho),
                           ("division", args.division)):
            if value:
                store.set(key, value)
        print("  DDO code:", store.get("ddo_code", "(not set)"))
        print("  HO name :", store.get("ho_name", "(not set)"))
        print("  Division:", store.get("division", "(not set)"))
        print("  Offices :", len(store.offices()))
    return 0


def cmd_batches(args):
    with Store(args.db) as store:
        rows = store.batches(include_reversed=args.all)
        if not rows:
            print("  No files loaded yet.")
            return 0
        print(f"\n  {'ID':>4}  {'SOURCE':<16}{'FILE':<38}{'ROWS':>7}  "
              f"{'PERIOD':<26}LOADED")
        for row in rows:
            span = f"{row['period_start']} .. {row['period_end']}"
            flag = "  [reversed]" if row["reversed_at"] else ""
            print(f"  {row['id']:>4}  {row['source']:<16}{row['file_name'][:36]:<38}"
                  f"{row['row_count']:>7}  {span:<26}{row['loaded_at']}{flag}")
    return 0


def cmd_reverse(args):
    with Store(args.db) as store:
        removed = store.reverse_batch(args.batch_id)
        print(f"  Batch {args.batch_id} reversed - {removed} entries removed.")
    return 0


def cmd_discrepancy(args):
    with Store(args.db) as store:
        if args.add:
            period = _period(args)
            result = reconcile_by_code(store, period, check_coverage=False)
            added = 0
            for row in result.differences:
                store.add_discrepancy(period, row, args.remarks)
                added += 1
            print(f"  {added} discrepancy row(s) recorded.")
        rows = store.discrepancies()
        print(f"  Register holds {len(rows)} row(s).")
        if args.export:
            print(f"  written: {write_discrepancy_report(args.export, rows)}")
    return 0


def cmd_register(args):
    """The Table-3 register: record, list, settle, export."""
    with Store(args.db) as store:
        if args.record:
            period = _period(args)
            entry_date = args.date or period.end
            result = reconcile_by_code(store, period, check_coverage=False)
            candidates = entries_from_reconciliation(result, entry_date,
                                                     office_name=args.office)
            already = store.open_register_codes(entry_date)
            fresh = [e for e in candidates if e.account_code not in already]
            for entry in fresh:
                if not entry.office_name:
                    entry.office_name = office_attribution(
                        reconcile_by_office(store, entry.account_code, period))
            store.add_register_entries(fresh)
            skipped = len(candidates) - len(fresh)
            print(f"  {len(fresh)} entr{'y' if len(fresh) == 1 else 'ies'} added "
                  f"to the FY {fy_label(entry_date)} register"
                  + (f"; {skipped} already open for {entry_date:%d-%m-%Y} and skipped."
                     if skipped else "."))

        if args.settle:
            if args.date is None:
                raise SystemExit("error: --settle needs --date, the date of rectification")
            if not (args.misc or args.te):
                raise SystemExit("error: record how it was rectified - give "
                                 "--misc and/or --te")
            try:
                entry = store.settle_register_entry(
                    args.settle, args.date,
                    misc_transaction=args.misc, transfer_entry=args.te)
            except ValueError as exc:
                raise SystemExit(f"error: {exc}")
            print(f"  Settled {entry.financial_year} Sl.{entry.serial} "
                  f"({entry.account_code}) on {entry.rectified_date:%d-%m-%Y}.")

        years = store.register_years()
        fy = args.fy or (years[-1] if years else fy_label(date.today()))
        entries = store.register_entries(fy=fy, only_open=args.open)
        shown = "open entries" if args.open else "entries"
        print(f"\n  FY {fy}: {len(entries)} {shown}"
              + (f" (register also covers {', '.join(y for y in years if y != fy)})"
                 if len(years) > 1 else ""))
        if entries:
            print(f"  {'ref':>5} {'sl':>4}  {'date':<12}{'a/c code':<12}"
                  f"{'description':<36}{'difference':>14}    status")
        for e in entries:
            status = (f"settled {e.rectified_date:%d-%m-%Y}" if e.is_settled
                      else f"OPEN {e.days_outstanding}d")
            diff = e.difference_receipt if e.difference_receipt else e.difference_payment
            side = "R" if e.difference_receipt else "P"
            print(f"  #{e.id:>4} {e.serial:>4}  {e.entry_date:%d-%m-%Y}  "
                  f"{e.account_code:<12}{(e.description or '')[:34]:<36}"
                  f"{diff:>14,} {side}  {status}")
        if any(not e.is_settled for e in entries):
            print("\n  settle one with: sbco register --settle <ref> "
                  "--date DD-MM-YYYY --misc \"...\" [--te \"...\"]")

        if args.export is not None:
            target = args.export or f"Table3-Register-{fy.replace('/', '-')}.xlsx"
            all_entries = store.register_entries(fy=fy)
            if not all_entries:
                raise SystemExit(f"error: the register has no entries for {fy}")
            path = write_discrepancy_register(
                target, all_entries, financial_year=fy,
                ho_name=store.get("ho_name", ""))
            print(f"\n  written: {path}")
    return 0


def _annexure_table2(args, month) -> int:
    from .webapp.server import parse_table2_opening
    from .ingest.reader import read_rows

    month_label = f"{month:%b-%Y}"
    with Store(args.db) as store:
        if args.opening:
            rows = parse_table2_opening(read_rows(args.opening))
            if not rows:
                raise SystemExit("error: --opening file has no AC_CODE / RECEIPT_DIFF / "
                                 "PAYMENT_DIFF rows")
            n = store.replace_table2_opening(month_label, rows)
            print(f"  {n} opening balance(s) recorded for {month_label}")

        ddo = args.ddo or store.get("ddo_code", "")
        ho = args.ho or store.get("ho_name", "")
        division = args.division or store.get("division", "")
        missing = [n for n, v in (("--ddo", ddo), ("--ho", ho),
                                  ("--division", division)) if not v]
        if missing:
            raise SystemExit(f"error: missing {', '.join(missing)} "
                             f"(or set them once with 'sbco config')")

        result = table2_for_month(store, month_label)
        for warning in result.warnings:
            print(f"  ! {warning}")
        out = args.output or f"CBS-MRR-TABLE2-{month:%b-%y}.xlsx"
        path = write_annexure_iv_table2(
            out, result, ddo_code=ddo, ho_name=ho, division=division, month=month,
            include_settled=args.show_all)
        print(f"\n  Annexure-IV Table-2 for {month:%B %Y}")
        print(f"  opening {result.opening_total:,} | current {result.current_total:,} | "
              f"rectified {result.rectified_total:,} | pending {result.closing_total:,}")
        print(f"  {len(result.pending)} code(s) pending rectification")
        print(f"  written: {path}")
    return 0


def cmd_te(args):
    """Approved transfer entries: list, or add one."""
    with Store(args.db) as store:
        if args.add:
            from .normalize import parse_amount

            amount = parse_amount(args.amount)
            if amount is None or not (args.from_code and args.to_code and args.month):
                raise SystemExit("error: --add needs --month, --from, --to and --amount")
            scope = "prior" if args.prior else "current"
            store.add_transfer_entry(args.month, args.from_code, args.to_code,
                                     amount, args.remarks, scope=scope)
            print(f"  TE recorded for {args.month}: {args.from_code} -> {args.to_code} "
                  f"{amount:,} ({'rectifies an earlier month - Table-2' if args.prior else 'this month - Table-1'})")
        rows = store.transfer_entries(args.month or None)
        print(f"\n  {len(rows)} transfer entr{'y' if len(rows) == 1 else 'ies'}"
              + (f" for {args.month}" if args.month else ""))
        for r in rows:
            where = "Table-2 (earlier month)" if r["scope"] == "prior" else "Table-1 (this month)"
            print(f"  #{r['id']:>3}  {r['month']:<9} {r['from_code']} -> {r['to_code']} "
                  f"{Decimal(r['amount']):>14,}  {where}  {r['remarks']}")
    return 0


# ------------------------------------------------------------------ parser

def build_parser():
    p = argparse.ArgumentParser(
        prog="sbco",
        description="SBCO Cashbook-CBS reconciliation engine")
    p.add_argument("--version", action="version",
                   version=f"sbco-recon {__version__}")
    p.add_argument("--db", default=DB_DEFAULT,
                   help="data file (default: your user data folder)")
    sub = p.add_subparsers(dest="command", required=True)

    def add_period(sp):
        sp.add_argument("--month", type=_date, help="e.g. Jul-2026 or 01-07-2026")
        sp.add_argument("--start", type=_date, help="DD-MM-YYYY")
        sp.add_argument("--end", type=_date, help="DD-MM-YYYY")

    sp = sub.add_parser("load", help="load report files")
    sp.add_argument("files", nargs="+")
    sp.add_argument("--allow-duplicate", action="store_true",
                    help="load even if an identical file was already loaded")
    sp.set_defaults(func=cmd_load)

    sp = sub.add_parser("reconcile", help="account-code reconciliation")
    add_period(sp)
    sp.add_argument("--show-all", action="store_true", help="include matched codes")
    sp.add_argument("--export", help="write an .xlsx to this path")
    sp.set_defaults(func=cmd_reconcile)

    sp = sub.add_parser("datewise", help="day-by-day drill-down for one code")
    sp.add_argument("code")
    add_period(sp)
    sp.add_argument("--show-all", action="store_true")
    sp.set_defaults(func=cmd_datewise)

    sp = sub.add_parser("officewise", help="office-wise reconciliation for one code")
    sp.add_argument("code")
    add_period(sp)
    sp.set_defaults(func=cmd_officewise)

    sp = sub.add_parser("clearing", help="clearing-account mismatch report")
    add_period(sp)
    sp.set_defaults(func=cmd_clearing)

    sp = sub.add_parser("annexure", help="generate Annexure-IV Table-1 or Table-2")
    sp.add_argument("--month", type=_date)
    sp.add_argument("--table", type=int, choices=(1, 2), default=1,
                    help="1: monthly reconciliation; 2: detailed opening/current/"
                         "rectified/pending (default 1)")
    sp.add_argument("--opening", metavar="FILE",
                    help="Table-2 only: record the month's opening balances first "
                         "(AC_CODE | DESCRIPTION | RECEIPT_DIFF | PAYMENT_DIFF)")
    sp.add_argument("--ddo"), sp.add_argument("--ho"), sp.add_argument("--division")
    sp.add_argument("--output"), sp.add_argument("--show-all", action="store_true")
    sp.set_defaults(func=cmd_annexure)

    sp = sub.add_parser("te", help="approved transfer entries: list or add")
    sp.add_argument("--month", help="e.g. Jul-2026")
    sp.add_argument("--add", action="store_true")
    sp.add_argument("--from", dest="from_code"), sp.add_argument("--to", dest="to_code")
    sp.add_argument("--amount"), sp.add_argument("--remarks", default="")
    sp.add_argument("--prior", action="store_true",
                    help="rectifies an earlier month's pending difference (Table-2) "
                         "instead of this month's cash account (Table-1)")
    sp.set_defaults(func=cmd_te)

    sp = sub.add_parser("doctor", help="check this PC is set up correctly")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("gui", help="open the application in your browser")
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(func=cmd_gui)

    sp = sub.add_parser("config", help="show or set office identity")
    sp.add_argument("--ddo"), sp.add_argument("--ho"), sp.add_argument("--division")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("batches", help="list loaded files")
    sp.add_argument("--all", action="store_true", help="include reversed batches")
    sp.set_defaults(func=cmd_batches)

    sp = sub.add_parser("reverse", help="undo one loaded file")
    sp.add_argument("batch_id", type=int)
    sp.set_defaults(func=cmd_reverse)

    sp = sub.add_parser("discrepancy", help="period discrepancy snapshots (legacy)")
    add_period(sp)
    sp.add_argument("--add", action="store_true", help="record current differences")
    sp.add_argument("--remarks", default="")
    sp.add_argument("--export")
    sp.set_defaults(func=cmd_discrepancy)

    sp = sub.add_parser(
        "register", help="Table-3 daily discrepancy register: record, settle, export")
    add_period(sp)
    sp.add_argument("--record", action="store_true",
                    help="save the period's differences into the register")
    sp.add_argument("--date", type=_date,
                    help="entry date when recording; rectification date when settling")
    sp.add_argument("--office", default="",
                    help="post office where the discrepancy was found")
    sp.add_argument("--settle", type=int, metavar="ID",
                    help="mark one entry rectified (needs --date and --misc/--te)")
    sp.add_argument("--misc", default="", help="particulars of Misc. transaction posted")
    sp.add_argument("--te", default="", help="particulars of transfer entries posted")
    sp.add_argument("--fy", help="financial year, e.g. 2026/27 (default: latest)")
    sp.add_argument("--open", action="store_true", help="list only unsettled entries")
    sp.add_argument("--export", nargs="?", const="", metavar="FILE",
                    help="write the FY's register as Table-3 (.xlsx)")
    sp.set_defaults(func=cmd_register)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # First run after an upgrade: bring a pre-2.1 data file across. Never for
    # 'doctor' - a diagnostic that changes the thing it is diagnosing is not a
    # diagnostic, and it would silently consume the very file it should be
    # reporting on.
    if args.db == DB_DEFAULT and args.command != "doctor":
        adopt_legacy_database(args.db)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  cancelled")
        return 130


if __name__ == "__main__":
    sys.exit(main())
