"""Mismatch heads: accounted vs cleared vs outstanding (legacy MISMATCH ENTRIES)."""

from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ...db import get_session
from ...services import recon_service
from ..dataframe_model import DataFrameModel
from ..widgets import date_range_bar, make_date_edit, make_table, qdate_to_date, save_frame_dialog

MONEY = {"Accounted", "Cleared", "Outstanding"}


class MismatchPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>CBS / IPPB / PLI mismatch heads</h2>"))

        self.start_edit = make_date_edit(dt.date.today().replace(day=1))
        self.end_edit = make_date_edit()
        bar = date_range_bar(self.start_edit, self.end_edit)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export)
        bar.addWidget(export_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.model = DataFrameModel(money_columns=MONEY, diff_columns={"Outstanding"})
        layout.addWidget(make_table(self.model))

    def refresh(self) -> None:
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        if start > end:
            QMessageBox.warning(self, "Mismatch", "Start date is after end date.")
            return
        with get_session() as session:
            self.model.set_frame(recon_service.mismatch_summary(session, start, end))

    def _export(self) -> None:
        start, end = qdate_to_date(self.start_edit), qdate_to_date(self.end_edit)
        save_frame_dialog(
            self, self.model.frame, "Mismatch entries — accounted vs cleared",
            f"Period: {start:%d/%m/%Y} to {end:%d/%m/%Y}",
            f"mismatch_{start:%Y%m%d}_{end:%Y%m%d}.xlsx", sorted(MONEY),
        )
