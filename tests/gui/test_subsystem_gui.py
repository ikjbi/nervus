"""Subsystems in the editor: navigation, Create Subsystem from Selection, undo across levels."""

from PySide6.QtCore import QPointF

from nervus.blocks import Subsystem
from nervus.gui.models import SimulationState


def _chain(window):  # type: ignore[no-untyped-def]
    ed = window.editor
    s = ed.add_block("sources.step", QPointF(0, 0), time=0.0)
    g = ed.add_block("math.gain", QPointF(150, 0), gain=2.0)
    i = ed.add_block("continuous.integrator", QPointF(300, 0))
    sc = ed.add_block("sinks.scope", QPointF(450, 0))
    ed.connect_ports(s, 0, g, 0)
    ed.connect_ports(g, 0, i, 0)
    ed.connect_ports(i, 0, sc, 0)
    return s, g, i, sc


def test_create_subsystem_from_selection(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    _s, g, i, _sc = _chain(window)
    root = window.diagram_model.root
    sub = window.editor.create_subsystem([g, i])
    assert isinstance(sub, Subsystem)
    assert [b.name for b in root.blocks] == ["Step", "Scope", "Subsystem"]
    assert sub.num_inputs() == 1 and sub.num_outputs() == 1
    assert {b.name for b in sub.system.blocks} == {"Gain", "Integrator", "In1", "Out1"}
    assert not root.check() or all(x.severity.value == "warning" for x in root.check())
    # It still simulates the same: y = 2t
    with qtbot.waitSignal(
        window.sim_model.stateChanged, timeout=20000, check_params_cb=lambda st: st is SimulationState.FINISHED
    ):
        window.simulation.run()
    res = window.sim_model.result
    assert abs(res["Subsystem/Integrator"][-1] - 2 * res.t[-1]) < 1e-6
    # Undo restores the flat diagram with all connections
    window.editor.undo_stack.undo()
    assert {b.name for b in root.blocks} == {"Step", "Gain", "Integrator", "Scope"}
    assert len(root.connections) == 3
    window.editor.undo_stack.redo()
    assert root.block("Subsystem") is sub and len(root.connections) == 2


def test_navigation_and_breadcrumbs(window) -> None:  # type: ignore[no-untyped-def]
    _s, g, i, _sc = _chain(window)
    sub = window.editor.create_subsystem([g, i])
    model = window.diagram_model
    window.scene.blockActivated.emit(sub)  # double-click
    assert model.diagram is sub.system
    assert [label for label, _ in model.breadcrumbs()][-1] == "Subsystem"
    assert {item.block.name for item in window.scene.blocks.values()} == {"Gain", "Integrator", "In1", "Out1"}
    # Adding a block inside, then going up and undoing, navigates back into the subsystem.
    window.editor.add_block("math.abs", QPointF(0, 200))
    model.up()
    assert model.diagram is model.root
    window.editor.undo_stack.undo()
    assert model.diagram is sub.system
    assert "Abs" not in sub.system


def test_diagnostics_paths_open_subsystem(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    _s, g, i, _sc = _chain(window)
    sub = window.editor.create_subsystem([g, i])
    window.diagram_model.enter(sub)
    window.editor.add_block("math.abs", QPointF(0, 200))
    window.diagram_model.up()
    qtbot.wait(350)
    errors, _ = window.diagnostics.counts()
    assert errors == 1
    window._highlight(("Subsystem/Abs",))
    assert window.diagram_model.diagram is sub.system
    assert [b.name for b in window.scene.selected_blocks()] == ["Abs"]


def test_save_and_reopen_subsystem(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _s, g, i, _sc = _chain(window)
    window.editor.create_subsystem([g, i])
    assert window.files.save_as(tmp_path / "m")
    window.files.new()
    assert window.files.open(tmp_path / "m.nervus")
    sub = window.diagram_model.root.block("Subsystem")
    assert isinstance(sub, Subsystem) and len(sub.system) == 4
