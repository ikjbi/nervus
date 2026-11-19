"""Block library browser: drag blocks onto the canvas, or double-click to add one."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QLineEdit, QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from nervus.blocks import categories
from nervus.core import NervusError
from nervus.gui.controllers.editor_controller import LIBRARY_PREFIX
from nervus.gui.views.canvas import block_mime
from nervus.help import block_doc

LIBRARY_ROLE = Qt.ItemDataRole.UserRole + 1  # on a library's category item: the library file path

CATEGORY_ORDER = [
    "Sources",
    "Sinks",
    "Ports & Subsystems",
    "Math Operations",
    "Continuous",
    "Discrete",
    "Control",
    "Lookup Tables",
    "Logic and Bit Operations",
    "State Machines",
    "CAN",
    "Discontinuities",
    "Signal Routing",
    "Signal Attributes",
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
    librariesChanged = Signal(list)  # [Path]: the component libraries shown
    openLibraryRequested = Signal(object)  # Path: open the library file for editing

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
        self.libraries: list[Path] = []
        self._populate()
        self.search.textChanged.connect(self._filter)
        self.tree.itemDoubleClicked.connect(self._activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)

    # ------------------------------------------------------------------ component libraries

    def add_library(self, path: str | Path) -> str | None:
        """Show the components of a ``.nervlib`` file. Returns an error message, or None."""
        p = Path(path).resolve()
        if p in self.libraries:
            self.reload_libraries()
            return None
        self.libraries.append(p)
        error = self.reload_libraries()
        self.librariesChanged.emit(list(self.libraries))
        return error

    def remove_library(self, path: Path) -> None:
        if path in self.libraries:
            self.libraries.remove(path)
            self.reload_libraries()
            self.librariesChanged.emit(list(self.libraries))

    def reload_libraries(self) -> str | None:
        """Re-read every library file (e.g. after it was edited). Returns the first error, if any."""
        from nervus.library import components, load_library

        for i in reversed(range(self.tree.topLevelItemCount())):
            item = self.tree.topLevelItem(i)
            if item is not None and item.data(0, LIBRARY_ROLE):
                self.tree.takeTopLevelItem(i)
        error = None
        for p in self.libraries:
            cat = QTreeWidgetItem([f"📚 {p.stem}"])
            cat.setData(0, LIBRARY_ROLE, str(p))
            cat.setToolTip(0, f"{p}\nRight-click to open or remove this library")
            cat.setFlags(cat.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            font = cat.font(0)
            font.setBold(True)
            cat.setFont(0, font)
            self.tree.addTopLevelItem(cat)
            try:
                comps = components(load_library(p))
            except (NervusError, OSError) as exc:
                cat.setText(0, f"📚 {p.stem} (not found)")
                error = error or str(exc)
                continue
            for comp in comps:
                child = QTreeWidgetItem([comp.name])
                child.setData(0, Qt.ItemDataRole.UserRole, f"{LIBRARY_PREFIX}{p}|{comp.name}")
                child.setToolTip(0, comp.mask_description or f"Component {comp.name} from {p.name}")
                cat.addChild(child)
            cat.setExpanded(True)
        return error

    def _context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        while item is not None and not item.data(0, LIBRARY_ROLE) and item.parent() is not None:
            item = item.parent()
        if item is None or not item.data(0, LIBRARY_ROLE):
            return
        path = Path(item.data(0, LIBRARY_ROLE))
        menu = QMenu(self)
        menu.addAction("Open Library for Editing", lambda: self.openLibraryRequested.emit(path))
        menu.addAction("Reload Libraries", self.reload_libraries)
        menu.addAction("Remove from Panel", lambda: self.remove_library(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

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

    def selected_is_component(self) -> bool:
        return (self.selected_type() or "").startswith(LIBRARY_PREFIX)

    def selected_type(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None
