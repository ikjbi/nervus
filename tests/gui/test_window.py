"""Tests of the assembled main window: canvas items follow the model, simulations run in a thread."""

from pathlib import Path

from PySide6.QtCore import QPointF

from nervus.gui.models import SimulationState
from nervus.gui.views.items import BlockItem, WireItem

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


def test_open_example_builds_scene(window) -> None:  # type: ignore[no-untyped-def]
    assert window.files.open(EXAMPLES / "throttle_pi.nervus")
    d = window.diagram_model.diagram
    assert len(window.scene.blocks) == len(d)
    assert len(window.scene.wires) == len(d.connections)
    assert all(isinstance(i, BlockItem) for i in window.scene.blocks.values())
    assert "throttle_pi.nervus" in window.windowTitle()


def test_scene_follows_undo(window) -> None:  # type: ignore[no-untyped-def]
    s = window.editor.add_block("sources.step", QPointF(0, 0))
    g = window.editor.add_block("math.gain", QPointF(200, 0))
    window.editor.connect_ports(s, 0, g, 0)
    assert len(window.scene.wires) == 1
    wire = next(iter(window.scene.wires.values()))
    assert isinstance(wire, WireItem)
    window.scene.select_blocks(["Gain"])
    window.delete_selection()
    assert len(window.scene.blocks) == 1 and not window.scene.wires
    window.editor.undo_stack.undo()
    assert len(window.scene.blocks) == 2 and len(window.scene.wires) == 1
    assert window.isWindowModified()


def test_property_panel_shows_selection(window) -> None:  # type: ignore[no-untyped-def]
    window.editor.add_block("math.gain", QPointF())
    window.scene.select_blocks(["Gain"])
    assert window.properties.block is not None
    assert window.properties.title.text() == "Gain"
    assert "gain" in window.properties._editors


def test_run_simulation_and_scope(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "mass_spring_damper_pid.nervus")
    with qtbot.waitSignal(
        window.sim_model.stateChanged, timeout=20000, check_params_cb=lambda s: s is SimulationState.FINISHED
    ):
        assert window.simulation.run()
    assert window.editor.editing_enabled
    res = window.sim_model.result
    assert res is not None and abs(res["position"][-1] - 1.0) < 1e-3
    assert window.scopes, "scopes open after the first run"
    scope = next(iter(window.scopes.values()))
    assert len(scope._series) == 3


def test_compile_error_goes_to_diagnostics(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.editor.add_block("math.gain", QPointF())
    assert not window.simulation.run()
    assert window.sim_model.state is SimulationState.FAILED
    qtbot.wait(300)  # diagnostics refresh is debounced
    errors, _ = window.diagnostics.counts()
    assert errors >= 1
    assert window.scene.blocks[id(window.diagram_model.diagram.block("Gain"))].error


def test_help_browser_has_every_block(window) -> None:  # type: ignore[no-untyped-def]
    from nervus.blocks import block_types

    window.show_help_for_type("math.gain")
    help_ = window._help
    assert help_ is not None
    for type_id in block_types():
        assert f"block:{type_id}" in help_._pages
    assert "Gain" in help_.text.toPlainText()
