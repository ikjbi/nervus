"""Code generation dialog: shows the generated C files, the interface, and runs the SIL check."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nervus.codegen import GeneratedCode
from nervus.core import Block, Diagram
from nervus.gui.controllers.codegen_controller import CodegenController
from nervus.gui.theme import monospace_font


class CodegenDialog(QDialog):
    def __init__(
        self,
        controller: CodegenController,
        target: Diagram | Block,
        code: GeneratedCode,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.controller, self.target, self.code = controller, target, code
        self.saved_to: Path | None = None
        self.setWindowTitle(f"C Code — {code.name}")
        self.resize(940, 700)

        rates = ", ".join(f"{r:g} s" for r in code.rates)
        ins = ", ".join(f"{n}[{w}]" for n, w in code.inputs) or "none"
        outs = ", ".join(f"{n}[{w}]" for n, w in code.outputs) or "none"
        info = QLabel(
            f"<b>{code.name}</b>: call <code>{code.name}_step()</code> every <b>{code.base_period:g} s</b> "
            f"(rates: {rates}).<br>Inputs: {ins}<br>Outputs: {outs}<br>"
            f"Tunable parameters: {len(code.params)}"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)

        mono = monospace_font()
        self.tabs = QTabWidget()
        for fname in (f"{code.name}.h", f"{code.name}.c", "main_example.c"):
            edit = QPlainTextEdit(code.files[fname])
            edit.setReadOnly(True)
            edit.setFont(mono)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.tabs.addTab(edit, fname)

        self.sil_label = QLabel(
            "Software-in-the-loop: compile this code and compare it with the model, step by step."
            if controller.compiler_available()
            else "Install a C compiler (gcc or clang) to run the software-in-the-loop check."
        )
        self.sil_label.setObjectName("muted")
        self.sil_label.setWordWrap(True)
        self.sil_button = QPushButton("Run SIL check")
        self.sil_button.setEnabled(controller.compiler_available())
        self.save_button = QPushButton("Save to folder…")
        self.save_button.setObjectName("primary")
        self.report_button = QPushButton("Open report")
        self.report_button.setEnabled(False)
        self.copy_button = QPushButton("Copy")
        close = QPushButton("Close")

        buttons = QHBoxLayout()
        buttons.addWidget(self.sil_button)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.sil_label)
        layout.addLayout(buttons)

        self.sil_button.clicked.connect(self.run_sil)
        self.save_button.clicked.connect(self._save)
        self.report_button.clicked.connect(self._open_report)
        self.copy_button.clicked.connect(self._copy)
        close.clicked.connect(self.accept)

    def run_sil(self) -> None:
        self.sil_label.setText("Compiling and running…")
        QGuiApplication.processEvents()
        res = self.controller.sil_check(self.target, self.code)
        if res is None:
            self.sil_label.setText("The SIL check could not run; see the status bar.")
            return
        icon = "✓" if res.passed else "✗"
        self.sil_label.setText(f"{icon} " + res.summary().replace("\n", "   "))

    def save_to(self, folder: str | Path) -> None:
        self.controller.save(self.code, folder)
        self.saved_to = Path(folder)
        self.report_button.setEnabled(True)

    def _save(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save generated code")
        if folder:
            self.save_to(folder)
            self.sil_label.setText(f"Saved {len(self.code.files)} files to {folder}")

    def _open_report(self) -> None:
        if self.saved_to is not None:
            webbrowser.open((self.saved_to / f"{self.code.name}_report.html").as_uri())

    def _copy(self) -> None:
        edit = self.tabs.currentWidget()
        if isinstance(edit, QPlainTextEdit):
            QGuiApplication.clipboard().setText(edit.toPlainText())
