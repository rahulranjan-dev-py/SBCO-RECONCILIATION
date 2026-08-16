"""Discrepancy Register page (Annexure-IV Table-3): view, add, settle, export."""

from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...db import get_session
from ...services import register_service
from ..dataframe_model import DataFrameModel
from ..widgets import make_date_edit, make_table, qdate_to_date, save_frame_dialog

MONEY = {
    "Receipt (CBS)", "Payment (CBS)", "Receipt (Cash Book)", "Payment (Cash Book)",
    "Diff Receipt", "Diff Payment",
}


def _money_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0, 10**12)
    spin.setDecimals(2)
    spin.setGroupSeparatorShown(True)
    return spin


class AddEntryDialog(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("New discrepancy entry")
        form = QFormLayout(self)
        self.date_edit = make_date_edit()
        self.code_edit = QLineEdit()
        self.office_edit = QLineEdit()
        self.cbs_r, self.cbs_p = _money_spin(), _money_spin()
        self.cb_r, self.cb_p = _money_spin(), _money_spin()
        self.remarks_edit = QLineEdit()
        form.addRow("Date:", self.date_edit)
        form.addRow("Account code:", self.code_edit)
        form.addRow("Office where found:", self.office_edit)
        form.addRow("Receipt as per CBS:", self.cbs_r)
        form.addRow("Payment as per CBS:", self.cbs_p)
        form.addRow("Receipt as per Cash Book:", self.cb_r)
        form.addRow("Payment as per Cash Book:", self.cb_p)
        form.addRow("Remarks:", self.remarks_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> bool:
        code = self.code_edit.text().strip()
        if not code.isdigit():
            QMessageBox.warning(self, "Register", "Enter a numeric account code.")
            return False
        with get_session() as session:
            register_service.add_entry(
                session,
                date=qdate_to_date(self.date_edit),
                account_code=code,
                office_name=self.office_edit.text().strip(),
                cbs_receipt=self.cbs_r.value(),
                cbs_payment=self.cbs_p.value(),
                cb_receipt=self.cb_r.value(),
                cb_payment=self.cb_p.value(),
                remarks=self.remarks_edit.text().strip(),
            )
        return True


class SettleDialog(QDialog):
    def __init__(self, parent: QWidget, entry_id: int, label: str):
        super().__init__(parent)
        self.entry_id = entry_id
        self.setWindowTitle("Settle discrepancy")
        form = QFormLayout(self)
        form.addRow(QLabel(label))
        self.date_edit = make_date_edit()
        self.misc_edit = QLineEdit()
        self.te_edit = QLineEdit()
        form.addRow("Date of rectification:", self.date_edit)
        form.addRow("Misc. transaction particulars:", self.misc_edit)
        form.addRow("Transfer entry particulars:", self.te_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> None:
        with get_session() as session:
            register_service.settle_entry(
                session,
                self.entry_id,
                rectified_on=qdate_to_date(self.date_edit),
                misc_txn_particulars=self.misc_edit.text().strip(),
                te_particulars=self.te_edit.text().strip(),
            )


class RegisterPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>CBS Daily Discrepancy Reconciliation Register</h2>"))

        bar = QHBoxLayout()
        self.status_combo = QComboBox()
        self.status_combo.addItem("All", None)
        self.status_combo.addItem("Open only", "OPEN")
        self.status_combo.addItem("Settled only", "SETTLED")
        self.status_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.status_combo)
        add_btn = QPushButton("Add entry…")
        add_btn.clicked.connect(self._add)
        bar.addWidget(add_btn)
        settle_btn = QPushButton("Settle selected…")
        settle_btn.clicked.connect(self._settle)
        bar.addWidget(settle_btn)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export)
        bar.addWidget(export_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.model = DataFrameModel(money_columns=MONEY, diff_columns={"Diff Receipt", "Diff Payment"})
        self.table = make_table(self.model)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        with get_session() as session:
            df = register_service.register_frame(session, status=self.status_combo.currentData())
        self.model.set_frame(df)

    def _add(self) -> None:
        dialog = AddEntryDialog(self)
        while dialog.exec() == QDialog.Accepted:
            if dialog.save():
                self.refresh()
                break

    def _settle(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        df = self.model.frame
        if not selection or df.empty:
            QMessageBox.information(self, "Register", "Select an entry first.")
            return
        record = df.iloc[selection[0].row()]
        if record["Status"] == "SETTLED":
            QMessageBox.information(self, "Register", "That entry is already settled.")
            return
        label = f"Sl {record['Sl No']} ({record['FY']}) — A/c {record['Account Code']}"
        dialog = SettleDialog(self, int(record["ID"]), label)
        if dialog.exec() == QDialog.Accepted:
            dialog.save()
            self.refresh()

    def _export(self) -> None:
        df = self.model.frame
        export_df = df.drop(columns=["ID"]) if "ID" in df.columns else df
        save_frame_dialog(
            self, export_df, "CBS Daily Discrepancy Reconciliation Register",
            f"Generated {dt.date.today():%d/%m/%Y} (Annexure-IV Table-3, SB Order 09/2026)",
            "discrepancy_register.xlsx", sorted(MONEY),
        )
