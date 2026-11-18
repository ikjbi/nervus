"""Block library browser: drag blocks onto the canvas, or double-click to add one."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from nervus.blocks import categories
from nervus.gui.views.canvas import block_mime
from nervus.help import block_doc

CATEGORY_ORDER = [
    "Sources",
    "Sinks",
    "Math Operations",
    "Continuous",
    "Discrete",
    "Control",
    "Discontinuities",
    "Signal Routing",
    "User-Defined",
]


class _Tree(QTreeWidget):
    def startDrag(self, supported: Qt.DropAction) -> None:
        item = self.currentItem()
        type_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not type_id:
            return
        drag = QDrag(self)
        drag.setMimeData(block_mime(type_id))
        drag.exec(Qt.DropAction.CopyAction)


class LibraryBrowser(QWidget):
    addRequested = Signal(str)  # type_id
    helpRequested = Signal(str)  # type_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search blocks…")
        self.search.setClearButtonEnabled(True)
        self.tree = _Tree()
        self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.search)
        layout.addWidget(self.tree)
        self._populate()
        self.search.textChanged.connect(self._filter)
        self.tree.itemDoubleClicked.connect(self._activated)

    def _populate(self) -> None:
        cats = categories()
        order = [c for c in CATEGORY_ORDER if c in cats] + sorted(c for c in cats if c not in CATEGORY_ORDER)
        for cat in order:
            parent = QTreeWidgetItem([cat])
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            for cls in sorted(cats[cat], key=lambda c: c.label):
                child = QTreeWidgetItem([cls.label])
                child.setData(0, Qt.ItemDataRole.UserRole, cls.type_id)
                child.setToolTip(0, block_doc(cls).split("\n\n")[0])
                parent.addChild(child)
            parent.setExpanded(True)

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            assert cat is not None
            visible = 0
            for j in range(cat.childCount()):
                child = cat.child(j)
                assert child is not None
                match = not text or text in child.text(0).lower() or text in cat.text(0).lower()
                child.setHidden(not match)
                visible += match
            cat.setHidden(visible == 0)
            cat.setExpanded(True)

    def _activated(self, item: QTreeWidgetItem, _col: int) -> None:
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if type_id:
            self.addRequested.emit(type_id)

    def selected_type(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None
