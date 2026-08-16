"""Typed records used throughout the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

ZERO = Decimal("0")


class Source(str, Enum):
    """Where a ledger entry came from."""

    FINACLE_GL = "finacle_gl"          # GL IT2.0 Transaction GL Wise Report
    FINACLE_TXN = "finacle_txn"        # GL IT2.0 Transaction Report
    CASHBOOK = "cashbook"              # APT 2.0 Cashbook
    APT_DETAILS = "apt_details"        # APT Accounting Details Report
    MANUAL = "manual"                  # Operator-entered adjustment
    TRANSFER_ENTRY = "transfer_entry"  # Approved TE


@dataclass(frozen=True)
class Office:
    """One office in the HO's establishment."""

    name: str
    office_id: str
    sol_id: str        # SOL ID for HO/SO, BO code for a Branch Office
    sol_group: str     # Parent SO's SOL ID for a BO, else own SOL ID

    @property
    def is_branch_office(self) -> bool:
        return self.sol_id != self.sol_group


@dataclass(frozen=True)
class Entry:
    """A single ledger line, normalised. Immutable by design.

    The legacy tool mutated rows in place across staging sheets, so a failed
    step could leave half-transformed data behind. Entries here are created
    once by a parser and never modified.
    """

    txn_date: date
    account_code: str
    amount: Decimal
    source: Source
    office_id: str = ""
    sol_id: str = ""
    description: str = ""
    batch_id: int = 0

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal, not float")


@dataclass
class ReconRow:
    """One line of the account-code reconciliation."""

    account_code: str
    description: str
    finacle: Decimal = ZERO
    cashbook: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.finacle - self.cashbook

    @property
    def matched(self) -> bool:
        return self.difference == ZERO

    @property
    def has_activity(self) -> bool:
        return self.finacle != ZERO or self.cashbook != ZERO


@dataclass
class OfficeReconRow:
    """One line of the office-wise reconciliation."""

    office: Office
    finacle: Decimal = ZERO
    apt: Decimal = ZERO

    @property
    def difference(self) -> Decimal:
        return self.finacle - self.apt

    @property
    def matched(self) -> bool:
        return self.difference == ZERO


@dataclass
class ReconResult:
    """The outcome of a reconciliation run."""

    period: "object"
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def differences(self) -> list:
        return [r for r in self.rows if not r.matched]

    @property
    def total_finacle(self) -> Decimal:
        return sum((r.finacle for r in self.rows), ZERO)

    @property
    def total_cashbook(self) -> Decimal:
        return sum((getattr(r, "cashbook", None) or getattr(r, "apt", ZERO)
                    for r in self.rows), ZERO)

    @property
    def total_difference(self) -> Decimal:
        return sum((r.difference for r in self.rows), ZERO)

    @property
    def is_balanced(self) -> bool:
        return not self.differences

    def summary(self) -> str:
        return (f"{len(self.rows)} codes | {len(self.differences)} with differences | "
                f"net {self.total_difference:,}")


@dataclass
class FileOutcome:
    """The fate of one uploaded file. Every file gets exactly one of these.

    This is the record that makes silent file loss impossible: the batch
    runner asserts that outcomes == files submitted before it reports.
    """

    path: str
    status: str            # loaded | rejected | duplicate | failed
    reason: str = ""
    detail: str = ""
    rows: int = 0
    batch_id: Optional[int] = None
    sha256: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "loaded"
