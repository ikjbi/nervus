"""Variable autocompletion and Find Usages."""

from pathlib import Path

from PySide6.QtCore import QPointF

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


def test_usages_in_model() -> None:
    from nervus import load

    d = load(EXAMPLES / "gear_shift.nervus")
    assert d.usages("r_wheel") == [
        ("car/gearbox/wheel_speed", "gain = 1 / r_wheel"),
        ("car/body/tractive_force", "gain = eta_driveline / r_wheel"),
    ]
    assert d.usages("min_gear_time") == [("tcu/shift_logic", "chart param min_gear_time")]
    assert d.usages("not_a_variable") == []


def test_usages_respect_masks_and_workspace_expressions() -> None:
    from nervus.blocks import Gain, Inport, Outport, Subsystem
    from nervus.core import Diagram, Variable

    d = Diagram()
    d.workspace.add(Variable("k", 2.0))
    d.workspace.add(Variable("k2", "k * 2"))
    inner = Diagram()
    inner.chain(inner.add(Inport(port=1)), inner.add(Gain(gain="k"), name="g"), inner.add(Outport(port=1)))
    sub = Subsystem(system=inner)
    sub.mask.add(Variable("k", "k + 1"))  # the mask's own k, computed from the model's k
    d.add(sub, name="masked")
    d.add(Gain(gain="k"), name="outer")
    found = d.usages("k")
    assert ("", "workspace variable k2 = k * 2") in found
    assert ("masked", "mask variable k = k + 1") not in found  # defines k itself
    assert ("outer", "gain = k") in found
    assert not any(path == "masked/g" for path, _ in found)  # inside, k is the mask's variable


def test_completer_offers_workspace_and_mask_names(window) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.views.completer import VariableCompleter, visible_names

    window.files.open(EXAMPLES / "gear_shift.nervus")
    car = window.diagram_model.root.block("car").system
    names = visible_names(car)
    assert "r_wheel" in names and "upshift_map" in names
    c = VariableCompleter(["Kp", "Ki", "Ti"])
    assert c.splitPath("2 * K") == ["K"]
    assert c.splitPath("2 * ") == ["\x00"]  # nothing to complete after an operator
    c.splitPath("Kp / T")
    assert c.pathFromIndex(c.model().index(2, 0)) == "Kp / Ti"
    window.editor.add_block("math.gain", QPointF())
    window.scene.select_blocks(["Gain"])
    assert isinstance(window.properties._editors["gain"].completer(), VariableCompleter)


def test_find_usages_dialog(window) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "gear_shift.nervus")
    dlg = window.show_usages("mass")
    assert dlg.tree.topLevelItemCount() == 2
    item = dlg.tree.topLevelItem(1)
    dlg._activated(item, 0)  # double-click: opens the subsystem and selects the block
    assert window.diagram_model.diagram is window.diagram_model.root.block("car").system.block("body").system
    assert [b.name for b in window.scene.selected_blocks()] == ["accel"]
    dlg.close()
