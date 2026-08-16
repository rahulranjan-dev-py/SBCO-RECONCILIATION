"""Office-wise reconciliation page: one account code, SOL-group comparison."""

from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...db import get_session
from ...services import officewise_service
from ..dataframe_model import DataFrameModel
from ..widgets import date_range_bar, make_date_edit, make_table, qdate_to_date, save_frame_dialog

MONEY = {"Finacle", "APT", "Difference"}


class OfficewisePage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Office-wise reconciliation (per account code)</h2>"))
        layout.addWidget(
            QLabel(
                "CBS side: Set-ID GL-Wise report (per SOL) · APT side: Accounting Details "
                "report. Finacle posts BO transactions under the parent SO's SOL, so the "
                "comparison is per SOL group; member offices show their APT share."
            )
        )

        self.start_edit = make_date_edit(dt.date.today().replace(day=1))
        self.end_edit = make_date_edit()
        bar = date_range_bar(self.start_edit, self.end_edit)
        bar.addWidget(QLabel("A/c code:"))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("e.g. 8001000100")
        self.code_edit.setFixedWidth(140)
        bar.addWidget(self.code_edit)
        refresh_btn = QPushButton("Compare")
        refresh_btn.clicked.connect(self.run_compare)
        bar.addWidget(refresh_btn)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export)
        bar.addWidget(export_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.model = DataFrameModel(money_columns=MONEY, diff_columns={"Difference"})
        layout.addWidget(make_table(self.model))

    def run_compare(self) -> None:
        code = self.code_edit.text().strip()
        if not code.isdigit():
            QMessageBox.warning(self, "Office-wise", "Enter a numeric account code.")
            return
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        if start > end:
            QMessageBox.warning(self, "Office-wise", "Start date is after end date.")
            return
        with get_session() as session:
            df = officewise_service.compare(session, code, start, end)
        self.model.set_frame(df)
        if df.empty:
            QMessageBox.information(
                self, "Office-wise",
                "No data. Import a Set-ID GL-Wise report and an APT Accounting Details "
                "report for this account code, and define offices under Masters & settings.",
            )

    def _export(self) -> None:
        code = self.code_edit.text().strip()
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        save_frame_dialog(
            self, self.model.frame, f"Office-wise reconciliation — A/c {code}",
            f"Period: {start:%d/%m/%Y} to {end:%d/%m/%Y}",
            f"officewise_{code}_{start:%Y%m%d}_{end:%Y%m%d}.xlsx", sorted(MONEY),
        )
