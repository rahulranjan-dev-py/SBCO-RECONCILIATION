"""Monthly PAO report page: Annexure-IV Table-1 / Table-2 preview + export,
and the month's transfer entries."""

from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...db import get_session
from ...export import export_table1, export_table2
from ...services import monthly_service, settings_service
from ..dataframe_model import DataFrameModel
from ..widgets import make_table

T1_MONEY = set(monthly_service.TABLE1_COLUMNS[3:])
T2_MONEY = set(monthly_service.TABLE2_COLUMNS[3:])


class AddTeDialog(QDialog):
    def __init__(self, parent: QWidget, month: str):
        super().__init__(parent)
        self.month = month
        self.setWindowTitle(f"Transfer entry — {month}")
        form = QFormLayout(self)
        self.code_edit = QLineEdit()
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("TO (+) — adds to Cash Account", +1)
        self.direction_combo.addItem("FROM (−) — reduces Cash Account", -1)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0, 10**12)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setGroupSeparatorShown(True)
        self.remarks_edit = QLineEdit()
        form.addRow("Account code:", self.code_edit)
        form.addRow("Direction:", self.direction_combo)
        form.addRow("Amount:", self.amount_spin)
        form.addRow("Remarks:", self.remarks_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> bool:
        code = self.code_edit.text().strip()
        if not code.isdigit():
            QMessageBox.warning(self, "Transfer entry", "Enter a numeric account code.")
            return False
        with get_session() as session:
            monthly_service.add_transfer_entry(
                session, self.month, code, self.amount_spin.value(),
                self.direction_combo.currentData(), self.remarks_edit.text().strip(),
            )
        return True


class MonthlyPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Monthly report to PAO (Annexure-IV)</h2>"))

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Month:"))
        self.month_combo = QComboBox()
        today = dt.date.today()
        for i in range(24):
            y, m = today.year, today.month - i
            while m <= 0:
                y, m = y - 1, m + 12
            value = f"{y:04d}-{m:02d}"
            self.month_combo.addItem(dt.date(y, m, 1).strftime("%B %Y"), value)
        bar.addWidget(self.month_combo)
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self.refresh_tables)
        bar.addWidget(generate_btn)
        export1_btn = QPushButton("Export Table-1…")
        export1_btn.clicked.connect(lambda: self._export(1))
        bar.addWidget(export1_btn)
        export2_btn = QPushButton("Export Table-2…")
        export2_btn.clicked.connect(lambda: self._export(2))
        bar.addWidget(export2_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.tabs = QTabWidget()
        self.t1_model = DataFrameModel(money_columns=T1_MONEY,
                                       diff_columns={"Difference Receipts", "Difference Payments"})
        self.t2_model = DataFrameModel(money_columns=T2_MONEY,
                                       diff_columns={"Pending Receipts", "Pending Payments"})
        self.te_model = DataFrameModel(money_columns={"Amount"})

        self.tabs.addTab(make_table(self.t1_model), "Table-1 (monthly recon)")
        self.tabs.addTab(make_table(self.t2_model), "Table-2 (detailed / pendency)")

        te_tab = QWidget()
        te_layout = QVBoxLayout(te_tab)
        te_bar = QHBoxLayout()
        add_te_btn = QPushButton("Add transfer entry…")
        add_te_btn.clicked.connect(self._add_te)
        te_bar.addWidget(add_te_btn)
        del_te_btn = QPushButton("Delete selected")
        del_te_btn.clicked.connect(self._delete_te)
        te_bar.addWidget(del_te_btn)
        te_bar.addStretch(1)
        te_layout.addLayout(te_bar)
        self.te_table = make_table(self.te_model)
        te_layout.addWidget(self.te_table)
        te_layout.addWidget(QLabel(
            "Approved Transfer Entries of the DDO for the month. "
            "TO (+) adds to the Monthly Cash Account, FROM (−) reduces it (Table-1 footnote)."
        ))
        self.tabs.addTab(te_tab, "Transfer entries")
        layout.addWidget(self.tabs)

    @property
    def month(self) -> str:
        return self.month_combo.currentData()

    def refresh(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        with get_session() as session:
            self.t1_model.set_frame(monthly_service.table1(session, self.month))
            self.t2_model.set_frame(monthly_service.table2(session, self.month))
            self.te_model.set_frame(monthly_service.transfer_entries_frame(session, self.month))

    def _add_te(self) -> None:
        dialog = AddTeDialog(self, self.month)
        while dialog.exec() == QDialog.Accepted:
            if dialog.save():
                self.refresh_tables()
                break

    def _delete_te(self) -> None:
        selection = self.te_table.selectionModel().selectedRows()
        df = self.te_model.frame
        if not selection or df.empty:
            QMessageBox.information(self, "Transfer entries", "Select an entry first.")
            return
        entry_id = int(df.iloc[selection[0].row()]["ID"])
        with get_session() as session:
            monthly_service.delete_transfer_entry(session, entry_id)
        self.refresh_tables()

    def _export(self, table: int) -> None:
        df = self.t1_model.frame if table == 1 else self.t2_model.frame
        if df.empty:
            QMessageBox.information(self, "Export", "Generate the report first (no rows to export).")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export Table-{table}", f"annexure4_table{table}_{self.month}.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        with get_session() as session:
            cfg = settings_service.all_settings(session)
        if table == 1:
            export_table1(df, path, self.month, cfg["ddo_code"], cfg["ho_name"], cfg["division"])
        else:
            export_table2(df, path, self.month, cfg["ddo_code"], cfg["ho_name"], cfg["division"])
        QMessageBox.information(self, "Export", f"Saved to:\n{path}")
