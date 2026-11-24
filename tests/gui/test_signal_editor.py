"""The signal editor of the Signal Builder block."""

from PySide6.QtCore import QPointF

from nervus.blocks.signal_builder import parse_signals


def _open(window):  # type: ignore[no-untyped-def]
    block = window.editor.add_block("sources.signal_builder", QPointF(0, 0))
    window._block_activated(block)
    ed = next(w for w in window.findChildren(object) if type(w).__name__ == "SignalEditor")
    return block, ed


def test_edit_points_signals_and_groups(window) -> None:  # type: ignore[no-untyped-def]
    block, ed = _open(window)
    before = str(block.params["definition"])
    assert len(ed.points) == 1 and ed.table.rowCount() == 6  # the default tip-in: 6 points
    ed.select(0, 2)
    ed.move_point(0, 2, 5.0, 60.0)  # dragged past its right neighbour: stops at it (6 s)
    assert ed.signal(0).times[2] == 5.0 and ed.signal(0).values[2] == 60.0
    ed.move_point(0, 2, 99.0, 60.0)  # onto the jump at 6 s: three points at one time is not a signal
    assert ed.signal(0).times[2] == 6.0
    assert not ed.ok_button.isEnabled() and "three points" in ed.message.text()
    ed.move_point(0, 2, 5.0, 60.0)
    assert ed.ok_button.isEnabled()
    k = ed.add_point(0, 8.0, 20.0)
    assert ed.signal(0).times[k] == 8.0
    ed.delete_point()
    assert 8.0 not in ed.signal(0).times
    ed.add_signal("brake")
    assert len(ed.points) == 2 and all(len(g.signals) == 2 for g in ed.groups)
    ed.add_group("panic")
    ed.move_point(1, 0, 0.0, 100.0)  # full braking in the new group only
    ed._play()
    ok = ed.apply()
    assert ok, (ed.message.text(), window.properties.error.text(), window.status_label.text())
    groups = parse_signals(str(block.params["definition"]))
    assert [g.name for g in groups] == ["tip_in", "ramp", "panic"]
    assert groups[2].signal("brake").values == [100.0] and groups[0].signal("brake").values == [0.0]
    assert block.params["group"] == "panic" and block.num_outputs() == 2
    window.editor.undo_stack.undo()  # one step
    assert str(block.params["definition"]) == before and block.params["group"] == ""
    ed.close()


def test_text_tab_and_invalid_text(window) -> None:  # type: ignore[no-untyped-def]
    _block, ed = _open(window)
    ed.tabs.setCurrentIndex(1)
    assert "group tip_in" in ed.text.toPlainText()
    ed.text.setPlainText("group a\n  x: 0 1, 2 3\n")
    ed.tabs.setCurrentIndex(0)
    assert [g.name for g in ed.groups] == ["a"] and ed.signal(0).name == "x"
    ed.tabs.setCurrentIndex(1)
    ed.text.setPlainText("x: 0")
    ed.tabs.setCurrentIndex(0)  # invalid: stays on the text with the reason
    assert ed.tabs.currentIndex() == 1 and "not valid" in ed.message.text()
    ed.close()


def test_table_edit_keeps_time_order(window) -> None:  # type: ignore[no-untyped-def]
    _block, ed = _open(window)
    ed.select(0, 0)
    ed.table.item(0, 0).setText("7")  # the first point moved to 7 s: re-sorted
    assert ed.signal(0).times == sorted(ed.signal(0).times) and 7.0 in ed.signal(0).times
    ed.close()


class _Drag:
    """A mouse drag as pyqtgraph hands it to an item (in the item's coordinates)."""

    def __init__(self, start, end, phase: str) -> None:  # type: ignore[no-untyped-def]
        self.start, self.end, self.phase = start, end, phase

    def button(self):  # type: ignore[no-untyped-def]
        from PySide6.QtCore import Qt

        return Qt.MouseButton.LeftButton

    def isStart(self) -> bool:  # noqa: N802  (pyqtgraph's names)
        return self.phase == "start"

    def isFinish(self) -> bool:  # noqa: N802
        return self.phase == "finish"

    def buttonDownPos(self):  # type: ignore[no-untyped-def]  # noqa: N802
        return self.start

    def pos(self):  # type: ignore[no-untyped-def]
        return self.end

    def accept(self) -> None:
        pass

    def ignore(self) -> None:
        pass


def test_dragging_a_point(window) -> None:  # type: ignore[no-untyped-def]
    _block, ed = _open(window)
    item = ed.points[0]
    start = QPointF(ed.signal(0).times[3], ed.signal(0).values[3])  # (6, 80)
    for phase, end in (("start", start), ("move", QPointF(4.0, 50.0)), ("finish", QPointF(4.5, 40.0))):
        item.mouseDragEvent(_Drag(start, end, phase))
    assert ed.selected == (0, 3) and ed.signal(0).times[3] == 4.5 and ed.signal(0).values[3] == 40.0
    ed.close()
