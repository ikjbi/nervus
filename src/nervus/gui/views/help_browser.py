"""In-app help: user guide pages and the block reference."""

from __future__ import annotations

from importlib import resources
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QWidget

from nervus.blocks import categories
from nervus.gui.theme import ThemeManager, current_theme
from nervus.gui.views.math_render import markdown_with_math
from nervus.help import admonitions_to_quotes, block_help_markdown

FIGURE_WIDTH = 680  # px; figures are rendered at 2x for sharp display


class HelpText(QTextBrowser):
    """A text browser that serves typeset equations (``math:<id>``) and block figures (``figures/<name>``)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.images: dict[str, QImage] = {}

    def loadResource(self, type_: int, url: QUrl | str) -> Any:
        key = url.toString() if isinstance(url, QUrl) else url
        if key in self.images:
            return self.images[key]
        if "figures/" in key:
            name = key.rsplit("figures/", 1)[1]
            path = resources.files("nervus.gui.resources.figures").joinpath(name)
            if path.is_file():
                img = QImage.fromData(path.read_bytes())
                if img.width() > 2 * FIGURE_WIDTH:
                    img = img.scaledToWidth(2 * FIGURE_WIDTH, Qt.TransformationMode.SmoothTransformation)
                img.setDevicePixelRatio(2.0)
                return img
        return super().loadResource(type_, url)

    def show_markdown(self, markdown: str) -> None:
        md = markdown_with_math(admonitions_to_quotes(markdown), self.images, current_theme().text)
        self.setMarkdown(md)


def _tutorial_pages() -> list[tuple[str, str]]:
    from nervus.tutorials import ordered

    return [("tutorials", "Tutorials: where to start"), *[(t.help_page, f"Tutorial: {t.title}") for t in ordered()]]


_TUTORIAL_PAGES = _tutorial_pages()

HELP_PAGES = [
    ("getting_started", "Getting started"),
    ("concepts", "Concepts"),
    ("editor", "Using the editor"),
    ("simulation", "Running simulations"),
    ("workspace", "Workspace and calibrations"),
    ("subsystems", "Subsystems"),
    ("libraries", "Component libraries"),
    ("datatypes", "Data types and fixed point"),
    ("statecharts", "State machines"),
    ("physical", "Physical modelling"),
    ("can", "CAN communication"),
    ("obd", "OBD-II live data"),
    ("analysis", "Linear analysis"),
    ("codegen", "C code generation"),
    ("testing", "Test cases and the Data Inspector"),
    ("verification", "Coverage, requirements, Model Advisor"),
    *_TUTORIAL_PAGES,
    ("coming_from_simulink", "Coming from Simulink"),
    ("model_files", "Model files"),
    ("shortcuts", "Keyboard shortcuts"),
]


def help_page(name: str) -> str:
    return resources.files("nervus.gui.resources.help").joinpath(f"{name}.md").read_text(encoding="utf-8")


class HelpBrowser(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Nervus Help")
        self.resize(900, 640)
        self.index = QListWidget()
        self.index.setMaximumWidth(260)
        self.text = HelpText()
        self.text.setOpenExternalLinks(True)
        splitter = QSplitter()
        splitter.addWidget(self.index)
        splitter.addWidget(self.text)
        splitter.setStretchFactor(1, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)

        self._pages: dict[str, str] = {}
        self._rows: dict[str, int] = {}
        self._add_heading("Guide")
        for key, title in HELP_PAGES:
            self._add(f"page:{key}", title, help_page(key))
        self._add_heading("Block reference")
        for _cat, classes in sorted(categories().items()):
            for cls in sorted(classes, key=lambda c: c.label):
                self._add(f"block:{cls.type_id}", f"   {cls.label}", block_help_markdown(cls, heading_level=1))
        self._current = ""
        self.index.currentItemChanged.connect(self._show)
        ThemeManager.instance().themeChanged.connect(self._on_theme)
        self.show_page("page:getting_started")

    def _on_theme(self, _theme: object) -> None:
        if self._current:  # equations are rendered in the theme's text colour
            self.text.show_markdown(self._pages[self._current])

    def _add_heading(self, text: str) -> None:
        item = QListWidgetItem(text.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        f = item.font()
        f.setBold(True)
        item.setFont(f)
        self.index.addItem(item)

    def _add(self, key: str, title: str, markdown: str) -> None:
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, key)
        self.index.addItem(item)
        self._pages[key] = markdown
        self._rows[key] = self.index.count() - 1

    def _show(self, item: QListWidgetItem | None, _prev: QListWidgetItem | None = None) -> None:
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key in self._pages:
            self._current = key
            self.text.show_markdown(self._pages[key])

    def show_page(self, key: str) -> None:
        if key in self._rows:
            self.index.setCurrentRow(self._rows[key])

    def show_block(self, type_id: str) -> None:
        self.show_page(f"block:{type_id}")
