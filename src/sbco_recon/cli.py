"""Command-line interface.

Every command is a thin wrapper over the engine, so anything the CLI can do a
future GUI can do by calling the same functions.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import __version__, refdata
from .fiscal import Period, quarter_label
from .ingest.batch import load_files, summarise
from .model import Source
from .normalize import parse_date
from .annexure import build_table1
from .reconcile import (coverage, reconcile_by_code, reconcile_by_date,
                        reconcile_by_office, reconcile_clearing)
from .reports import (write_annexure_iv_table1, write_discrepancy_report,
                      write_recon_sheet)
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
    period = Period.for_month(month)
    with Store(args.db) as store:
        recon = reconcile_by_code(store, period)
        month_label = f"{month:%b-%Y}"
        transfer_entries = store.transfer_entries(month_label)
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

    sp = sub.add_parser("annexure", help="generate Annexure-IV Table-1")
    sp.add_argument("--month", type=_date)
    sp.add_argument("--ddo"), sp.add_argument("--ho"), sp.add_argument("--division")
    sp.add_argument("--output"), sp.add_argument("--show-all", action="store_true")
    sp.set_defaults(func=cmd_annexure)

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

    sp = sub.add_parser("discrepancy", help="discrepancy register")
    add_period(sp)
    sp.add_argument("--add", action="store_true", help="record current differences")
    sp.add_argument("--remarks", default="")
    sp.add_argument("--export")
    sp.set_defaults(func=cmd_discrepancy)
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
