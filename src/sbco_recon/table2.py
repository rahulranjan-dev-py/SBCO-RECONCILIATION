"""Annexure-IV Table-2: the detailed monthly reconciliation report to the PAO.

Layout and arithmetic recovered from CASHBOOK TOOL for SBCO 1.09.8, whose
Table-2 sheet is driven by these formulas:

    D  opening receipts    VLOOKUP(code, TABLE2_DATA!A:D, 3)   previous Table-2
    E  opening payments    VLOOKUP(code, TABLE2_DATA!A:D, 4)
    F  current receipts    VLOOKUP(code, TABLE2_DATA!G:J, 3)   this month's Table-1
    G  current payments    VLOOKUP(code, TABLE2_DATA!G:J, 4)
    H  rectified receipts  IF(side = "Payment Side", 0, TE)
    I  rectified payments  IF(side = "Receipt Side", 0, TE)
    J  closing receipts    D + F - H
    K  closing payments    E + G - I
    M  side                VLOOKUP(code, ac_codes!A:D, 4)

So every figure is split into receipts and payments, and which side a figure
lands on is decided by the account code itself, from the ac_codes master -
not by the sign of the difference. A transfer entry is applied whole to its
code's own side.

One difference from the Excel original. Its comparison against "Payment Side"
is case-insensitive because Excel's `=` is; Python's is not, and the recovered
master contains one code classified as "payment Side" with a small p. Matching
literally would have silently filed that code on the wrong side of a statutory
return, so the side is normalised before comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from . import refdata
from .model import ZERO

MONTH_FMT = "%b-%Y"
RECEIPT, PAYMENT = "receipt", "payment"


def month_label(d: date) -> str:
    return d.strftime(MONTH_FMT)


def parse_month(label: str) -> Optional[date]:
    from .normalize import parse_date
    return parse_date(label, allow_month_only=True)


def months_between(earlier: str, later: str) -> int:
    a, b = parse_month(earlier), parse_month(later)
    if a is None or b is None:
        return 0
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


def side_of(account_code: str) -> str:
    """Which column a figure for this code belongs in.

    Falls back to reading the description, because a code missing from the
    master must still be placed somewhere and the naming is consistent
    ("...-Receipts" / "...-Payments").
    """
    entry = refdata.account_codes().get(account_code, {})
    raw = (entry.get("side") or "").strip().lower()
    if raw.startswith("receipt"):
        return RECEIPT
    if raw.startswith("payment"):
        return PAYMENT
    description = (entry.get("description") or refdata.describe(account_code) or "")
    return PAYMENT if "payment" in description.lower() else RECEIPT


@dataclass
class Table2Row:
    """One account code's line on the return."""

    account_code: str
    description: str = ""
    opening_receipt: Decimal = ZERO
    opening_payment: Decimal = ZERO
    current_receipt: Decimal = ZERO
    current_payment: Decimal = ZERO
    rectified_receipt: Decimal = ZERO
    rectified_payment: Decimal = ZERO
    first_month: str = ""          # ours, not on the official sheet

    def __post_init__(self):
        if not self.description:
            self.description = refdata.describe(self.account_code)

    @property
    def side(self) -> str:
        return side_of(self.account_code)

    @property
    def closing_receipt(self) -> Decimal:
        return self.opening_receipt + self.current_receipt - self.rectified_receipt

    @property
    def closing_payment(self) -> Decimal:
        return self.opening_payment + self.current_payment - self.rectified_payment

    @property
    def is_settled(self) -> bool:
        return self.closing_receipt == ZERO and self.closing_payment == ZERO

    @property
    def has_activity(self) -> bool:
        return any((self.opening_receipt, self.opening_payment,
                    self.current_receipt, self.current_payment,
                    self.rectified_receipt, self.rectified_payment))

    def age(self, as_of: str) -> int:
        return months_between(self.first_month, as_of) if self.first_month else 0


@dataclass
class Table2Result:
    month: str
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def _sum(self, attr) -> Decimal:
        return sum((getattr(r, attr) for r in self.rows), ZERO)

    @property
    def opening_total(self) -> Decimal:
        return self._sum("opening_receipt") + self._sum("opening_payment")

    @property
    def current_total(self) -> Decimal:
        return self._sum("current_receipt") + self._sum("current_payment")

    @property
    def rectified_total(self) -> Decimal:
        return self._sum("rectified_receipt") + self._sum("rectified_payment")

    @property
    def closing_total(self) -> Decimal:
        return self._sum("closing_receipt") + self._sum("closing_payment")

    @property
    def pending(self) -> list:
        return [r for r in self.rows if not r.is_settled]

    @property
    def balances(self) -> bool:
        """opening + current - rectified must equal closing. Always."""
        return (self.opening_total + self.current_total
                - self.rectified_total) == self.closing_total

    def ageing(self) -> dict:
        """How long each still-pending item has been open.

        Not part of the prescribed return - the official sheet has no column
        for it and an imported Table-2 carries no first-seen date. It is
        available because we keep the history in a database rather than in the
        sheet itself, and a follow-up register is more use when it can tell
        April's break from this month's.
        """
        buckets = {"0-1 month": [], "2-3 months": [],
                   "4-6 months": [], "over 6 months": []}
        for row in self.pending:
            age = row.age(self.month)
            key = ("0-1 month" if age <= 1 else "2-3 months" if age <= 3
                   else "4-6 months" if age <= 6 else "over 6 months")
            buckets[key].append(row)
        return buckets

    def summary(self) -> str:
        return (f"{self.month}: opening {self.opening_total:,}, "
                f"current {self.current_total:,}, "
                f"rectified {self.rectified_total:,}, "
                f"closing {self.closing_total:,} "
                f"({len(self.pending)} codes pending)")


