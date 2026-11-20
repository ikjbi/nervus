"""Subsystems in the editor: navigation, Create Subsystem from Selection, undo across levels."""

import itertools

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


def test_mask_editing_with_undo(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0), value=1.0)
    g = ed.add_block("math.gain", QPointF(150, 0))
    sc = ed.add_block("sinks.scope", QPointF(300, 0))
    ed.connect_ports(c, 0, g, 0)
    ed.connect_ports(g, 0, sc, 0)
    sub = ed.create_subsystem([g])
    assert ed.set_mask(sub, [{"name": "K", "value": 4.0, "unit": "-", "description": "gain"}], "×K", "scales")
    window.diagram_model.enter(sub)
    assert ed.set_params(g, {"gain": "K"})  # validated against the mask's namespace
    window.diagram_model.up()
    window.scene.select_blocks([sub.name])
    assert "mask:K" in window.properties._editors
    assert ed.set_mask_value(sub, "K", 7.0)
    assert float(g.params["gain"]) == 7.0
    ed.undo_stack.undo()
    assert float(g.params["gain"]) == 4.0
    assert not ed.set_mask(sub, [{"name": "K", "value": "undefined_thing"}], "", "")


def test_variants_editing_with_undo(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0), value=1.0)
    g = ed.add_block("math.gain", QPointF(150, 0), gain=2.0)
    sc = ed.add_block("sinks.scope", QPointF(300, 0))
    ed.connect_ports(c, 0, g, 0)
    ed.connect_ports(g, 0, sc, 0)
    sub = ed.create_subsystem([g])
    original = sub.system
    assert ed.set_variants(sub, [(None, "petrol", ""), (None, "diesel", "")], "petrol")
    assert list(sub.variants) == ["petrol", "diesel"]
    diesel = sub.variants["diesel"].system
    assert diesel is not original
    window.scene.select_blocks([sub.name])
    assert "variant" in window.properties._editors
    window.diagram_model.enter(sub)
    assert ed.activate_variant(sub, "diesel")
    assert sub.system is diesel and window.diagram_model.diagram is not original  # left the inactive variant
    ed.undo_stack.undo()
    assert sub.active_variant == "petrol"
    ed.undo_stack.undo()
    assert not sub.variants and sub.system is original
    assert not ed.set_variants(sub, [(None, "a", ""), (None, "a", "")], "a")
    window.diagram_model.root.workspace["ENGINE"] = 2
    assert ed.set_variants(sub, [(None, "petrol", "ENGINE == 1"), (None, "diesel", "ENGINE == 2")], "petrol")
    assert sub.active_variant == "diesel"  # chosen by the condition


def test_component_library_workflow(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.controllers.editor_controller import LIBRARY_PREFIX

    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0), value=1.0)
    g = ed.add_block("math.gain", QPointF(150, 0), gain=3.0)
    sc = ed.add_block("sinks.scope", QPointF(300, 0))
    ed.connect_ports(c, 0, g, 0)
    ed.connect_ports(g, 0, sc, 0)
    sub = ed.create_subsystem([g])
    lib = tmp_path / "parts.nervlib"
    assert ed.save_to_library(sub, lib)
    assert sub.library_link is not None and sub.library_link.component == sub.name
    # Editing inside a linked subsystem is refused.
    window.diagram_model.enter(sub)
    assert ed.add_block("math.gain", QPointF(0, 100)) is None
    window.diagram_model.up()
    # The library shows up in the panel; adding a component creates a linked copy.
    window.library.add_library(lib)
    assert window.library.reload_libraries() is None
    copy = ed.add_block(f"{LIBRARY_PREFIX}{lib}|{sub.name}", QPointF(0, 200))
    assert copy is not None and copy.library_link is not None
    assert ed.break_link(copy) and copy.library_link is None
    window.diagram_model.enter(copy)
    assert ed.add_block("math.gain", QPointF(0, 100)) is not None  # editable after breaking the link
    window.diagram_model.up()
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert copy.library_link is not None
    window.library.remove_library(lib.resolve())


def test_context_menus(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0))
    g = ed.add_block("math.gain", QPointF(150, 0))
    ed.connect_ports(c, 0, g, 0)
    sub = ed.create_subsystem([g])
    texts = lambda menu: [a.text() for a in menu.actions() if a.text()]  # noqa: E731
    window.scene.select_blocks([sub.name])
    sub_menu = texts(window.context_menu(sub))
    assert "Open Subsystem" in sub_menu and "Edit Mask…" in sub_menu and "Variants…" in sub_menu
    window.scene.select_blocks([c.name])
    assert "Rename…" in texts(window.context_menu(c))
    wire = window.diagram_model.diagram.connections[0]
    menu = window.context_menu(wire)
    assert texts(menu) == ["Name Signal…", "Delete Wire"]
    menu.actions()[1].trigger()  # Delete Wire
    assert not window.diagram_model.diagram.connections
    assert any("Layout" in t for t in texts(window.context_menu(None)))


