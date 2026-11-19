"""Find Usages: where a workspace variable is used in the model."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from nervus.core import Diagram


class UsagesDialog(QDialog):
    """Lists the blocks (and other variables) that use a variable; double-click a block to show it."""

    blockActivated = Signal(str)  # block path

    def __init__(self, diagram: Diagram, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Usages of {name}")
        self.resize(560, 320)
        self.usages = diagram.usages(name)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Block", "Use"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setRootIsDecorated(False)
        for path, what in self.usages:
            item = QTreeWidgetItem([path or "(model workspace)", what])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            self.tree.addTopLevelItem(item)
        n = len(self.usages)
        summary = QLabel(
            f"<b>{name}</b> is used {n} time{'s' if n != 1 else ''}." + (" Double-click to show a block." if n else "")
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)
        self.tree.itemDoubleClicked.connect(self._activated)

    def _activated(self, item: QTreeWidgetItem, _col: int) -> None:
        path = str(item.data(0, Qt.ItemDataRole.UserRole))
        if path:
            self.blockActivated.emit(path)
