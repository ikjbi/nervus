"""Autocompletion of workspace variable names in parameter fields."""

from __future__ import annotations

import re

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QLineEdit, QWidget

from nervus.core import Diagram

_LAST_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def visible_names(diagram: Diagram) -> list[str]:
    """Variable names a block in ``diagram`` can use: the model workspace and the masks of the subsystems
    around it (without evaluating them)."""
    names: list[str] = []
    d: Diagram | None = diagram
    while d is not None:
        parent = d.parent
        mask = getattr(parent, "mask", None)
        if mask is not None:
            names.extend(mask)
        if parent is None or parent.diagram is None:
            names.extend(d.workspace)
            break
        d = parent.diagram
    return sorted(set(names), key=str.lower)


class VariableCompleter(QCompleter):
    """Completes the word under the cursor, so ``Kp / T`` offers ``Ti`` and keeps ``Kp / ``."""

    def __init__(self, names: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._names = QStringListModel(names, self)  # owned by the completer, so it is not garbage-collected
        self.setModel(self._names)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._prefix = ""

    def splitPath(self, path: str) -> list[str]:
        m = _LAST_WORD.search(path)
        if m is None:
            self._prefix = path
            return ["\x00"]  # matches nothing: no popup after an operator or a number
        self._prefix = path[: m.start()]
        return [m.group(0)]

    def pathFromIndex(self, index: QModelIndex | QPersistentModelIndex) -> str:
        return self._prefix + str(index.data())


def attach_completer(edit: QLineEdit, diagram: Diagram | None) -> None:
    """Offer the variable names visible in ``diagram`` while typing in ``edit``."""
    if diagram is None:
        return
    names = visible_names(diagram)
    if names:
        edit.setCompleter(VariableCompleter(names, edit))
