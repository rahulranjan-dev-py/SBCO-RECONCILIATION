"""Masters & settings: HO details for report headers, and the office master
that drives the office-wise reconciliation."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...db import get_session
from ...services import settings_service
from ..dataframe_model import DataFrameModel
from ..widgets import make_table


class OfficeDialog(QDialog):
    def __init__(self, parent: QWidget, record: dict | None = None):
        super().__init__(parent)
        self.record = record or {}
        self.setWindowTitle("Office" if record else "New office")
        form = QFormLayout(self)
        self.name_edit = QLineEdit(self.record.get("Office Name", ""))
        self.id_edit = QLineEdit(self.record.get("Office ID", ""))
        self.sol_edit = QLineEdit(self.record.get("SOL / BO Code", ""))
        self.group_edit = QLineEdit(self.record.get("SOL Group", ""))
        form.addRow("Office name:", self.name_edit)
        form.addRow("Office ID (APT):", self.id_edit)
        form.addRow("SOL ID (HO/SO) or BO code:", self.sol_edit)
        form.addRow("SOL group (parent SO's SOL for BOs):", self.group_edit)
        form.addRow(QLabel(
            "For HOs and SOs the SOL group is their own SOL ID.\n"
            "For BOs it is the parent SO's SOL ID (Finacle posts BO data there)."
        ))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> bool:
        name, office_id = self.name_edit.text().strip(), self.id_edit.text().strip()
        if not name or not office_id:
            QMessageBox.warning(self, "Office", "Office name and Office ID are required.")
            return False
        with get_session() as session:
            settings_service.upsert_office(
                session, name, office_id,
                self.sol_edit.text().strip(), self.group_edit.text().strip(),
                row_id=self.record.get("ID"),
            )
        return True


class MastersPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Masters &amp; settings</h2>"))

        ho_box = QGroupBox("Head Office details (used on the monthly PAO report)")
        ho_form = QFormLayout(ho_box)
        self.ho_edit = QLineEdit()
        self.ddo_edit = QLineEdit()
        self.division_edit = QLineEdit()
        ho_form.addRow("HO name:", self.ho_edit)
        ho_form.addRow("DDO code:", self.ddo_edit)
        ho_form.addRow("Division:", self.division_edit)
        save_btn = QPushButton("Save details")
        save_btn.clicked.connect(self._save_settings)
        ho_form.addRow(save_btn)
        layout.addWidget(ho_box)

        office_box = QGroupBox("Office master (HO, SOs and BOs under this HO)")
        office_layout = QVBoxLayout(office_box)
        bar = QHBoxLayout()
        add_btn = QPushButton("Add office…")
        add_btn.clicked.connect(self._add_office)
        bar.addWidget(add_btn)
        edit_btn = QPushButton("Edit selected…")
        edit_btn.clicked.connect(self._edit_office)
        bar.addWidget(edit_btn)
        del_btn = QPushButton("Delete selected")
        del_btn.clicked.connect(self._delete_office)
        bar.addWidget(del_btn)
        bar.addStretch(1)
        office_layout.addLayout(bar)
        self.office_model = DataFrameModel()
        self.office_table = make_table(self.office_model)
        office_layout.addWidget(self.office_table)
        layout.addWidget(office_box, stretch=1)

    def refresh(self) -> None:
        with get_session() as session:
            cfg = settings_service.all_settings(session)
            self.office_model.set_frame(settings_service.offices_frame(session))
        self.ho_edit.setText(cfg["ho_name"])
        self.ddo_edit.setText(cfg["ddo_code"])
        self.division_edit.setText(cfg["division"])

    def _save_settings(self) -> None:
        with get_session() as session:
            settings_service.set_setting(session, "ho_name", self.ho_edit.text().strip())
            settings_service.set_setting(session, "ddo_code", self.ddo_edit.text().strip())
            settings_service.set_setting(session, "division", self.division_edit.text().strip())
        QMessageBox.information(self, "Settings", "Saved.")

    def _selected_record(self) -> dict | None:
        selection = self.office_table.selectionModel().selectedRows()
        df = self.office_model.frame
        if not selection or df.empty:
            return None
        return df.iloc[selection[0].row()].to_dict()

    def _add_office(self) -> None:
        dialog = OfficeDialog(self)
        while dialog.exec() == QDialog.Accepted:
            if dialog.save():
                self.refresh()
                break

    def _edit_office(self) -> None:
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "Offices", "Select an office first.")
            return
        dialog = OfficeDialog(self, record)
        while dialog.exec() == QDialog.Accepted:
            if dialog.save():
                self.refresh()
                break

    def _delete_office(self) -> None:
        record = self._selected_record()
        if record is None:
            QMessageBox.information(self, "Offices", "Select an office first.")
            return
        confirm = QMessageBox.question(
            self, "Delete office", f"Delete '{record['Office Name']}' from the office master?"
        )
        if confirm != QMessageBox.Yes:
            return
        with get_session() as session:
            settings_service.delete_office(session, int(record["ID"]))
        self.refresh()
