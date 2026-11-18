"""Light and dark themes.

Colours are defined once as tokens and used by the stylesheet, the canvas and the scope plots.
Plot series colours use a categorical palette validated for colour-vision deficiency; they are assigned
in a fixed order and never cycled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class ThemeMode(Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    panel: str
    panel_alt: str
    border: str
    text: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_text: str
    canvas: str
    grid: str
    block_fill: str
    block_border: str
    block_text: str
    port: str
    wire: str
    selection: str
    error: str
    warning: str
    plot_surface: str
    plot_grid: str
    series: tuple[str, ...]

    def color(self, token: str) -> QColor:
        return QColor(getattr(self, token))


LIGHT = Theme(
    name="light",
    window="#f3f3f1",
    panel="#fbfbfa",
    panel_alt="#efefec",
    border="#dcdbd5",
    text="#1d1d1b",
    text_secondary="#52514e",
    text_muted="#86857f",
    accent="#2a78d6",
    accent_text="#ffffff",
    canvas="#fcfcfb",
    grid="#e3e2dc",
    block_fill="#ffffff",
    block_border="#9c9b94",
    block_text="#1d1d1b",
    port="#6b6a64",
    wire="#4b4a46",
    selection="#2a78d6",
    error="#d03b3b",
    warning="#b97800",
    plot_surface="#fcfcfb",
    plot_grid="#e1e0d9",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
)

DARK = Theme(
    name="dark",
    window="#161615",
    panel="#1f1f1e",
    panel_alt="#262625",
    border="#353532",
    text="#f2f2ef",
    text_secondary="#c3c2b7",
    text_muted="#8d8c85",
    accent="#3987e5",
    accent_text="#ffffff",
    canvas="#1a1a19",
    grid="#2a2a28",
    block_fill="#262625",
    block_border="#6c6b65",
    block_text="#f2f2ef",
    port="#a3a29b",
    wire="#bdbcb4",
    selection="#3987e5",
    error="#e66767",
    warning="#d9a020",
    plot_surface="#1a1a19",
    plot_grid="#2c2c2a",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
)


def _stylesheet(t: Theme) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {t.window}; }}
    QWidget {{ color: {t.text}; font-size: 13px; }}
    QDockWidget {{ titlebar-close-icon: none; }}
    QDockWidget::title {{
        background: {t.window}; padding: 6px 8px; color: {t.text_secondary};
        font-weight: 600; text-transform: uppercase; font-size: 11px;
    }}
    #panel, QTreeWidget, QListWidget, QTextBrowser, QPlainTextEdit, QScrollArea {{
        background: {t.panel}; border: 1px solid {t.border}; border-radius: 6px;
    }}
    QScrollArea > QWidget > QWidget {{ background: {t.panel}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t.panel}; border: 1px solid {t.border}; border-radius: 5px; padding: 4px 6px;
        selection-background-color: {t.accent};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {t.accent}; }}
    QLineEdit[invalid="true"] {{ border: 1px solid {t.error}; }}
    QPushButton {{
        background: {t.panel}; border: 1px solid {t.border}; border-radius: 5px; padding: 5px 12px;
    }}
    QPushButton:hover {{ background: {t.panel_alt}; }}
    QPushButton:default, QPushButton#primary {{
        background: {t.accent}; color: {t.accent_text}; border: 1px solid {t.accent};
    }}
    QToolBar {{ background: {t.window}; border: none; spacing: 4px; padding: 4px; }}
    QToolButton {{ border: none; border-radius: 5px; padding: 4px; }}
    QToolButton:hover {{ background: {t.panel_alt}; }}
    QToolButton:checked {{ background: {t.panel_alt}; }}
    QStatusBar {{ background: {t.window}; color: {t.text_secondary}; }}
    QTreeWidget::item, QListWidget::item {{ padding: 3px; }}
    QTreeWidget::item:selected, QListWidget::item:selected {{
        background: {t.accent}; color: {t.accent_text}; border-radius: 4px;
    }}
    QHeaderView::section {{ background: {t.panel_alt}; border: none; padding: 4px; }}
    QProgressBar {{
        border: 1px solid {t.border}; border-radius: 4px; background: {t.panel}; height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
    QMenu {{ background: {t.panel}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QLabel#heading {{ font-size: 15px; font-weight: 600; }}
    QLabel#muted {{ color: {t.text_muted}; }}
    QLabel#error {{ color: {t.error}; }}
    QSplitter::handle {{ background: {t.window}; }}
    """


def _palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.panel,
        QPalette.ColorRole.AlternateBase: t.panel_alt,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.panel,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.panel,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.text_muted,
        QPalette.ColorRole.Link: t.accent,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.text_muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.text_muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.text_muted))
    return p


class ThemeManager(QObject):
    """Holds the active theme and re-applies it when the mode or the system colour scheme changes."""

    themeChanged = Signal(object)  # Theme

    _instance: ThemeManager | None = None

    def __init__(self) -> None:
        super().__init__()
        self._mode = ThemeMode.SYSTEM
        self._theme = LIGHT
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(lambda _scheme: self.apply())

    @classmethod
    def instance(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    def set_mode(self, mode: ThemeMode) -> None:
        self._mode = mode
        self.apply()

    def _resolve(self) -> Theme:
        if self._mode is ThemeMode.LIGHT:
            return LIGHT
        if self._mode is ThemeMode.DARK:
            return DARK
        scheme = QGuiApplication.styleHints().colorScheme()
        return DARK if scheme == Qt.ColorScheme.Dark else LIGHT

    def apply(self) -> None:
        self._theme = self._resolve()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setPalette(_palette(self._theme))
            app.setStyleSheet(_stylesheet(self._theme))
        self.themeChanged.emit(self._theme)


def current_theme() -> Theme:
    return ThemeManager.instance().theme
