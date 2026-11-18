"""Workspace editing in the GUI: variables, expressions in block parameters, parameter sets, undo."""

from PySide6.QtCore import QPointF


def test_workspace_variable_drives_block(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    var = ed.add_variable("Kp", 2.0)
    assert var is not None
    g = ed.add_block("math.gain", QPointF())
    assert ed.set_params(g, {"gain": "Kp"})
    assert g.expressions == {"gain": "Kp"} and float(g.params["gain"]) == 2.0
    assert ed.update_variable("Kp", value=5.0)
    assert float(g.params["gain"]) == 5.0  # re-resolved when the workspace changes
    ed.undo_stack.undo()
    assert float(g.params["gain"]) == 2.0
    assert window.workspace_panel.table.rowCount() == 1
    assert window.workspace_panel.table.item(0, 1).text() == "2.0"


def test_unknown_variable_rejected(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    g = window.editor.add_block("math.gain", QPointF())
    with qtbot.waitSignal(window.editor.errorOccurred):
        assert not window.editor.set_params(g, {"gain": "nope"})
    assert g.expressions == {}


def test_cannot_delete_used_variable(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    ed.add_variable("Kp", 1.0)
    g = ed.add_block("math.gain", QPointF())
    ed.set_params(g, {"gain": "Kp"})
    with qtbot.waitSignal(ed.errorOccurred):
        assert not ed.delete_variable("Kp")
    ed.set_params(g, {"gain": 1.0})
    assert ed.delete_variable("Kp")
    ed.undo_stack.undo()
    assert "Kp" in window.diagram_model.diagram.workspace


def test_rename_and_expression_variable(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    ed.add_variable("a", 2.0)
    ed.add_variable("b", "2*a")
    assert window.diagram_model.diagram.workspace["b"] == 4.0
    assert not ed.update_variable("a", value="b")  # forward reference -> rejected
    assert ed.update_variable("b", name="b2")
    assert list(window.diagram_model.diagram.workspace) == ["a", "b2"]
    ed.undo_stack.undo()
    assert list(window.diagram_model.diagram.workspace) == ["a", "b"]


def test_parameter_set_roundtrip(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    ed.add_variable("Kp", 1.0)
    ed.add_variable("Ki", 3.0)
    path = ed.save_parameter_set(tmp_path / "base")
    assert path is not None
    ed.update_variable("Kp", value=9.0)
    assert ed.load_parameter_set(path)
    assert window.diagram_model.diagram.workspace["Kp"] == 1.0
    ed.undo_stack.undo()
    assert window.diagram_model.diagram.workspace["Kp"] == 9.0


def test_property_panel_shows_expression(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    ed.add_variable("Kp", 1.0)
    g = ed.add_block("math.gain", QPointF())
    ed.set_params(g, {"gain": "Kp*2"})
    window.scene.select_blocks([g.name])
    assert window.properties._editors["gain"].text() == "Kp*2"
