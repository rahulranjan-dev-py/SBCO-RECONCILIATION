"""Small shared UI helpers."""

from __future__ import annotations

import datetime as dt

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTableView,
    QWidget,
)

from ..export import export_frame
from .dataframe_model import DataFrameModel


def make_date_edit(initial: dt.date | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd/MM/yyyy")
    date = initial or dt.date.today()
    edit.setDate(QDate(date.year, date.month, date.day))
    return edit


def qdate_to_date(edit: QDateEdit) -> dt.date:
    q = edit.date()
    return dt.date(q.year(), q.month(), q.day())


def make_table(model: DataFrameModel) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QTableView.SelectRows)
    view.setEditTriggers(QTableView.NoEditTriggers)
    view.horizontalHeader().setStretchLastSection(True)
    view.setSortingEnabled(False)
    return view


def date_range_bar(start_edit: QDateEdit, end_edit: QDateEdit) -> QHBoxLayout:
    bar = QHBoxLayout()
    bar.addWidget(QLabel("From:"))
    bar.addWidget(start_edit)
    bar.addWidget(QLabel("To:"))
    bar.addWidget(end_edit)
    return bar


def save_frame_dialog(parent: QWidget, df: pd.DataFrame, title: str, subtitle: str,
                      default_name: str, money_columns: list[str]) -> None:
    if df.empty:
        QMessageBox.information(parent, "Export", "Nothing to export.")
        return
    path, _ = QFileDialog.getSaveFileName(parent, "Export to Excel", default_name, "Excel (*.xlsx)")
    if not path:
        return
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    export_frame(df, path, title, subtitle, money_columns)
    QMessageBox.information(parent, "Export", f"Saved to:\n{path}")
