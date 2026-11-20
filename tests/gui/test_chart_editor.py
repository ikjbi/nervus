"""The graphical chart editor."""

from pathlib import Path

from nervus.blocks.chart import parse_chart

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


def _open(window, model: str, block: str):  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / model)
    b = next(x for _path, x in window.diagram_model.root.walk() if x.name == block)
    return b, window.open_chart_editor(b)


def test_editor_shows_the_chart(window) -> None:  # type: ignore[no-untyped-def]
    block, ed = _open(window, "gear_shift.nervus", "shift_logic")
    spec = parse_chart(str(block.params["definition"]))
    assert set(ed.state_items) == {s.name for s in spec.states}
    assert len(ed.transition_items) == len(spec.transitions)
    assert len(ed.markers) == 1 and ed.markers[0].target.name == spec.states[spec.initial].name
    assert ed.ok_button.isEnabled()
    ed.close()


def test_double_click_opens_the_editor(window) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "charging_system.nervus")
    window._block_activated(window.diagram_model.root.block("energy_management"))
    assert any(type(w).__name__ == "ChartEditor" for w in window.findChildren(object))


def test_edit_apply_and_undo(window) -> None:  # type: ignore[no-untyped-def]
    block, ed = _open(window, "charging_system.nervus", "energy_management")
    before = str(block.params["definition"])
    # A new state with an entry action, reached from 'normal' when the battery is nearly empty.
    ed.state_items["normal"].setSelected(True)
    name = ed.add_state()
    ed.state_name.setText("limp")
    ed._rename()
    ed.state_fields["entry"].setPlainText("idle_rpm = idle_boost; shed = 1")
    ed.scene.clearSelection()
    ed.state_items["normal"].setSelected(True)
    ed.start_transition()
    assert ed.scene.picking
    ed._picked("limp")
    ed.tr_guard.setText("i_bat < -50")
    ed._set_transition_field("guard", "i_bat < -50")
    ed._move_priority(-1)  # checked before the other transitions leaving 'normal'
    assert name != "limp" and ed.apply()
    text = str(block.params["definition"])
    spec = parse_chart(text)
    names = [s.name for s in spec.states]
    first = next(t for t in spec.transitions if names[t.source] == "normal")
    assert "limp" in names and names[first.target] == "limp" and first.guard_src == "i_bat < -50"
    assert block.meta["chart_layout"]["limp"]
    window.editor.undo_stack.undo()  # one step: the text and the layout
    assert str(block.params["definition"]) == before and "limp" not in block.meta.get("chart_layout", {})
    ed.close()


def test_invalid_chart_cannot_be_applied(window) -> None:  # type: ignore[no-untyped-def]
    block, ed = _open(window, "gear_shift.nervus", "shift_logic")
    before = str(block.params["definition"])
    ed.scene.clearSelection()
    ed.transition_items[0].setSelected(True)
    ed._set_transition_field("guard", "nonsense > 1")
    assert not ed.ok_button.isEnabled() and "unknown name 'nonsense'" in ed.message.text()
    assert not ed.apply() and str(block.params["definition"]) == before
    ed.close()


def test_text_tab_round_trip(window) -> None:  # type: ignore[no-untyped-def]
    _block, ed = _open(window, "engine_modes.nervus", "modes")
    ed.tabs.setCurrentIndex(1)
    text = ed.text.toPlainText()
    assert text.startswith("input") and "transition" in text
    ed.text.setPlainText(text + "\nstate extra\n")
    ed.tabs.setCurrentIndex(0)
    assert "extra" in ed.state_items
    ed.tabs.setCurrentIndex(1)
    ed.text.setPlainText("state broken -> nowhere")
    ed.tabs.setCurrentIndex(0)  # invalid: stays on the text tab with the reason
    assert ed.tabs.currentIndex() == 1 and "not a valid chart" in ed.message.text()
    ed.close()


def test_hierarchy_and_delete(window) -> None:  # type: ignore[no-untyped-def]
    _block, ed = _open(window, "gear_shift.nervus", "shift_logic")
    first = next(iter(ed.state_items))
    ed.scene.clearSelection()
    ed.state_items[first].setSelected(True)
    child = ed.add_child()
    assert child is not None and ed.state_items[child].parentItem() is ed.state_items[first]
    _fx, _fy, fw, fh = ed.chart.layout[first]
    cx, cy, cw, ch = ed.chart.layout[child]
    assert cx + cw <= fw and cy + ch <= fh  # the parent grew around its child
    ed.scene.clearSelection()
    ed.state_items[first].setSelected(True)
    n_before = len(ed.chart.transitions)
    ed.delete_selected()
    assert first not in ed.state_items and child not in ed.state_items and len(ed.chart.transitions) < n_before
    ed.close()
