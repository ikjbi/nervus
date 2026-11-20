"""Tools → CAN Bus Trace after a simulation with a rest bus."""

from pathlib import Path

import pytest

from nervus import Diagram, simulate
from nervus.blocks import CanReceive, CanRestBus, Scope

pytest.importorskip("cantools")
DBC = str(Path(__file__).parent.parent.parent / "examples" / "data" / "vehicle.dbc")


def test_trace_shows_decoded_frames(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("bus")
    d.add(CanRestBus(dbc_file=DBC, values="EngineSpeed=1500, VehicleSpeed=50"), name="rest")
    rx = d.add(CanReceive(dbc_file=DBC, message="VehicleData"), name="rx")
    for k in range(6):
        d.connect((rx, k), d.add(Scope()))
    simulate(d, 0.1, solver="rk4", step=0.001)
    window.diagram_model.set_diagram(d)
    dlg = window.show_can_trace()
    dlg.bus_box.setCurrentText("can0")
    dlg.refresh()
    # EngineData every 10 ms, VehicleData every 20 ms; the frames queued at the last sample (90 ms) are only put
    # on the wire when a later sample asks the bus, so the last frame is missing.
    n = dlg.tree.topLevelItemCount()
    assert n in (14, 15)
    rows = [dlg.tree.topLevelItem(k) for k in range(3)]
    assert rows[0].text(1) == "0x100" and rows[0].text(2) == "EngineData"  # lowest ID first at t = 0
    assert "EngineSpeed=1500 rpm" in rows[0].text(6)
    assert "VehicleSpeed=50 km/h" in rows[1].text(6)
    assert "load" in dlg.info.text()
    assert dlg.export("asc", str(tmp_path / "t.asc")).read_text().count(" Rx ") == n
    dlg.close()


def test_import_dbc_into_workspace(window) -> None:  # type: ignore[no-untyped-def]
    chassis = str(Path(DBC).with_name("chassis.dbc"))
    added = window.workspace_panel.import_dbc(chassis)
    ws = window.diagram_model.root.workspace
    assert "GearSelector_Drive" in added and ws.variable("GearSelector_Drive").value == 3.0
    assert window.workspace_panel.import_dbc(chassis) == []  # names that exist are kept
    window.editor.undo_stack.undo()  # one undo step for the whole import
    assert "GearSelector_Drive" not in window.diagram_model.root.workspace
