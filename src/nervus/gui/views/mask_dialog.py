"""Edit Mask dialog: the parameters, icon text and description of a masked subsystem."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.core import Block
from nervus.core.expressions import format_value, parse_value

COLUMNS = ("Name", "Value", "Unit", "Description")


class MaskDialog(QDialog):
    def __init__(self, subsystem: Block, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Mask — {subsystem.name}")
        self.resize(640, 420)
        self.subsystem = subsystem
        self.icon = QLineEdit(getattr(subsystem, "mask_icon", ""))
        self.icon.setPlaceholderText("text on the block, \\n for a new line, e.g. Engine\\n1.6 l")
        self.description = QLineEdit(getattr(subsystem, "mask_description", ""))
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        for v in subsystem.mask.variables:  # type: ignore[attr-defined]
            self.add_row(v.name, v.display_value, v.unit, v.description)
        add = QPushButton("Add parameter")
        remove = QPushButton("Remove")
        add.clicked.connect(lambda: self.add_row(f"p{self.table.rowCount() + 1}", "0.0", "", ""))
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        help_text = QLabel(
            "Blocks inside the subsystem can use these names in their parameters. Values may be numbers, "
            "vectors, or expressions of model workspace variables. A masked subsystem shows its parameters "
            "in the Properties panel."
        )
        help_text.setObjectName("muted")
        help_text.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Icon text", self.icon)
        form.addRow("Description", self.description)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("<b>Mask parameters</b>"))
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addWidget(help_text)
        layout.addWidget(buttons)

    def add_row(self, name: str, value: str, unit: str, description: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, text in enumerate((name, value, unit, description)):
            self.table.setItem(r, c, QTableWidgetItem(text))

    def variables(self) -> list[dict[str, Any]]:
        out = []
        for r in range(self.table.rowCount()):
            cells = []
            for c in range(4):
                item = self.table.item(r, c)
                cells.append(item.text().strip() if item is not None else "")
            if not cells[0]:
                continue
            try:
                value: Any = parse_value(cells[1])
            except ValueError:
                value = cells[1]
            out.append({"name": cells[0], "value": value, "unit": cells[2], "description": cells[3]})
        return out


__all__ = ["MaskDialog", "format_value"]
