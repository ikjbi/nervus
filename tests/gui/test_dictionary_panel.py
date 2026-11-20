"""Data Dictionary panel and naming signals on wires."""

from nervus import Diagram
from nervus.blocks import Gain, Scope, Step


def test_name_signal_and_edit_objects(window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("m")
    s = d.add(Step(), name="u")
    g = d.add(Gain(gain=2.0), name="k")
    d.chain(s, g, d.add(Scope(), name="sc"))
    window.diagram_model.set_diagram(d)
    root = window.diagram_model.root
    wire = next(c for c in root.connections if c.src.name == "k")
    assert window.name_signal(wire, "torque")
    panel = window.dictionary_panel
    assert panel.table.rowCount() == 1 and "no signal object" in panel.table.item(0, 5).text()
    assert panel.table.item(0, 6).text() == "k:0"
    wire_item = next(w for w in window.scene.wires.values() if w.connection is wire)
    assert wire_item.signal_name() == "torque"
    # Add an object with the selected name, then edit it in the table.
    panel.table.setCurrentCell(0, 0)
    panel._add()
    assert "torque" in root.signals
    panel.table.item(0, 2).setText("N·m")
    panel.table.item(0, 4).setText("400")
    assert root.signals["torque"].unit == "N·m" and root.signals["torque"].max == 400.0
    panel.table.item(0, 4).setText("abc")  # rejected
    assert root.signals["torque"].max == 400.0
    # Undo: the max, the unit, the object, then the name.
    stack = window.editor.undo_stack
    for _ in range(3):
        stack.undo()
    assert "torque" not in root.signals
    stack.undo()
    assert wire_item.signal_name() == ""
    # A name can be used only once.
    errors = []
    window.editor.errorOccurred.connect(errors.append)
    assert window.name_signal(wire, "torque")
    other = next(c for c in root.connections if c.src.name == "u")
    assert not window.name_signal(other, "torque") and "already used" in errors[-1]
    assert not window.name_signal(other, "2bad")
