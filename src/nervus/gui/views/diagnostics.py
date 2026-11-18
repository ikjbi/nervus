"""Diagnostics panel: problems in the diagram and simulation errors. Click an entry to select the blocks."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from nervus.core import Severity
from nervus.gui.models.diagram_model import DiagramModel
from nervus.gui.models.simulation_model import SimulationModel
from nervus.gui.theme import ThemeManager, current_theme


class DiagnosticsPanel(QWidget):
    blocksActivated = Signal(tuple)  # block names
    errorBlocksChanged = Signal(tuple)  # names of blocks with errors

    def __init__(self, model: DiagramModel, sim: SimulationModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.sim = sim
        self.list = QListWidget()
        self.list.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.list)
        self._sim_error: tuple[str, tuple[str, ...]] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        model.changed.connect(self._timer.start)
        model.changed.connect(self._clear_sim_error)
        sim.errorOccurred.connect(self._on_sim_error)
        self.list.itemClicked.connect(self._clicked)
        ThemeManager.instance().themeChanged.connect(self._on_theme)
        self.refresh()

    def _on_theme(self, _theme: object) -> None:
        self.refresh()

    def _clear_sim_error(self) -> None:
        self._sim_error = None

    def _on_sim_error(self, message: str, blocks: tuple[str, ...]) -> None:
        self._sim_error = (message, tuple(blocks)) if message else None
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        error_blocks: list[str] = []
        if self._sim_error:
            msg, blocks = self._sim_error
            self._add("⛔", msg, blocks)
            error_blocks.extend(blocks)
        issues = self.model.root.check()
        for issue in issues:
            if issue.severity is Severity.ERROR:
                self._add("⛔", issue.message, issue.blocks)
                error_blocks.extend(issue.blocks)
        for issue in issues:
            if issue.severity is Severity.WARNING:
                self._add("⚠", issue.message, issue.blocks)
        if self.list.count() == 0:
            item = QListWidgetItem("✓  No problems found.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.errorBlocksChanged.emit(tuple(dict.fromkeys(error_blocks)))

    def _add(self, icon: str, message: str, blocks: tuple[str, ...]) -> None:
        item = QListWidgetItem(f"{icon}  {message}")
        item.setData(Qt.ItemDataRole.UserRole, blocks)
        item.setForeground(current_theme().color("text"))
        item.setToolTip("Click to select the block(s)" if blocks else message)
        self.list.addItem(item)

    def _clicked(self, item: QListWidgetItem) -> None:
        blocks = item.data(Qt.ItemDataRole.UserRole)
        if blocks:
            self.blocksActivated.emit(tuple(blocks))

    def counts(self) -> tuple[int, int]:
        errors = warnings = 0
        for i in range(self.list.count()):
            text = self.list.item(i).text()
            errors += text.startswith("⛔")
            warnings += text.startswith("⚠")
        return errors, warnings
