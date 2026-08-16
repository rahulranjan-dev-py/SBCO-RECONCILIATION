"""SQLAlchemy models.

Mirrors the data stores of the legacy Excel tool (TEMP.FIN, TEMP.CBR, DESC.RPT, ...)
as proper relational tables. Receipts and payments are distinct account codes in
IT 2.0, so daily amounts are single-valued per (date, account_code) after aggregation.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountCode(Base):
    """Master of IT 2.0 account codes (seeded from the legacy tool, ~3,000 rows)."""

    __tablename__ = "account_codes"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    hoa: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text, default="")
    side: Mapped[str | None] = mapped_column(String(20))  # "Receipt Side" / "Payment Side"
    sign: Mapped[str | None] = mapped_column(String(10))  # "Positive" / "Negative"
    part: Mapped[str | None] = mapped_column(String(10))  # Part I / II / III


class MismatchPair(Base):
    """The 8 mismatch heads and their '_Cleared' counterpart codes."""

    __tablename__ = "mismatch_pairs"

    mismatch_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    mismatch_desc: Mapped[str] = mapped_column(Text, default="")
    cleared_code: Mapped[str] = mapped_column(String(20))
    cleared_desc: Mapped[str] = mapped_column(Text, default="")


class Office(Base):
    """Office master: HO, SOs and BOs. BOs carry their parent SO's SOL in sol_group."""

    __tablename__ = "offices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    office_id: Mapped[str] = mapped_column(String(20), unique=True)
    sol_or_bo_code: Mapped[str | None] = mapped_column(String(20))
    sol_group: Mapped[str | None] = mapped_column(String(20))


class FinacleGlDaily(Base):
    """Daily consolidated Finacle figures per account code (from the GL-wise report).

    amount = Deposits(Cr) + Withdrawals(Dr) for the code, matching the legacy tool
    (each code is inherently receipt-side or payment-side, so a single column).
    """

    __tablename__ = "finacle_gl_daily"
    __table_args__ = (
        UniqueConstraint("date", "account_code", name="uq_fin_date_code"),
        Index("ix_fin_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    account_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class FinacleSolDaily(Base):
    """Per-SOL daily Finacle figures, from a GL-wise report generated with a Set ID
    (one section per SOL). Feeds the office-wise reconciliation."""

    __tablename__ = "finacle_sol_daily"
    __table_args__ = (
        UniqueConstraint("date", "sol_id", "account_code", name="uq_finsol_date_sol_code"),
        Index("ix_finsol_code_date", "account_code", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    sol_id: Mapped[str] = mapped_column(String(20))
    account_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class AptOfficeDaily(Base):
    """Office-wise daily APT figures for one account code, from the APT
    'Accounting Details' report (Treasury >> Reports >> Accounting Details)."""

    __tablename__ = "apt_office_daily"
    __table_args__ = (Index("ix_aptoff_code_date", "account_code", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    office_id: Mapped[str | None] = mapped_column(String(20))
    office_name: Mapped[str | None] = mapped_column(String(120))
    account_code: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    remarks: Mapped[str] = mapped_column(Text, default="")


class CashbookDaily(Base):
    """Daily APT cashbook rows (one row per office x account code as downloaded)."""

    __tablename__ = "cashbook_daily"
    __table_args__ = (
        Index("ix_cb_date", "date"),
        Index("ix_cb_date_code", "date", "account_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    office_name: Mapped[str | None] = mapped_column(String(120))
    office_id: Mapped[str | None] = mapped_column(String(20))
    account_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    part: Mapped[str | None] = mapped_column(String(20))
    side: Mapped[str | None] = mapped_column(String(30))  # Receipts / Payments
    ho_amt: Mapped[float] = mapped_column(Float, default=0.0)
    so_amt: Mapped[float] = mapped_column(Float, default=0.0)
    bo_amt: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)


class ImportLog(Base):
    """Audit of every file import (the legacy 'Processing Summary', persisted)."""

    __tablename__ = "import_log"
    __table_args__ = (Index("ix_implog_type_date", "report_type", "report_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    report_type: Mapped[str] = mapped_column(String(40))
    report_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # PROCESSED / INVALID / DUPLICATE / ERROR
    message: Mapped[str] = mapped_column(Text, default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class DiscrepancyEntry(Base):
    """CBS Daily Discrepancy Reconciliation Register (Annexure-IV Table-3).

    Serial numbers restart every financial year (fy is e.g. '2026-27').
    """

    __tablename__ = "discrepancy_register"
    __table_args__ = (UniqueConstraint("fy", "serial", name="uq_reg_fy_serial"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fy: Mapped[str] = mapped_column(String(10))
    serial: Mapped[int] = mapped_column(Integer)
    date: Mapped[dt.date] = mapped_column(Date)
    account_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    office_name: Mapped[str] = mapped_column(String(120), default="")
    cbs_receipt: Mapped[float] = mapped_column(Float, default=0.0)
    cbs_payment: Mapped[float] = mapped_column(Float, default=0.0)
    cb_receipt: Mapped[float] = mapped_column(Float, default=0.0)
    cb_payment: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN / SETTLED
    rectified_on: Mapped[dt.date | None] = mapped_column(Date)
    misc_txn_particulars: Mapped[str] = mapped_column(Text, default="")
    te_particulars: Mapped[str] = mapped_column(Text, default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)

    @property
    def diff_receipt(self) -> float:
        return round(self.cbs_receipt - self.cb_receipt, 2)

    @property
    def diff_payment(self) -> float:
        return round(self.cbs_payment - self.cb_payment, 2)


class TransferEntry(Base):
    """Approved Transfer Entries of the DDO, per month (feed Annexure-IV Table-1)."""

    __tablename__ = "transfer_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    account_code: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[int] = mapped_column(Integer, default=1)  # +1 TO / -1 FROM
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    remarks: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    """Key/value app settings (HO name, DDO code, division, ...)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
