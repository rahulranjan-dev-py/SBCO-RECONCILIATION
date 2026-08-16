"""Annexure-IV tables, as prescribed by SB Order No. 09/2026 dated 24.07.2026.

The order defines three forms, and this module holds the data model for all of
them so the layouts in reports/ have a single source of truth.

Table-1  CBS Monthly Reconciliation Report to PAO by the HO
         Finacle / Monthly Cash Account / Difference, each split into
         Receipts and Payments. Due the 4th of each month.

Table-2  Detailed CBS Monthly Reconciliation Report
         Opening / Current month / Rectified / Pending for Rectification,
         each split into Receipts and Payments.

Table-3  CBS Daily Discrepancy Reconciliation Register
         Maintained daily by SBCO, preserved permanently, serial numbering
         reset at the start of each financial year.

Every money column in the order is split into Receipts and Payments, and the
order is explicit about why: para 1(ix) forbids netting a receipt discrepancy
against a payment one. A tool that carried one signed figure per account code
would quietly do the thing the order prohibits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from . import refdata
from .fiscal import fy_label
from .model import ZERO
from .table2 import PAYMENT, RECEIPT, side_of

# Footnote printed under Table-1, quoted from the order.
CASH_ACCOUNT_NOTE = ("* Monthly Cash Account = Sum of Daily Cash Books + "
                     "Approved Transfer Entries of DDO")


@dataclass
class Table1Row:
    """One account code on Table-1.

    A code belongs to one side, so its figures land in either the receipts or
    the payments column - never both, and never netted across.
    """

    account_code: str
    description: str = ""
    finacle_receipt: Decimal = ZERO
    finacle_payment: Decimal = ZERO
    cashbook_receipt: Decimal = ZERO
    cashbook_payment: Decimal = ZERO

    def __post_init__(self):
        if not self.description:
            self.description = refdata.describe(self.account_code)

    @property
    def side(self) -> str:
        return side_of(self.account_code)

    @property
    def difference_receipt(self) -> Decimal:
        return self.finacle_receipt - self.cashbook_receipt

    @property
    def difference_payment(self) -> Decimal:
        return self.finacle_payment - self.cashbook_payment

    @property
    def matched(self) -> bool:
        return self.difference_receipt == ZERO and self.difference_payment == ZERO

    @property
    def has_activity(self) -> bool:
        return any((self.finacle_receipt, self.finacle_payment,
                    self.cashbook_receipt, self.cashbook_payment))


@dataclass
class Table1Result:
    month: str
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def _sum(self, attr) -> Decimal:
        return sum((getattr(r, attr) for r in self.rows), ZERO)

    @property
    def differences(self) -> list:
        return [r for r in self.rows if not r.matched]

    @property
    def total_difference(self) -> Decimal:
        return self._sum("difference_receipt") + self._sum("difference_payment")

    def totals(self) -> dict:
        return {name: self._sum(name) for name in (
            "finacle_receipt", "finacle_payment",
            "cashbook_receipt", "cashbook_payment",
            "difference_receipt", "difference_payment")}

    def summary(self) -> str:
        t = self.totals()
        return (f"{self.month}: receipts differ by {t['difference_receipt']:,}, "
                f"payments by {t['difference_payment']:,} "
                f"({len(self.differences)} codes)")


def build_table1(recon_result, month: str, transfer_entries: Iterable = ()) -> Table1Result:
    """Turn an account-code reconciliation into Table-1.

    The order defines Monthly Cash Account as the daily cash books *plus*
    approved transfer entries of the DDO, so TEs are folded into the cash
    account column here rather than shown separately.
    """
    result = Table1Result(month=month, warnings=list(recon_result.warnings))
    rows = {}

    for source in recon_result.rows:
        code = source.account_code
        row = Table1Row(code, getattr(source, "description", "") or "")
        if side_of(code) == RECEIPT:
            row.finacle_receipt = source.finacle
            row.cashbook_receipt = source.cashbook
        else:
            row.finacle_payment = source.finacle
            row.cashbook_payment = source.cashbook
        rows[code] = row

    for code, amount in expand_transfer_entries(transfer_entries):
        if amount == ZERO:
            continue
        row = rows.get(code)
        if row is None:
            row = Table1Row(code)
            rows[code] = row
            result.warnings.append(
                f"An approved transfer entry of {amount:,} was recorded against "
                f"{code}, which had no activity this month. It appears on the "
                f"return - check it is correct.")
        if row.side == RECEIPT:
            row.cashbook_receipt += amount
        else:
            row.cashbook_payment += amount

    result.rows = sorted((r for r in rows.values() if r.has_activity),
                         key=lambda r: r.account_code)
    return result


def expand_transfer_entries(entries: Iterable) -> list:
    """Normalise every way a transfer entry can arrive into (code, amount).

    A TE recorded in the store moves an amount between two account codes, so
    it expands into two signed postings - the from-code is reduced and the
    to-code increased. Treating such a row as a single posting silently
    dropped half of every transfer entry.
    """
    out = []
    for entry in entries:
        if isinstance(entry, (tuple, list)):
            out.append((str(entry[0]), _to_decimal(entry[1])))
            continue
        keys = _keys(entry)
        amount = _to_decimal(_field(entry, "amount"))
        if "from_code" in keys or "to_code" in keys:
            from_code = _field(entry, "from_code")
            to_code = _field(entry, "to_code")
            if from_code:
                out.append((str(from_code), -amount))
            if to_code:
                out.append((str(to_code), amount))
        else:
            out.append((str(_field(entry, "account_code")), amount))
    return out


def _keys(entry) -> set:
    if hasattr(entry, "keys"):
        return set(entry.keys())
    return set()


def _field(entry, name):
    try:
        return entry[name]
    except (KeyError, IndexError, TypeError):
        return None


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


# ─────────────────────────────────────────────── Table-3, the daily register

@dataclass
class RegisterEntry:
    """One line of the CBS Daily Discrepancy Reconciliation Register.

    Column letters follow the order's own labelling, (a) through (o). The two
    difference columns are computed, not recorded: the order defines them as
    (f)-(h) and (g)-(i), so storing them would allow a register that
    contradicts its own arithmetic.
    """

    entry_date: date                    # (b)
    account_code: str                   # (c)
    description: str = ""               # (d)
    office_name: str = ""               # (e)
    cbs_receipt: Decimal = ZERO         # (f)
    cbs_payment: Decimal = ZERO         # (g)
    cashbook_receipt: Decimal = ZERO    # (h)
    cashbook_payment: Decimal = ZERO    # (i)
    sbco_initials: str = ""             # (j)
    rectified_date: Optional[date] = None   # (k)
    misc_transaction: str = ""          # (l)
    transfer_entry: str = ""            # (m)
    pa_initials: str = ""               # (n)
    postmaster_initials: str = ""       # (o)
    serial: int = 0                     # (a) - resets each financial year
    id: Optional[int] = None

    def __post_init__(self):
        if not self.description:
            self.description = refdata.describe(self.account_code)

    @property
    def difference_receipt(self) -> Decimal:
        return self.cbs_receipt - self.cashbook_receipt

    @property
    def difference_payment(self) -> Decimal:
        return self.cbs_payment - self.cashbook_payment

    @property
    def financial_year(self) -> str:
        return fy_label(self.entry_date)

    @property
    def is_settled(self) -> bool:
        """The order treats a discrepancy as settled only once the
        rectification has been verified, which is what the date records."""
        return self.rectified_date is not None

    @property
    def days_outstanding(self) -> int:
        end = self.rectified_date or date.today()
        return max(0, (end - self.entry_date).days)


def entries_from_reconciliation(recon_result, entry_date: date,
                                office_name: str = "") -> list:
    """Seed register entries from a day's account-code reconciliation."""
    out = []
    for source in recon_result.rows:
        if source.matched:
            continue
        code = source.account_code
        receipt = side_of(code) == RECEIPT
        out.append(RegisterEntry(
            entry_date=entry_date,
            account_code=code,
            description=getattr(source, "description", "") or "",
            office_name=office_name,
            cbs_receipt=source.finacle if receipt else ZERO,
            cbs_payment=ZERO if receipt else source.finacle,
            cashbook_receipt=source.cashbook if receipt else ZERO,
            cashbook_payment=ZERO if receipt else source.cashbook,
        ))
    return out
