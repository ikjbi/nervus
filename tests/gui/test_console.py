"""The scripting console."""

from nervus import Diagram, simulate
from nervus.blocks import Gain, Scope, Step


def test_console_reads_and_edits_the_model(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("m")
    s = d.add(Step(), name="u")
    g = d.add(Gain(gain=2.0), name="k")
    d.chain(s, g, d.add(Scope(), name="sc"))
    window.diagram_model.set_diagram(d)
    con = window.console
    con.run("print(len(model.blocks), model.block('k').params['gain'])")
    assert "3 2.0" in con.output.toPlainText()
    # A multi-line statement.
    assert con.run("for b in model.blocks:")
    assert con.run("    pass")
    assert not con.run("")
    # An edit: one undo step, and the editor shows the new block.
    con.run("model.add(Gain(gain=5.0), name='extra')")
    assert "extra" in window.diagram_model.root
    assert window.editor.undo_stack.undoText().startswith("Script:")
    window.editor.undo_stack.undo()
    assert "extra" not in window.diagram_model.root
    assert window.console.namespace["model"] is window.diagram_model.root  # follows the restored model
    window.editor.undo_stack.redo()
    assert "extra" in window.diagram_model.root
    # Errors are shown, not raised.
    con.run("1/0")
    assert "ZeroDivisionError" in con.output.toPlainText()
    con.run("def (")
    assert "SyntaxError" in con.output.toPlainText()
    # Results of the last run.
    other = Diagram("other")
    other.chain(other.add(Step(), name="u"), other.add(Gain(gain=2.0), name="k"), other.add(Scope()))
    window.sim_model.add_run(simulate(other, 1.0), "run 1")
    con.run("print(res['k'][-1])")
    assert con.output.toPlainText().rstrip().endswith("2.0")


def test_history(window) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    con = window.console
    for line in ("a = 1", "b = 2"):
        con.input.setText(line)
        con._enter()
    assert con.namespace["b"] == 2
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    con.input.keyPressEvent(up)
    assert con.input.text() == "b = 2"
    con.input.keyPressEvent(up)
    assert con.input.text() == "a = 1"


def test_settings_dialog_algebraic_loops(qtbot) -> None:  # type: ignore[no-untyped-def]
    from nervus import SimulationSettings
    from nervus.gui.views.settings_dialog import SettingsDialog

    dlg = SettingsDialog(SimulationSettings(algebraic_loops="solve"))
    qtbot.addWidget(dlg)
    assert dlg.loops.currentData() == "solve"
    dlg.loops.setCurrentIndex(0)
    dlg._accept()
    assert dlg.result_settings.algebraic_loops == "error"
