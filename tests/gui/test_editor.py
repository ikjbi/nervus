"""Tests of the GUI models and controllers (MVC), driven without real mouse input."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from nervus.blocks import Gain, Step, Sum
from nervus.gui.controllers import EditorController
from nervus.gui.models import DiagramModel


@pytest.fixture
def editor(qtbot) -> EditorController:  # type: ignore[no-untyped-def]
    return EditorController(DiagramModel())


def test_add_block_and_undo(editor: EditorController) -> None:
    added = []
    editor.model.blockAdded.connect(added.append)
    b = editor.add_block("math.gain", QPointF(10, 20), gain=3.0)
    assert b is not None and b.name == "Gain"
    assert b.meta["position"] == [10.0, 20.0]
    assert added == [b]
    editor.undo_stack.undo()
    assert len(editor.model.diagram) == 0
    editor.undo_stack.redo()
    assert editor.model.diagram.block("Gain") is b


def test_unknown_block_type_reports_error(editor: EditorController, qtbot) -> None:  # type: ignore[no-untyped-def]
    with qtbot.waitSignal(editor.errorOccurred):
        assert editor.add_block("nope.block", QPointF()) is None
    assert editor.undo_stack.count() == 0


def _two_blocks(editor: EditorController) -> tuple[Step, Gain]:
    s = editor.add_block("sources.step", QPointF(0, 0))
    g = editor.add_block("math.gain", QPointF(150, 0))
    assert isinstance(s, Step) and isinstance(g, Gain)
    return s, g


def test_connect_replace_and_undo(editor: EditorController) -> None:
    s, g = _two_blocks(editor)
    s2 = editor.add_block("sources.constant", QPointF(0, 100))
    assert s2 is not None
    assert editor.connect_ports(s, 0, g, 0)
    assert editor.model.diagram.driver(g, 0).src is s  # type: ignore[union-attr]
    # Connecting another source to the same input replaces the line.
    assert editor.connect_ports(s2, 0, g, 0)
    assert editor.model.diagram.driver(g, 0).src is s2  # type: ignore[union-attr]
    assert len(editor.model.diagram.connections) == 1
    editor.undo_stack.undo()
    assert editor.model.diagram.driver(g, 0).src is s  # type: ignore[union-attr]
    editor.undo_stack.redo()
    assert editor.model.diagram.driver(g, 0).src is s2  # type: ignore[union-attr]


def test_delete_block_restores_connections_on_undo(editor: EditorController) -> None:
    s, g = _two_blocks(editor)
    editor.connect_ports(s, 0, g, 0)
    editor.delete([g], [])
    assert g not in editor.model.diagram and not editor.model.diagram.connections
    editor.undo_stack.undo()
    assert g in editor.model.diagram
    assert editor.model.diagram.driver(g, 0).src is s  # type: ignore[union-attr]
    editor.undo_stack.redo()
    editor.undo_stack.undo()  # redo/undo repeatedly stays consistent
    assert len(editor.model.diagram.connections) == 1


def test_set_params_validation_and_undo(editor: EditorController, qtbot) -> None:  # type: ignore[no-untyped-def]
    _, g = _two_blocks(editor)
    assert editor.set_params(g, {"gain": 5.0})
    assert float(g.params["gain"]) == 5.0
    with qtbot.waitSignal(editor.errorOccurred):
        assert not editor.set_params(g, {"multiplication": "matrix"})  # needs a 2-D gain
    assert g.params["multiplication"] == "elementwise"
    editor.undo_stack.undo()
    assert float(g.params["gain"]) == 1.0


def test_fewer_ports_drops_connections_and_undo_restores(editor: EditorController) -> None:
    a = editor.add_block("sources.constant", QPointF())
    b = editor.add_block("sources.constant", QPointF(0, 100))
    s = editor.add_block("math.sum", QPointF(150, 0))
    assert a and b and isinstance(s, Sum)
    editor.connect_ports(a, 0, s, 0)
    editor.connect_ports(b, 0, s, 1)
    editor.set_params(s, {"signs": "+"})
    assert len(editor.model.diagram.connections) == 1
    editor.undo_stack.undo()
    assert len(editor.model.diagram.connections) == 2


def test_rename_rules(editor: EditorController) -> None:
    _s, g = _two_blocks(editor)
    assert editor.rename(g, "controller")
    assert not editor.rename(g, "Step")  # taken
    assert not editor.rename(g, "  ")
    editor.undo_stack.undo()
    assert g.name == "Gain"


def test_move_and_settings_undo(editor: EditorController) -> None:
    s, _ = _two_blocks(editor)
    editor.move_blocks([(s, QPointF(0, 0), QPointF(40, 50))])
    assert s.meta["position"] == [40.0, 50.0]
    from nervus.core import SimulationSettings

    assert editor.set_settings(SimulationSettings(t_final=3.0, solver="rk4"))
    assert not editor.set_settings(SimulationSettings(t_final=-1.0))
    editor.undo_stack.undo()
    assert editor.model.diagram.settings.t_final == 10.0
    editor.undo_stack.undo()
    assert s.meta["position"] == [0.0, 0.0]


def test_copy_paste(editor: EditorController) -> None:
    s, g = _two_blocks(editor)
    editor.connect_ports(s, 0, g, 0)
    text = editor.copy_to_text([s, g])
    created = editor.paste_from_text(text)
    assert [b.name for b in created] == ["Step1", "Gain1"]
    assert len(editor.model.diagram.connections) == 2
    assert created[0].meta["position"] == [30.0, 30.0]
    editor.undo_stack.undo()  # paste is one undo step
    assert len(editor.model.diagram) == 2


def test_editing_locked_while_disabled(editor: EditorController, qtbot) -> None:  # type: ignore[no-untyped-def]
    editor.set_editing_enabled(False)
    with qtbot.waitSignal(editor.errorOccurred):
        assert editor.add_block("math.gain", QPointF()) is None


def test_file_controller_roundtrip(qtbot, qsettings, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.controllers import FileController

    model = DiagramModel()
    editor = EditorController(model)
    files = FileController(model, editor, qsettings)
    editor.add_block("sources.step", QPointF(10, 10))
    assert files.is_modified
    assert files.save_as(tmp_path / "m")
    assert model.file_path == tmp_path / "m.nervus"
    assert not files.is_modified
    files.new()
    assert len(model.diagram) == 0
    assert files.open(tmp_path / "m.nervus")
    assert model.diagram.block("Step").meta["position"] == [10.0, 10.0]
    assert files.recent_files() == [(tmp_path / "m.nervus").resolve()]
    with qtbot.waitSignal(files.errorOccurred):
        assert not files.open(tmp_path / "missing.nervus")


def test_datatype_labels_and_param(qtbot, qsettings) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.theme import ThemeManager
    from nervus.gui.views.main_window import MainWindow

    ThemeManager.instance().apply()
    w = MainWindow(qsettings)
    try:
        ed = w.editor
        c = ed.add_block("sources.constant", QPointF(0, 0), value=3.7)
        dtc = ed.add_block("routing.datatype_conversion", QPointF(150, 0), output_type="int8")
        g = ed.add_block("math.gain", QPointF(300, 0))
        ed.connect_ports(c, 0, dtc, 0)
        ed.connect_ports(dtc, 0, g, 0)
        ed.connect_ports(g, 0, ed.add_block("sinks.scope", QPointF(450, 0)), 0)
        w.act_types.setChecked(True)
        w.refresh_types()
        labels = sorted(wire.type_label for wire in w.scene.wires.values())
        assert labels == ["", "int8", "int8"]  # constant is double; conversion and gain carry int8
        assert ed.set_params(g, {"output_type": "fixdt(1, 16, 8)"})
        assert not ed.set_params(g, {"output_type": "int7"})
    finally:
        w.editor.undo_stack.setClean()
        w.close()