def test_flip_blocks(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0))
    g = ed.add_block("math.gain", QPointF(300, 0))
    ed.connect_ports(c, 0, g, 0)
    item = window.scene._item(g)
    left_in = item.in_ports[0].scene_anchor().x()
    assert ed.flip_blocks([g])
    assert g.meta["flipped"] is True
    item = window.scene._item(g)
    assert item.in_ports[0].scene_anchor().x() > left_in + item.size[0] - 1  # the input moved to the right side
    wire = next(iter(window.scene.wires.values()))
    assert wire.path().elementCount() >= 3  # routed around to the right side
    ed.undo_stack.undo()
    assert "flipped" not in g.meta
    from nervus.io import dumps, loads

    ed.undo_stack.redo()
    assert loads(dumps(window.diagram_model.root)).block(g.name).meta["flipped"] is True


def test_rotate_blocks(window) -> None:  # type: ignore[no-untyped-def]
    from nervus.core.layout import orientation_of
    from nervus.io import dumps, loads

    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0))
    g = ed.add_block("math.gain", QPointF(0, 200))
    ed.connect_ports(c, 0, g, 0)
    seen = []
    for _ in range(4):
        assert ed.rotate_blocks([g])
        seen.append(orientation_of(g))
    assert seen == ["down", "left", "up", "right"]  # clockwise, back to the start
    assert "vertical" not in g.meta and "flipped" not in g.meta
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert orientation_of(g) == "down"
    item = window.scene._item(g)
    body = item.mapRectToScene(item.body_rect())
    inp, out = item.in_ports[0].scene_anchor(), item.out_ports[0].scene_anchor()
    assert inp.y() < body.top() and out.y() > body.bottom()  # input on top, output below
    wire = next(iter(window.scene.wires.values()))
    end = wire.path().elementAt(wire.path().elementCount() - 1)
    before = wire.path().elementAt(wire.path().elementCount() - 2)
    assert abs(before.x - end.x) < 1e-9 and before.y < end.y  # the wire comes down into the top port
    assert ed.flip_blocks([g])
    assert orientation_of(g) == "up"
    assert orientation_of(loads(dumps(window.diagram_model.root)).block(g.name)) == "up"  # saved


def test_resize_and_nudge(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    ed = window.editor
    g = ed.add_block("math.gain", QPointF(0, 0))
    item = window.scene._item(g)
    w0, h0 = item.size
    assert ed.resize_block(g, None, [200.0, 100.0])
    assert window.scene._item(g).size == (200.0, 100.0)
    assert ed.resize_block(g, [200.0, 100.0], [10.0, 10.0])
    assert window.scene._item(g).size == (w0, h0)  # never smaller than the natural size
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert "size" not in g.meta and window.scene._item(g).size == (w0, h0)
    window.scene._item(g).setSelected(True)
    window.view.setFocus()
    qtbot.keyClick(window.view.viewport(), Qt.Key.Key_Right)
    qtbot.keyClick(window.view.viewport(), Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert g.meta["position"] == [10.0, 50.0]
    ed.undo_stack.undo()
    assert g.meta["position"] == [10.0, 0.0]


def test_vertical_routes() -> None:
    from nervus.gui.views.items import route

    def corners(path):  # type: ignore[no-untyped-def]
        return [(round(path.elementAt(k).x), round(path.elementAt(k).y)) for k in range(path.elementCount())]

    # Down out of one block and down into a block below it: a Z with horizontal middle segment.
    pts = corners(route(QPointF(0, 0), QPointF(100, 200), (0, 1), (0, 1)))
    assert pts[0] == (0, 0) and pts[-1] == (100, 200)
    assert all(a[0] == b[0] or a[1] == b[1] for a, b in itertools.pairwise(pts))  # orthogonal
    assert pts[1][0] == 0 and pts[-2][0] == 100  # leaves downwards, arrives from above
    # Right out of a block and down into a rotated block: one corner.
    assert corners(route(QPointF(0, 0), QPointF(100, 100), (1, 0), (0, 1))) == [(0, 0), (100, 0), (100, 100)]
    # The old horizontal routes are unchanged.
    assert corners(route(QPointF(0, 0), QPointF(100, 50), 1, 1)) == [(0, 0), (50, 0), (50, 50), (100, 50)]


def test_shortcuts_are_unique(window) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QAction

    seen: dict[str, str] = {}
    for action in window.findChildren(QAction):
        for seq in action.shortcuts():
            key = seq.toString()
            if key:
                assert key not in seen or seen[key] == action.text(), f"{key}: {seen.get(key)} and {action.text()}"
                seen[key] = action.text()
