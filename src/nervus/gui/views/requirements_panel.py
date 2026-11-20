"""Requirements: the list, which blocks and test cases are linked to each, and its status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.core.block import Block
from nervus.core.requirements import META_KEY, Requirement, trace, write_report
from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.models.diagram_model import DiagramModel

COLUMNS = ("Id", "Title", "Text", "Blocks", "Test cases", "Status")
STATUS_COLORS = {"verified": "#1f8a4c", "failed": "#c0392b", "not run": "#a07a12", "not tested": "#a07a12",
                 "not implemented": "#c0392b"}  # fmt: skip


class RequirementsPanel(QWidget):
    statusMessage = Signal(str)
    blockActivated = Signal(str)

    def __init__(self, model: DiagramModel, controller: EditorController, tests: Any = None,
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self.model, self.controller, self.tests = model, controller, tests
        self._updating = False
        self.summary = QLabel()
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, w in enumerate((90, 160, 320, 160, 160)):
            self.table.setColumnWidth(col, w)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setToolTip("Link blocks with right-click ▸ Requirements…, and test cases in the test editor.")
        buttons = QHBoxLayout()
        for text, slot, tip in (("Add", self._add, "Add a requirement"), ("Delete", self._delete, ""),
                                ("Import CSV…", self.import_csv, "Requirements from a CSV file (id, title, text, source)"),
                                ("Report…", self.report, "Traceability matrix as HTML")):  # fmt: skip
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=slot: f())
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.summary)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.table.itemChanged.connect(self._edited)
        self.table.itemDoubleClicked.connect(self._activated)
        for sig in (model.requirementsChanged, model.diagramReset, model.paramsChanged, model.testsChanged):
            sig.connect(self.refresh)
        if tests is not None:
            tests.finished.connect(self.refresh)
        controller.editingEnabledChanged.connect(self.setEnabled)
        self.refresh()

    def results(self) -> dict[str, bool]:
        return {name: r.passed for name, r in getattr(self.tests, "results", {}).items()}

    def refresh(self, *_args: Any) -> None:
        self._updating = True
        rows = trace(self.model.root, self.results())
        self.table.setRowCount(len(rows))
        for k, row in enumerate(rows):
            r = row.requirement
            cells = (r.id, r.title, r.text, ", ".join(row.blocks), ", ".join(row.tests), row.status)
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, r.id)
                if col >= 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 5:
                    item.setForeground(QColor(STATUS_COLORS[row.status]))
                if col == 2:
                    item.setToolTip(r.text + (f"\n\nSource: {r.source}" if r.source else ""))
                self.table.setItem(k, col, item)
        done = sum(r.status == "verified" for r in rows)
        self.summary.setText(f"{done} of {len(rows)} verified" if rows else "No requirements yet")
        self._updating = False

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        old = self.model.root.requirements[rid]
        fields = dict(old.__dict__)
        fields[("id", "title", "text")[item.column()]] = item.text().strip()
        try:
            new = Requirement(**fields)
        except ValueError as exc:
            self.statusMessage.emit(str(exc))
            self.refresh()
            return
        if not self.controller.set_requirement(rid, new):
            self.refresh()

    def _add(self) -> None:
        ids = set(self.model.root.requirements)
        k = 1
        while f"REQ-{k:03d}" in ids:
            k += 1
        if self.controller.set_requirement(None, Requirement(f"REQ-{k:03d}", "New requirement")):
            row = self.table.rowCount() - 1
            self.table.setCurrentCell(row, 1)
            item = self.table.item(row, 1)
            if item is not None:
                self.table.editItem(item)

    def _delete(self) -> None:
        ids = {i.data(Qt.ItemDataRole.UserRole) for i in self.table.selectedItems()}
        for rid in sorted(ids):
            self.controller.set_requirement(rid, None)

    def import_csv(self, path: str | None = None) -> list[str]:
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import requirements", "", "CSV files (*.csv);;All files (*)")
            if not path:
                return []
        ids = self.controller.import_requirements(path)
        if ids:
            self.statusMessage.emit(f"Imported {len(ids)} requirements from {Path(path).name}")
        return ids

    def report(self, path: str | None = None) -> Path | None:
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Traceability report", "traceability.html", "HTML (*.html)")
            if not path:
                return None
        out = write_report(self.model.root, path, self.results())
        self.statusMessage.emit(f"Wrote {out.name}")
        return out

    def _activated(self, item: QTableWidgetItem) -> None:
        blocks = self.table.item(item.row(), 3)
        if blocks is not None and blocks.text():
            self.blockActivated.emit(blocks.text().split(", ")[0])


class LinkRequirementsDialog(QDialog):
    """Tick the requirements a block implements."""

    def __init__(self, block: Block, ids: list[str], titles: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Requirements of {block.name}")
        self.list = QListWidget()
        linked = set(block.meta.get(META_KEY, []))
        for rid in ids:
            item = QListWidgetItem(f"{rid}  {titles.get(rid, '')}")
            item.setData(Qt.ItemDataRole.UserRole, rid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rid in linked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The requirements this block implements:" if ids else
                                "The model has no requirements yet: add them in the Requirements tab."))  # fmt: skip
        layout.addWidget(self.list)
        layout.addWidget(buttons)

    def chosen(self) -> list[str]:
        return [self.list.item(k).data(Qt.ItemDataRole.UserRole) for k in range(self.list.count())
                if self.list.item(k).checkState() == Qt.CheckState.Checked]  # fmt: skip
