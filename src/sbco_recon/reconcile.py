"""The reconciliation engine.

Pure functions over data pulled from the store. No Excel, no UI, no global
state - which is what makes every rule here directly testable, unlike the
legacy version where the logic lived inside 235-line button handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from . import refdata
from .fiscal import Period
from .model import (Office, OfficeReconRow, ReconResult, ReconRow, Source,
                    ZERO)
from .store import Store


# --------------------------------------------------------------- coverage

@dataclass
class Coverage:
    """Which days in the period actually have data on each side.

    The legacy tool reconciled whatever happened to be loaded and reported the
    result as authoritative. If a cashbook file was never uploaded for the
    18th, that day's transactions showed up as a Finacle-only difference and
    looked exactly like a genuine unaccounted entry. This surfaces the gap
    before any figures are presented.
    """

    period: Period
    finacle_days: set
    cashbook_days: set

    def __post_init__(self):
        # computed once: the properties were recalculating the whole day set
        # on every access, twice per request (QA-13)
        wanted = set(self.period.days())
        self._missing_finacle = sorted(wanted - self.finacle_days)
        self._missing_cashbook = sorted(wanted - self.cashbook_days)

    @property
    def missing_finacle(self) -> list:
        return self._missing_finacle

    @property
    def missing_cashbook(self) -> list:
        return self._missing_cashbook

    @property
    def complete(self) -> bool:
        return not self.missing_finacle and not self.missing_cashbook

    def warnings(self) -> list:
        out = []
        for label, missing in (("Finacle/CBS", self.missing_finacle),
                               ("Cashbook", self.missing_cashbook)):
            if missing:
                shown = ", ".join(d.strftime("%d-%m-%Y") for d in missing[:6])
                more = f" and {len(missing) - 6} more" if len(missing) > 6 else ""
                out.append(f"No {label} report covers {len(missing)} day(s) in this "
                           f"period: {shown}{more}. Differences for these dates are "
                           f"not reliable until the missing report is uploaded.")
        return out


def coverage(store: Store, period: Period,
             finacle_source: Source = Source.FINACLE_GL) -> Coverage:
    """Which days of the period a report has been uploaded for.

    Measured against what the loaded batches span, not against which days
    happen to carry transactions - see Store.covered_days (QA-06).
    """
    in_period = set(period.days())
    return Coverage(
        period=period,
        finacle_days=store.covered_days(finacle_source) & in_period,
        cashbook_days=store.covered_days(Source.CASHBOOK) & in_period,
    )


# -------------------------------------------------- account-code reconciliation

def reconcile_by_code(store: Store, period: Period, *,
                      finacle_source: Source = Source.FINACLE_GL,
                      include_zero_rows: bool = False,
                      check_coverage: bool = True) -> ReconResult:
    """Compare Finacle against the cashbook, account code by account code.

    This is the dashboard calculation. The legacy version did it with 1,284
    volatile OFFSET/SUMIFS formulas that recalculated on every keystroke; here
    it is two indexed queries and a dictionary merge.
    """
    finacle = store.totals_by_code(finacle_source, period.start, period.end)
    cashbook = store.totals_by_code(Source.CASHBOOK, period.start, period.end)

    result = ReconResult(period=period)
    if check_coverage:
        result.warnings.extend(coverage(store, period, finacle_source).warnings())

    # Present codes in the order the dashboard used, then any extras found in
    # the data. An unexpected code is reported, never dropped.
    ordered = [entry["code"] for entry in refdata.dashboard_codes()]
    known = set(ordered)
    extras = sorted((set(finacle) | set(cashbook)) - known)

    for code in ordered + extras:
        row = ReconRow(
            account_code=code,
            description=refdata.describe(code) or "(unknown account code)",
            finacle=finacle.get(code, ZERO),
            cashbook=cashbook.get(code, ZERO),
        )
        if include_zero_rows or row.has_activity:
            result.rows.append(row)

    for code in extras:
        if not refdata.is_known(code):
            result.warnings.append(
                f"Account code {code} appears in the uploaded data but is not in "
                f"the reference master. Verify it before including it in a return.")
    return result


# --------------------------------------------------- office-wise reconciliation

def office_key(name: str) -> str:
    """Fold an office name for matching: the portal writes 'Barkur S.O', the
    office master 'Barkur SO'."""
    return " ".join("".join(ch for ch in name.lower() if ch.isalnum() or ch.isspace()).split())


def reconcile_by_office(store: Store, account_code: str, period: Period, *,
                        finacle_source: Optional[Source] = None,
                        offices: Optional[list] = None) -> ReconResult:
    """Compare Finacle against APT Accounting Details, office by office.

    Finacle identifies an office by SOL ID; APT identifies it by office ID
    (or, when the export omits the ID, by name). The office master is what
    joins them, and Branch Offices roll up to their parent SO through
    sol_group.

    Two Finacle reports can supply the per-office figures: the GL IT2.0
    Transaction Report (the one the SOP has SBCO pull for a discrepancy date)
    and a Set-ID GL-wise report. When finacle_source is not given, the
    transaction report is used if it has data for this code and period, else
    the GL-wise data.
    """
    offices = offices if offices is not None else store.offices()
    if not offices:
        result = ReconResult(period=period)
        result.warnings.append(
            "No office master loaded. Import your office settings file first "
            "(Office Name | Office ID | SOL ID/BO Code | SOL ID Group).")
        return result

    if finacle_source is None:
        finacle_raw = store.totals_by_office(Source.FINACLE_TXN, account_code,
                                             period.start, period.end)
        finacle_source = Source.FINACLE_TXN if finacle_raw else Source.FINACLE_GL
    if finacle_source is not Source.FINACLE_TXN or not finacle_raw:
        finacle_raw = store.totals_by_office(finacle_source, account_code,
                                             period.start, period.end)
    apt_raw = store.totals_by_office(Source.APT_DETAILS, account_code,
                                     period.start, period.end)

    by_sol = {o.sol_id: o for o in offices}
    by_office_id = {o.office_id: o for o in offices}
    by_name = {office_key(o.name): o for o in offices}

    finacle_totals, apt_totals, unmatched = {}, {}, []

    # QA-25: match strictly per source. Falling back across namespaces meant a
    # BO code that happened to equal another office's ID silently moved money
    # to the wrong office.
    for key, amount in finacle_raw.items():
        office = by_sol.get(key)
        if office is None:
            unmatched.append(("Finacle", key, amount))
            continue
        finacle_totals[office.office_id] = finacle_totals.get(office.office_id, ZERO) + amount

    for key, amount in apt_raw.items():
        if key.startswith("name:"):
            office = by_name.get(office_key(key[5:]))
            key = key[5:]
        else:
            office = by_office_id.get(key)
        if office is None:
            unmatched.append(("APT", key, amount))
            continue
        apt_totals[office.office_id] = apt_totals.get(office.office_id, ZERO) + amount

    result = ReconResult(period=period)
    for office in offices:
        result.rows.append(OfficeReconRow(
            office=office,
            finacle=finacle_totals.get(office.office_id, ZERO),
            apt=apt_totals.get(office.office_id, ZERO),
        ))

    for system, key, amount in unmatched:
        result.warnings.append(
            f"{system} data for SOL/office '{key}' ({amount:,}) does not match any "
            f"office in the master and is excluded from the office-wise totals.")
    return result


def office_attribution(result: ReconResult) -> str:
    """The register's 'office where the discrepancy is found', in the form the
    legacy remarks used: 'Manipal HO (94,000), Barkur SO (40,000)'."""
    def money(value: Decimal) -> str:
        return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"

    parts = [f"{r.office.name} ({money(r.difference)})"
             for r in result.rows if r.difference != ZERO]
    return ", ".join(parts)


def rollup_branch_offices(rows) -> list:
    """Aggregate BO figures into their parent SO, for SO-level reporting."""
    by_sol_group = {}
    for row in rows:
        key = row.office.sol_group
        if key not in by_sol_group:
            parent = row.office if not row.office.is_branch_office else None
            by_sol_group[key] = OfficeReconRow(
                office=parent or Office(name=f"SOL {key}", office_id=key,
                                        sol_id=key, sol_group=key))
        target = by_sol_group[key]
        target.finacle += row.finacle
        target.apt += row.apt
    return list(by_sol_group.values())


# ------------------------------------------------------ datewise reconciliation

@dataclass
class DateRow:
    day: date
    finacle: Decimal = ZERO
    cashbook: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.finacle - self.cashbook

    @property
    def matched(self) -> bool:
        return self.difference == ZERO


def reconcile_by_date(store: Store, account_code: str, period: Period, *,
                      finacle_source: Source = Source.FINACLE_GL,
                      only_differences: bool = False) -> list:
    """Day-by-day drill-down for one account code - pinpoints when a break began."""
    finacle = store.totals_by_date(finacle_source, account_code, period.start, period.end)
    cashbook = store.totals_by_date(Source.CASHBOOK, account_code, period.start, period.end)

    rows = [DateRow(day, finacle.get(day, ZERO), cashbook.get(day, ZERO))
            for day in period.days()]
    if only_differences:
        rows = [r for r in rows if not r.matched]
    return rows


# ------------------------------------------------- clearing-account mismatches

@dataclass
class ClearingRow:
    category: str          # CBS | PLI/RPLI | IPPB | Other
    side: str              # Receipts | Payments
    mismatch_code: str
    cleared_code: str
    mismatch: Decimal = ZERO
    cleared: Decimal = ZERO

    @property
    def outstanding(self) -> Decimal:
        """What was flagged as a mismatch but never cleared."""
        return self.mismatch - self.cleared

    @property
    def matched(self) -> bool:
        return self.outstanding == ZERO


def reconcile_clearing(store: Store, period: Period, *,
                       source: Source = Source.CASHBOOK) -> list:
    """Pair each mismatch account against its cleared counterpart.

    The eight pairs are recovered from the legacy TEMP.CLRNG.AC sheet.
    """
    totals = store.totals_by_code(source, period.start, period.end)
    return [
        ClearingRow(
            category=pair["category"],
            side=pair["side"],
            mismatch_code=pair["mismatch_code"],
            cleared_code=pair["cleared_code"],
            mismatch=totals.get(pair["mismatch_code"], ZERO),
            cleared=totals.get(pair["cleared_code"], ZERO),
        )
        for pair in refdata.clearing_pairs()
    ]


# ------------------------------------------------------------------- helpers

def apply_transfer_entries(result: ReconResult, store: Store, month: str) -> ReconResult:
    """Adjust a reconciliation by approved transfer entries.

    A TE moves an amount from one account code to another, so the from-code is
    credited and the to-code debited before the difference is reported.

    This must be called on every path that produces a return. It was written,
    tested, and then wired into neither the CLI nor the interface, so the
    Annexure showed uncorrected figures while the screen promised corrected
    ones (QA-04).
    """
    by_code = {row.account_code: row for row in result.rows}
    for te in store.transfer_entries(month):
        amount = Decimal(te["amount"])
        for code, delta in ((te["from_code"], -amount), (te["to_code"], amount)):
            row = by_code.get(code)
            if row is None:
                row = ReconRow(account_code=code,
                               description=refdata.describe(code) or "(via transfer entry)")
                result.rows.append(row)
                by_code[code] = row
            row.cashbook += delta
    return result