def _amount(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def build_table2(month: str,
                 table1_rows: Iterable = (),
                 previous_table2: Iterable = (),
                 transfer_entries: Iterable = ()) -> Table2Result:
    """Roll the register forward one month.

    month             e.g. "Jul-2026"
    table1_rows       this month's Table-1 (ReconRow-like: .account_code,
                      .description, .difference)
    previous_table2   last month's Table-2 rows, or the first-month seed
    transfer_entries  approved TEs: (account_code, signed_amount) pairs,
                      dicts, or sqlite3.Rows
    """
    result = Table2Result(month=month)
    rows = {}

    def row_for(code, description="") -> Table2Row:
        if code not in rows:
            rows[code] = Table2Row(account_code=code, description=description,
                                   first_month=month)
        elif description and not rows[code].description:
            rows[code].description = description
        return rows[code]

    # ---- brought forward from last month's closing
    for prior in previous_table2:
        code = getattr(prior, "account_code", None) or prior["account_code"]
        row = row_for(code, getattr(prior, "description", "") or "")
        row.opening_receipt = _amount(getattr(prior, "closing_receipt", None)
                                      if hasattr(prior, "closing_receipt")
                                      else prior["closing_receipt"])
        row.opening_payment = _amount(getattr(prior, "closing_payment", None)
                                      if hasattr(prior, "closing_payment")
                                      else prior["closing_payment"])
        first = getattr(prior, "first_month", "") or ""
        row.first_month = first or row.first_month

    # ---- this month's Table-1 differences
    for source in table1_rows:
        difference = getattr(source, "difference", None)
        if difference is None or difference == ZERO:
            continue
        code = source.account_code
        row = row_for(code, getattr(source, "description", "") or "")
        if side_of(code) == RECEIPT:
            row.current_receipt += difference
        else:
            row.current_payment += difference

    # ---- rectified by approved transfer entries
    from .annexure import expand_transfer_entries

    for code, amount in expand_transfer_entries(transfer_entries):
        if amount == ZERO:
            continue
        if code not in rows:
            result.warnings.append(
                f"A transfer entry of {amount:,} was recorded against {code}, "
                f"but that code has nothing outstanding and no difference this "
                f"month. It still appears on the return - check it is correct.")
        row = row_for(code)
        if side_of(code) == RECEIPT:
            row.rectified_receipt += amount
        else:
            row.rectified_payment += amount

    result.rows = [r for r in rows.values() if r.has_activity]
    result.rows.sort(key=lambda r: r.account_code)

    if not result.balances:
        result.warnings.append(
            f"Internal check failed: opening {result.opening_total:,} plus "
            f"current {result.current_total:,} less rectified "
            f"{result.rectified_total:,} does not equal closing "
            f"{result.closing_total:,}. Do not submit this return; report it.")
    return result





# ----------------------------------------------------- the month-to-month chain

class _Table1Difference:
    """The shape build_table2 reads from a Table-1 row: one signed difference."""

    __slots__ = ("account_code", "description", "difference")

    def __init__(self, row):
        self.account_code = row.account_code
        self.description = row.description
        # a code sits on one side, so exactly one of these is non-zero
        self.difference = row.difference_receipt + row.difference_payment


class _Opening:
    """A Table-2 opening seed row, in the shape of a prior month's closing."""

    __slots__ = ("account_code", "description", "closing_receipt",
                 "closing_payment", "first_month")

    def __init__(self, row, month):
        self.account_code = row["account_code"]
        self.description = row["description"]
        self.closing_receipt = _amount(row["receipt_diff"])
        self.closing_payment = _amount(row["payment_diff"])
        self.first_month = month


def table2_for_month(store, month: str) -> Table2Result:
    """Table-2 for `month`, carried forward from everything the store holds.

    The legacy tool rebuilt Table-2 by hand each month: upload last month's
    Table-2 (or a first-time seed), upload this month's Table-1, add the TEs
    that rectified older differences. Here the same arithmetic walks every
    month with data, oldest first, so this month's opening balances are last
    month's closing balances without anyone re-uploading anything. A seed
    recorded for a month (Store.replace_table2_opening) replaces the computed
    carry-forward for that month - the "preparing for the first time" case.
    """
    from .annexure import build_table1
    from .fiscal import Period
    from .reconcile import reconcile_by_code

    target = parse_month(month)
    if target is None:
        raise ValueError(f"'{month}' is not a month - use e.g. Jul-2026")
    target_label = month_label(target)

    months = [m for m in store.months_with_data()
              if parse_month(m) and parse_month(m) <= target]
    if target_label not in months:
        months.append(target_label)
    months.sort(key=parse_month)

    previous = []
    result = None
    for label in months:
        seed = store.table2_opening(label)
        if seed:
            previous = [_Opening(r, label) for r in seed]

        period = Period.for_month(parse_month(label))
        recon = reconcile_by_code(store, period, check_coverage=False)
        table1 = build_table1(recon, label, store.transfer_entries(label, scope="current"))
        current = [_Table1Difference(r) for r in table1.rows]

        result = build_table2(label, current, previous_table2=previous,
                              transfer_entries=store.transfer_entries(label, scope="prior"))
        previous = result.rows
    return result
