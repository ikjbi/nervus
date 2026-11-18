"""Render screenshots of the editor for the documentation (docs/images/).

Run: QT_QPA_PLATFORM=offscreen uv run python scripts/screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "images"


def grab(widget: QWidget, name: str) -> None:
    QApplication.processEvents()
    widget.grab().save(str(OUT / name))
    print("wrote", OUT / name)


def main() -> None:
    from nervus.gui.qtfix import unhide_qt_plugins

    unhide_qt_plugins()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from nervus.gui.theme import ThemeManager, ThemeMode

    OUT.mkdir(parents=True, exist_ok=True)
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        ThemeManager.instance().set_mode(mode)
        from nervus.gui.views.main_window import MainWindow

        settings = QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat)
        win = MainWindow(settings)
        win.resize(1400, 860)
        win.show()
        win.files.open(ROOT / "examples" / "throttle_pi.nervus")
        win.view.fit()
        win.scene.select_blocks(["throttle_pi"])
        suffix = "" if mode is ThemeMode.LIGHT else "-dark"
        grab(win, f"editor{suffix}.png")
        if mode is ThemeMode.LIGHT:
            win.workspace_dock.raise_()
            win.resizeDocks([win.workspace_dock], [210], Qt.Orientation.Vertical)
            grab(win, "workspace.png")
            grab(win.workspace_panel, "workspace-panel.png")
            win.diagnostics_dock.raise_()

        win.simulation.run()
        win.simulation.wait()
        for _ in range(20):
            QApplication.processEvents()
        scope = next(iter(win.scopes.values()))
        scope.resize(900, 520)
        grab(scope, f"scope{suffix}.png")

        if mode is ThemeMode.LIGHT:
            # Subsystems: group the ECU part of the throttle model.
            root = win.diagram_model.root
            ecu = win.editor.create_subsystem([root.block(n) for n in ("tps_sample", "error", "throttle_pi")])
            assert ecu is not None
            win.editor.rename(ecu, "ECU")
            win.editor.auto_layout()
            win.view.fit()
            win.scene.select_blocks(["ECU"])
            grab(win, "subsystem-outer.png")
            win.diagram_model.enter(ecu)
            win.editor.auto_layout()
            win.view.fit()
            grab(win, "subsystem-inner.png")
            win.diagram_model.up()
            for _ in range(4):
                win.editor.undo_stack.undo()
            win.show_help_for_type("control.discrete_pid")
            assert win._help is not None
            grab(win._help, "help.png")
            win.show_help_for_type("math.gain")
            win._help.resize(980, 720)
            grab(win._help, "help-gain.png")
            dlg_mod = __import__("nervus.gui.views.settings_dialog", fromlist=["SettingsDialog"])
            dlg = dlg_mod.SettingsDialog(win.diagram_model.diagram.settings, win)
            dlg.show()
            grab(dlg, "settings.png")
            dlg.close()
        win.files.editor.undo_stack.setClean()
        for w in list(win.scopes.values()):
            w.close()
        win.close()


if __name__ == "__main__":
    main()
