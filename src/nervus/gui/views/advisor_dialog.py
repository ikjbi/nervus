"""Model Advisor dialog: findings of the static checks; click one to show the block."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.advisor import RULES, Finding, advise
from nervus.core import Diagram


class AdvisorDialog(QDialog):
    blocksActivated = Signal(tuple)

    def __init__(self, diagram: Diagram, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.diagram = diagram
        self.setWindowTitle("Model Advisor")
        self.resize(900, 520)
        self.summary = QLabel()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Rule", "Finding", "Blocks"])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.setColumnWidth(0, 28)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 520)
        rerun = QPushButton("Run again")
        rerun.setObjectName("primary")
        rules = QLabel("Rules: " + "; ".join(f"<b>{k}</b> ({d})" for k, (d, _) in RULES.items()))
        rules.setObjectName("muted")
        rules.setWordWrap(True)
        bar = QHBoxLayout()
        bar.addWidget(self.summary, 1)
        bar.addWidget(rerun)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.tree, 1)
        layout.addWidget(rules)
        rerun.clicked.connect(self.run)
        self.tree.itemClicked.connect(self._clicked)
        self.findings: list[Finding] = []
        self.run()

    def run(self) -> list[Finding]:
        self.findings = advise(self.diagram)
        self.tree.clear()
        for f in self.findings:
            item = QTreeWidgetItem(["⚠" if f.severity == "warning" else "ℹ", f.rule, f.message, ", ".join(f.blocks)])
            item.setData(0, Qt.ItemDataRole.UserRole, f.blocks)
            item.setToolTip(2, f.message)
            self.tree.addTopLevelItem(item)
        warnings = sum(f.severity == "warning" for f in self.findings)
        self.summary.setText(
            "✓ No findings."
            if not self.findings
            else f"{warnings} warning(s), {len(self.findings) - warnings} suggestion(s). Click a finding to show the block."
        )
        return self.findings

    def _clicked(self, item: QTreeWidgetItem) -> None:
        blocks = item.data(0, Qt.ItemDataRole.UserRole)
        if blocks:
            self.blocksActivated.emit(tuple(blocks))
