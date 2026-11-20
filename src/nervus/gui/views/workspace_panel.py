"""Model Workspace panel: named parameters used by block expressions, and parameter sets (calibrations)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.core.expressions import format_value
from nervus.core.workspace import PARAMETER_SET_EXTENSION
from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.models.diagram_model import DiagramModel

COLUMNS = ("Name", "Value", "Unit", "Min", "Max", "Type", "Cal.", "Description")
TYPE_COL, CAL_COL, DESC_COL = 5, 6, 7
CAL_FILTER = f"Parameter sets (*{PARAMETER_SET_EXTENSION});;All files (*)"


class WorkspacePanel(QWidget):
    statusMessage = Signal(str)
    usagesRequested = Signal(str)  # variable name: show where it is used

    def __init__(self, model: DiagramModel, controller: EditorController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.controller = controller
        self._updating = False
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 150)
        for c in (2, 3, 4):
            self.table.setColumnWidth(c, 60)
        self.table.setColumnWidth(TYPE_COL, 100)
        self.table.setColumnWidth(CAL_COL, 40)
        header_item = self.table.horizontalHeaderItem(TYPE_COL)
        if header_item is not None:
            header_item.setToolTip("Storage type in generated C: double, single, int16, uint8, fixdt(1,16,7), ...")
        cal_item = self.table.horizontalHeaderItem(CAL_COL)
        if cal_item is not None:
            cal_item.setToolTip("Calibratable (in RAM and the A2L file). Untick for a constant in ROM.")
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.add_button = QPushButton("Add")
        self.delete_button = QPushButton("Delete")
        self.usages_button = QPushButton("Find Usages")
        self.usages_button.setToolTip("List the blocks that use the selected variable")
        self.load_button = QPushButton("Load set…")
        self.save_button = QPushButton("Save set…")
        self.dbc_button = QPushButton("Import DBC…")
        self.dbc_button.setToolTip("Add the signals and value tables of a DBC file as variables")
        self.add_button.setToolTip("Add a workspace variable")
        self.load_button.setToolTip("Load a parameter set (calibration) and apply its values")
        self.save_button.setToolTip("Save the current values as a parameter set")
        buttons = QHBoxLayout()
        for b in (self.add_button, self.delete_button, self.usages_button, self.dbc_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        for b in (self.load_button, self.save_button):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

        self.add_button.clicked.connect(self._add)
        self.delete_button.clicked.connect(self._delete)
        self.usages_button.clicked.connect(self._find_usages)
        self.load_button.clicked.connect(self._load)
        self.save_button.clicked.connect(self._save)
        self.dbc_button.clicked.connect(lambda: self.import_dbc())
        self.table.itemChanged.connect(self._edited)
        model.workspaceChanged.connect(self.refresh)
        model.diagramReset.connect(self.refresh)
        controller.editingEnabledChanged.connect(self.setEnabled)
        self.refresh()

    def selected_name(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _find_usages(self) -> None:
        name = self.selected_name()
        if name is None:
            self.statusMessage.emit("Select a variable first.")
            return
        self.usagesRequested.emit(name)

    def refresh(self) -> None:
        self._updating = True
        ws = self.model.root.workspace
        try:
            ns: dict[str, Any] | None = ws.namespace()
        except Exception:
            ns = None
        self.table.setRowCount(len(ws))
        for row, var in enumerate(ws.variables):
            cells = (
                var.name,
                var.display_value,
                var.unit,
                "" if var.min is None else format_value(var.min),
                "" if var.max is None else format_value(var.max),
                var.data_type,
                "",
                var.description,
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, var.name)
                if col == 1 and ns is not None and (isinstance(var.value, str) or var.data_type != "double"):
                    item.setToolTip(
                        f"= {format_value(ns[var.name])}"
                        + (f" (as {var.data_type})" if var.data_type != "double" else "")
                    )
                if col == CAL_COL:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if var.calibratable else Qt.CheckState.Unchecked)
                self.table.setItem(row, col, item)
        self._updating = False

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        text = item.text().strip()
        col = item.column()
        changes: dict[str, Any]
        if col == 0:
            changes = {"name": text}
        elif col == 1:
            changes = {"value": self.controller.parse_variable_value(text)}
        elif col == 2:
            changes = {"unit": text}
        elif col == TYPE_COL:
            changes = {"data_type": text or "double"}
        elif col == CAL_COL:
            changes = {"calibratable": item.checkState() == Qt.CheckState.Checked}
        elif col in (3, 4):
            key = "min" if col == 3 else "max"
            try:
                changes = {key: float(text) if text else None}
            except ValueError:
                self.statusMessage.emit(f"{key} must be a number")
                self.refresh()
                return
        else:
            changes = {"description": text}
        if not self.controller.update_variable(name, **changes):
            self.refresh()

    def selected_names(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        names = []
        for r in rows:
            item = self.table.item(r, 0)
            if item is not None:
                names.append(item.data(Qt.ItemDataRole.UserRole))
        return names

    def _add(self) -> None:
        var = self.controller.add_variable()
        if var is not None:
            row = list(self.model.root.workspace).index(var.name)
            self.table.setCurrentCell(row, 0)
            item = self.table.item(row, 0)
            if item is not None:
                self.table.editItem(item)

    def _delete(self) -> None:
        for name in self.selected_names():
            self.controller.delete_variable(name)

    def import_dbc(self, path: str | None = None) -> list[str]:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import DBC", "", "DBC files (*.dbc);;All files (*)")
            if not path:
                return []
        added = self.controller.import_dbc(path)
        self.statusMessage.emit(f"Imported {len(added)} variables from {Path(path).name}")
        return added

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load parameter set", "", CAL_FILTER)
        if path and self.controller.load_parameter_set(path):
            self.statusMessage.emit(f"Loaded parameter set {path}")

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save parameter set", "calibration", CAL_FILTER)
        if path:
            with contextlib.suppress(Exception):
                saved = self.controller.save_parameter_set(path)
                if saved:
                    self.statusMessage.emit(f"Saved parameter set {saved.name}")
