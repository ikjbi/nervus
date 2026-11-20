"""Scripting console: Python with the model and the results in scope."""

from __future__ import annotations

import code
import contextlib
import io
import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.models.diagram_model import DiagramModel
from nervus.gui.models.simulation_model import SimulationModel

BANNER = """Nervus console. In scope: model (the open model), res (the last result), runs, simulate, load, save,
np, plt, blocks (all block classes), and help(). Changes to the model can be undone in one step."""


def _snapshot(model: DiagramModel) -> dict[str, Any] | None:
    from nervus.io.model_file import to_dict

    try:
        return to_dict(model.root)
    except Exception:  # a half-built model the script is still working on
        return None


class _Interpreter(code.InteractiveConsole):
    """Prints errors itself, instead of handing them to ``sys.excepthook`` (the app's crash dialog)."""

    def showtraceback(self) -> None:
        import sys
        import traceback

        etype, value, tb = sys.exc_info()
        self.write("".join(traceback.format_exception(etype, value, tb.tb_next if tb else None)))

    def showsyntaxerror(self, filename: str | None = None, **kwargs: Any) -> None:
        import sys
        import traceback

        etype, value, _tb = sys.exc_info()
        self.write("".join(traceback.format_exception_only(etype, value)))


class _Input(QLineEdit):
    """The input line, with history on Up/Down."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self._pos = 0

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Up and self.history:
            self._pos = max(0, self._pos - 1)
            self.setText(self.history[self._pos])
        elif event.key() == Qt.Key.Key_Down and self.history:
            self._pos = min(len(self.history), self._pos + 1)
            self.setText(self.history[self._pos] if self._pos < len(self.history) else "")
        else:
            super().keyPressEvent(event)

    def remember(self, line: str) -> None:
        if line.strip() and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._pos = len(self.history)


class ConsolePanel(QWidget):
    statusMessage = Signal(str)

    def __init__(self, model: DiagramModel, editor: EditorController, sim: SimulationModel,
                 window: Any = None, parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self.model, self.editor, self.sim = model, editor, sim
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.output.setFont(mono)
        self.prompt = QLabel(">>>")
        self.prompt.setFont(mono)
        self.input = _Input()
        self.input.setFont(mono)
        self.input.setPlaceholderText("Python, e.g. model.block('pid').params  or  res['speed'].max()")
        self.input.returnPressed.connect(self._enter)
        row = QHBoxLayout()
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.output, 1)
        layout.addLayout(row)
        self.namespace = self._namespace(window)
        self.console = _Interpreter(self.namespace, filename="<console>")
        self._lines: list[str] = []
        self._before: dict[str, Any] | None = None
        model.diagramReset.connect(self._sync)
        sim.runsChanged.connect(self._sync)
        self.write(BANNER + "\n")

    def _namespace(self, window: Any) -> dict[str, Any]:
        import numpy as np

        import nervus
        import nervus.blocks as blocks

        ns: dict[str, Any] = {"np": np, "nervus": nervus, "blocks": blocks, "simulate": nervus.simulate,
                              "load": nervus.load, "save": nervus.save, "window": window}  # fmt: skip
        with contextlib.suppress(ImportError):
            import matplotlib.pyplot as plt

            ns["plt"] = plt
        ns.update({name: getattr(blocks, name) for name in getattr(blocks, "__all__", [])})
        return ns

    def _sync(self) -> None:
        self.namespace["model"] = self.model.root
        runs = getattr(self.sim, "runs", [])
        self.namespace["runs"] = runs
        self.namespace["res"] = runs[-1].result if runs else None

    def write(self, text: str) -> None:
        self.output.moveCursor(self.output.textCursor().MoveOperation.End)
        self.output.insertPlainText(text)
        self.output.ensureCursorVisible()

    def _enter(self) -> None:
        line = self.input.text()
        self.input.clear()
        self.input.remember(line)
        self.run(line)

    def run(self, line: str) -> bool:
        """Execute one line (as typed in the console); returns True if more lines are needed."""
        self._sync()
        if not self._lines:
            self._before = _snapshot(self.model)
        self._lines.append(line)
        self.write(f"{self.prompt.text()} {line}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            more = self.console.push(line)
        self.write(buf.getvalue())
        self.prompt.setText("..." if more else ">>>")
        if not more:
            self._commit(" ".join(x.strip() for x in self._lines))
            self._lines = []
        return bool(more)

    def _commit(self, text: str) -> None:
        """Record changes the script made to the model as one undo step and refresh the editor."""
        from nervus.gui.controllers.commands import ScriptCommand

        root = self.namespace.get("model")
        if root is not self.model.root:  # the script loaded another model: open it
            from nervus.core import Diagram

            if isinstance(root, Diagram):
                self.model.set_diagram(root)
            return
        after = _snapshot(self.model)
        if self._before is None or after is None:
            return
        if json.dumps(self._before, sort_keys=True, default=str) == json.dumps(after, sort_keys=True, default=str):
            return
        self.editor.undo_stack.push(ScriptCommand(self.model, self._before, after, text))
        self.statusMessage.emit("Model changed by the console (Edit ▸ Undo reverts it)")
