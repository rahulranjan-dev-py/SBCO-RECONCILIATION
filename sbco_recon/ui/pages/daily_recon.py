"""Daily account-code-wise reconciliation (the legacy 'CBS' sheet), with a
datewise drilldown dialog and one-click 'add to register'."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...db import get_session
from ...services import recon_service, register_service
from ..dataframe_model import DataFrameModel
from ..widgets import date_range_bar, make_date_edit, make_table, qdate_to_date, save_frame_dialog

MONEY = {"Finacle", "Cashbook", "Difference"}


class DatewiseDialog(QDialog):
    def __init__(self, parent: QWidget, account_code: str, description: str,
                 start: dt.date, end: dt.date):
        super().__init__(parent)
        self.setWindowTitle(f"Datewise — {account_code}")
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{account_code}</b> — {description}"))
        with get_session() as session:
            df = recon_service.datewise(session, account_code, start, end)
        model = DataFrameModel(df, money_columns=MONEY, diff_columns={"Difference"})
        layout.addWidget(make_table(model))
        export_btn = QPushButton("Export to Excel…")
        export_btn.clicked.connect(
            lambda: save_frame_dialog(
                self, df, f"Datewise reconciliation — A/c {account_code}",
                f"{description} | {start:%d/%m/%Y} to {end:%d/%m/%Y}",
                f"datewise_{account_code}.xlsx", sorted(MONEY),
            )
        )
        layout.addWidget(export_btn)


class DailyReconPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Daily reconciliation (Finacle vs Cashbook)</h2>"))

        self.start_edit = make_date_edit(dt.date.today() - dt.timedelta(days=1))
        self.end_edit = make_date_edit(dt.date.today() - dt.timedelta(days=1))
        bar = date_range_bar(self.start_edit, self.end_edit)
        self.nonzero = QCheckBox("Show only differences")
        self.nonzero.setChecked(True)
        bar.addWidget(self.nonzero)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export)
        bar.addWidget(export_btn)
        register_btn = QPushButton("Add selected to register")
        register_btn.clicked.connect(self._add_selected_to_register)
        bar.addWidget(register_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.model = DataFrameModel(money_columns=MONEY, diff_columns={"Difference"})
        self.table = make_table(self.model)
        self.table.doubleClicked.connect(self._drilldown)
        layout.addWidget(self.table)
        layout.addWidget(QLabel("Double-click a row for the datewise drilldown."))

    def refresh(self) -> None:
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        if start > end:
            QMessageBox.warning(self, "Reconciliation", "Start date is after end date.")
            return
        self.setCursor(Qt.WaitCursor)
        try:
            with get_session() as session:
                df = recon_service.daily_codewise(session, start, end, self.nonzero.isChecked())
        finally:
            self.unsetCursor()
        self.model.set_frame(df)

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def _drilldown(self, index: QModelIndex) -> None:
        df = self.model.frame
        if df.empty:
            return
        row = df.iloc[index.row()]
        DatewiseDialog(
            self, row["Account Code"], row["Description"],
            qdate_to_date(self.start_edit), qdate_to_date(self.end_edit),
        ).exec()

    def _export(self) -> None:
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        save_frame_dialog(
            self, self.model.frame, "Daily reconciliation — Finacle vs APT Cashbook",
            f"Period: {start:%d/%m/%Y} to {end:%d/%m/%Y}",
            f"daily_recon_{start:%Y%m%d}_{end:%Y%m%d}.xlsx", sorted(MONEY),
        )

    def _add_selected_to_register(self) -> None:
        rows = self._selected_rows()
        df = self.model.frame
        if not rows or df.empty:
            QMessageBox.information(self, "Register", "Select one or more rows first.")
            return
        end = qdate_to_date(self.end_edit)
        added = 0
        with get_session() as session:
            for r in rows:
                record = df.iloc[r]
                if abs(record["Difference"]) < 0.005:
                    continue
                # Each IT2.0 code is receipt- or payment-side; the register keeps
                # both column pairs, so place amounts on the receipt columns by
                # default and let the user refine office/side in the register page.
                register_service.add_entry(
                    session,
                    date=end,
                    account_code=str(record["Account Code"]),
                    cbs_receipt=float(record["Finacle"]),
                    cb_receipt=float(record["Cashbook"]),
                    remarks="Auto-added from daily reconciliation",
                )
                added += 1
        QMessageBox.information(self, "Register", f"{added} entr(y/ies) added to the register.")
