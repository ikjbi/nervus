"""Variants dialog: the alternative implementations of a subsystem and the conditions that choose them."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.core import Block

ORIGINAL = 0x0100  # Qt.ItemDataRole.UserRole: the variant's name when the dialog opened (None = new copy)


class VariantDialog(QDialog):
    def __init__(self, subsystem: Block, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Variants — {subsystem.name}")
        self.resize(560, 380)
        sub = subsystem
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Name", "Condition"))
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        variants = getattr(sub, "variants", {})
        if variants:
            for name, v in variants.items():
                self._add_row(name, name, v.condition)
        else:
            self._add_row(None, "default", "")
        self.active = QComboBox()
        self._refresh_active(getattr(sub, "active_variant", "") or "default")
        self.table.itemChanged.connect(lambda _item: self._refresh_active(self.active.currentText()))
        add = QPushButton("Add (copy of active)")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add_copy)
        remove.clicked.connect(self._remove)
        help_text = QLabel(
            "Each variant is a complete implementation with the same inputs and outputs. A condition such as "
            "<code>ENGINE == 2</code> uses model workspace variables; the variant whose condition is true is "
            "simulated and turned into C code. A variant with an empty condition is the default. Without any "
            "conditions, the active variant below is used."
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        form = QFormLayout()
        form.addRow("Active variant", self.active)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addLayout(form)
        layout.addWidget(help_text)
        layout.addWidget(buttons)

    def _add_row(self, original: str | None, name: str, condition: str) -> None:
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        item = QTableWidgetItem(name)
        item.setData(ORIGINAL, original)
        self.table.setItem(r, 0, item)
        self.table.setItem(r, 1, QTableWidgetItem(condition))
        self.table.blockSignals(False)

    def _add_copy(self) -> None:
        names = {n for _o, n, _c in self.rows()}
        k = 2
        while f"variant{k}" in names:
            k += 1
        self._add_row(None, f"variant{k}", "")
        self._refresh_active(self.active.currentText())

    def _remove(self) -> None:
        if self.table.rowCount() > 1 and self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self._refresh_active(self.active.currentText())

    def _refresh_active(self, keep: str) -> None:
        names = [n for _o, n, _c in self.rows()]
        self.active.blockSignals(True)
        self.active.clear()
        self.active.addItems(names)
        if keep in names:
            self.active.setCurrentText(keep)
        self.active.blockSignals(False)

    def rows(self) -> list[tuple[str | None, str, str]]:
        out = []
        for r in range(self.table.rowCount()):
            name_item, cond_item = self.table.item(r, 0), self.table.item(r, 1)
            if name_item is None:
                continue
            original = name_item.data(ORIGINAL)
            out.append((original, name_item.text().strip(), cond_item.text().strip() if cond_item else ""))
        return out
