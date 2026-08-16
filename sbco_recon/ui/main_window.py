"""Main window: sidebar navigation over the feature pages."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from .. import APP_NAME, __version__
from .pages import (
    DailyReconPage,
    DashboardPage,
    ImportsPage,
    MastersPage,
    MismatchPage,
    MonthlyPage,
    OfficewisePage,
    RegisterPage,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1200, 760)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.nav = QListWidget()
        self.nav.setFixedWidth(210)
        self.nav.setIconSize(QSize(20, 20))
        self.stack = QStackedWidget()

        self.pages = [
            ("Dashboard", DashboardPage()),
            ("Import reports", ImportsPage()),
            ("Daily reconciliation", DailyReconPage()),
            ("Office-wise recon", OfficewisePage()),
            ("Mismatch heads", MismatchPage()),
            ("Discrepancy register", RegisterPage()),
            ("Monthly report (PAO)", MonthlyPage()),
            ("Masters & settings", MastersPage()),
        ]
        for label, page in self.pages:
            QListWidgetItem(label, self.nav)
            self.stack.addWidget(page)

        self.nav.currentRowChanged.connect(self._switch)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            "CBS–Cashbook reconciliation per SB Order 09/2026 | data verified against Finacle GL-Wise reports"
        )
        self.nav.setCurrentRow(0)

    def _switch(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        page = self.pages[row][1]
        if hasattr(page, "refresh"):
            page.refresh()
