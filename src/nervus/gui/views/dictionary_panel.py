"""The data dictionary: signal objects (type, unit, range, description) and where they are used."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.core.dictionary import named_signals
from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.models.diagram_model import DiagramModel

COLUMNS = ("Name", "Type", "Unit", "Min", "Max", "Description", "Used by")
USED_COL = 6


class DictionaryPanel(QWidget):
    statusMessage = Signal(str)
    blockActivated = Signal(str)  # block path of a named output

    def __init__(self, model: DiagramModel, controller: EditorController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model, self.controller = model, controller
        self._updating = False
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, w in enumerate((130, 90, 60, 60, 60, 220)):
            self.table.setColumnWidth(col, w)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setToolTip("Name a wire's signal (right-click the wire) to bind it to an object here.")
        add, delete = QPushButton("Add"), QPushButton("Delete")
        add.setToolTip("Add a signal object")
        add.clicked.connect(self._add)
        delete.clicked.connect(self._delete)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.table.itemChanged.connect(self._edited)
        self.table.itemDoubleClicked.connect(self._activated)
        for sig in (model.signalsChanged, model.diagramReset, model.paramsChanged, model.blockRenamed):
            sig.connect(self.refresh)
        controller.editingEnabledChanged.connect(self.setEnabled)
        self.refresh()

    def refresh(self, *_args: Any) -> None:
        self._updating = True
        dd = self.model.root.signals
        try:
            used = named_signals(self.model.root)
        except Exception:
            used = {}
        names = list(dd) + [n for n in used if n not in dd]  # named outputs without an object: shown too
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            obj = dd.get(name)
            where = f"{used[name][0]}:{used[name][1]}" if name in used else ""
            cells = (name, "", "", "", "", "(no signal object: Add one with this name)", where) if obj is None else (
                obj.name, obj.data_type, obj.unit, "" if obj.min is None else f"{obj.min:g}",
                "" if obj.max is None else f"{obj.max:g}", obj.description, where,
            )  # fmt: skip
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, name)
                if obj is None or col == USED_COL:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self._updating = False

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        name, text, col = item.data(Qt.ItemDataRole.UserRole), item.text().strip(), item.column()
        key = COLUMNS[col].lower()
        changes: dict[str, Any]
        if col in (3, 4):
            try:
                changes = {key: float(text) if text else None}
            except ValueError:
                self.statusMessage.emit(f"{key} must be a number")
                self.refresh()
                return
        elif col == 1:
            changes = {"data_type": text or "inherit"}
        else:
            changes = {key: text}
        if not self.controller.update_signal_object(name, **changes):
            self.refresh()

    def _add(self) -> None:
        row_item = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        unnamed = row_item.data(Qt.ItemDataRole.UserRole) if row_item is not None else None
        name = unnamed if unnamed is not None and unnamed not in self.model.root.signals else None
        obj = self.controller.add_signal_object(name)
        if obj is not None:
            self.statusMessage.emit(f"Added signal object {obj.name}")

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        for r in rows:
            item = self.table.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in self.model.root.signals:
                self.controller.delete_signal_object(item.data(Qt.ItemDataRole.UserRole))

    def _activated(self, item: QTableWidgetItem) -> None:
        where = self.table.item(item.row(), USED_COL)
        if where is not None and where.text():
            self.blockActivated.emit(where.text().rsplit(":", 1)[0])
