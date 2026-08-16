"""Dashboard: what data is loaded, open discrepancies, backup shortcut."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select

from ...db import get_session
from ...db.models import DiscrepancyEntry
from ...parsers import cashbook, glwise
from ...services import backup_service
from ...services.import_service import loaded_date_summary


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        title = QLabel("<h2>SBCO Reconciliation — Dashboard</h2>")
        layout.addWidget(title)

        box = QGroupBox("Loaded data")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("<b>Report</b>"), 0, 0)
        grid.addWidget(QLabel("<b>From</b>"), 0, 1)
        grid.addWidget(QLabel("<b>To</b>"), 0, 2)
        grid.addWidget(QLabel("<b>Days</b>"), 0, 3)
        self._fin_labels = [QLabel("-") for _ in range(3)]
        self._cb_labels = [QLabel("-") for _ in range(3)]
        grid.addWidget(QLabel("Finacle GL-Wise (CBS)"), 1, 0)
        grid.addWidget(QLabel("APT Cashbook"), 2, 0)
        for col, lbl in enumerate(self._fin_labels, start=1):
            grid.addWidget(lbl, 1, col)
        for col, lbl in enumerate(self._cb_labels, start=1):
            grid.addWidget(lbl, 2, col)
        layout.addWidget(box)

        self.open_label = QLabel("")
        layout.addWidget(self.open_label)

        backup_btn = QPushButton("Backup database now")
        backup_btn.clicked.connect(self._backup)
        layout.addWidget(backup_btn)
        layout.addStretch(1)

    def refresh(self) -> None:
        with get_session() as session:
            summary = loaded_date_summary(session)
            open_count = session.scalar(
                select(func.count()).select_from(DiscrepancyEntry).where(DiscrepancyEntry.status == "OPEN")
            )
        for labels, key in ((self._fin_labels, glwise.REPORT_TYPE), (self._cb_labels, cashbook.REPORT_TYPE)):
            first, last, days = summary[key]
            labels[0].setText(first.strftime("%d/%m/%Y") if first else "—")
            labels[1].setText(last.strftime("%d/%m/%Y") if last else "—")
            labels[2].setText(str(days))
        self.open_label.setText(f"<b>Open discrepancies in register:</b> {open_count}")

    def _backup(self) -> None:
        path = backup_service.create_backup()
        QMessageBox.information(self, "Backup", f"Backup created:\n{path}")
