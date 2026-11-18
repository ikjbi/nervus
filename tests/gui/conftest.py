import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QSettings

from nervus.gui.qtfix import unhide_qt_plugins

unhide_qt_plugins()  # before pytest-qt creates the QApplication


@pytest.fixture
def qsettings() -> QSettings:
    return QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat)


@pytest.fixture
def window(qtbot, qsettings):  # type: ignore[no-untyped-def]
    from nervus.gui.theme import ThemeManager
    from nervus.gui.views.main_window import MainWindow

    ThemeManager.instance().apply()
    w = MainWindow(qsettings)
    w.show()
    qtbot.waitExposed(w)
    yield w
    # Close it ourselves (not via qtbot.addWidget) so the "save changes?" prompt never appears.
    w.editor.undo_stack.setClean()
    w.simulation.stop()
    w.simulation.wait()
    w.close()
    w.deleteLater()


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    """Delete all Qt windows before Python shuts down (avoids PySide6 teardown crashes)."""
    import gc

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        for w in QApplication.topLevelWidgets():
            w.close()
            w.deleteLater()
        app.processEvents()
    gc.collect()
