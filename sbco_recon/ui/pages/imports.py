"""Import page: batch file selection, processing summary, delete-by-range tools."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...db import get_session
from ...db.models import ImportLog
from ...parsers import apt_details, cashbook, glwise
from ...services import import_service
from ..dataframe_model import DataFrameModel
from ..widgets import make_date_edit, make_table, qdate_to_date

REPORT_LABELS = {
    glwise.REPORT_TYPE: "Finacle GL-Wise (CBS)",
    cashbook.REPORT_TYPE: "APT Cashbook",
    apt_details.REPORT_TYPE: "APT Accounting Details (office-wise)",
}


class ImportsPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Import reports</h2>"))
        layout.addWidget(
            QLabel(
                "Select one or more Excel files — the report type (Finacle GL-Wise / APT "
                "Cashbook / APT Accounting Details) is detected automatically. Re-uploads "
                "of already-loaded dates are refused; delete the date range first to re-import."
            )
        )

        pick = QPushButton("Select files to import…")
        pick.clicked.connect(self._pick_files)
        layout.addWidget(pick)

        self.log_model = DataFrameModel(pd.DataFrame())
        layout.addWidget(QLabel("<b>Processing summary</b> (most recent first)"))
        layout.addWidget(make_table(self.log_model))

        box = QGroupBox("Delete loaded data by date range")
        row = QHBoxLayout(box)
        self.type_combo = QComboBox()
        for rtype, label in REPORT_LABELS.items():
            self.type_combo.addItem(label, rtype)
        self.del_start = make_date_edit()
        self.del_end = make_date_edit()
        row.addWidget(self.type_combo)
        row.addWidget(QLabel("From:"))
        row.addWidget(self.del_start)
        row.addWidget(QLabel("To:"))
        row.addWidget(self.del_end)
        del_btn = QPushButton("Delete range")
        del_btn.clicked.connect(self._delete_range)
        row.addWidget(del_btn)
        layout.addWidget(box)

    def refresh(self) -> None:
        with get_session() as session:
            logs = session.scalars(
                select(ImportLog).order_by(ImportLog.imported_at.desc()).limit(200)
            ).all()
        df = pd.DataFrame(
            [
                {
                    "File": l.file_name,
                    "Type": REPORT_LABELS.get(l.report_type, l.report_type),
                    "Report Date": l.report_date.strftime("%d/%m/%Y") if l.report_date else "",
                    "Status": l.status,
                    "Rows": l.row_count,
                    "Message": l.message,
                    "Imported At": l.imported_at.strftime("%d/%m/%Y %H:%M:%S"),
                }
                for l in logs
            ]
        )
        self.log_model.set_frame(df)

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select report files", "", "Excel files (*.xls *.xlsx *.xlsm)"
        )
        if not paths:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            with get_session() as session:
                results = import_service.import_files(session, paths)
        finally:
            self.unsetCursor()
        self.refresh()

        processed = sum(1 for r in results if r.status == "PROCESSED")
        problems = [r for r in results if r.status != "PROCESSED"]
        message = f"Processed: {processed} of {len(results)} file(s)."
        if problems:
            message += "\n\nSkipped:\n" + "\n".join(
                f"• {r.file_name}: {r.status} — {r.message}" for r in problems[:15]
            )
        QMessageBox.information(self, "Import complete", message)

    def _delete_range(self) -> None:
        rtype = self.type_combo.currentData()
        start, end = qdate_to_date(self.del_start), qdate_to_date(self.del_end)
        if start > end:
            QMessageBox.warning(self, "Delete", "Start date is after end date.")
            return
        label = REPORT_LABELS[rtype]
        confirm = QMessageBox.question(
            self,
            "Confirm deletion",
            f"Delete all {label} data from {start:%d/%m/%Y} to {end:%d/%m/%Y}?",
        )
        if confirm != QMessageBox.Yes:
            return
        with get_session() as session:
            count = import_service.delete_date_range(session, rtype, start, end)
        self.refresh()
        QMessageBox.information(self, "Delete", f"{count} row(s) deleted from {label}.")
