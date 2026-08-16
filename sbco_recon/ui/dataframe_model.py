"""Qt table model over a pandas DataFrame, with money formatting and
difference highlighting."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

RED = QBrush(QColor(198, 40, 40))
GREEN = QBrush(QColor(46, 125, 50))


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, money_columns: set[str] | None = None,
                 diff_columns: set[str] | None = None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()
        self.money_columns = money_columns or set()
        self.diff_columns = diff_columns or set()

    @property
    def frame(self) -> pd.DataFrame:
        return self._df

    def set_frame(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._df.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self._df.columns[index.column()]
        value = self._df.iat[index.row(), index.column()]
        if role == Qt.DisplayRole:
            if col in self.money_columns and isinstance(value, (int, float)):
                return f"{value:,.2f}"
            return "" if value is None else str(value)
        if role == Qt.TextAlignmentRole and col in self.money_columns:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole and col in self.diff_columns and isinstance(value, (int, float)):
            if abs(value) >= 0.005:
                return RED
            return GREEN
        return None
