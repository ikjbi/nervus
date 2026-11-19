"""Tools → Record from OBD-II, against a simulated ECU."""

import numpy as np

from nervus.obd import Elm327
from nervus.obd_sim import CONFIRMED, SimulatedEcu


def test_record_from_simulated_car(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    car = SimulatedEcu({"rpm": 2000.0, "speed": 50.0, "coolant_temp": 85.0}, {"P0171": CONFIRMED})
    dlg = window.show_obd()
    assert dlg.connect_car(Elm327(car))
    assert set(dlg.chosen_pids()) == {"rpm", "speed", "coolant_temp"}  # engine_load is not supported: unticked
    dlg.duration.setValue(0.3)
    dlg.interval.setValue(0.02)
    assert dlg.start()
    qtbot.waitUntil(lambda: dlg.recording is not None, timeout=10000)
    rec = dlg.recording
    assert len(rec.t) > 3 and np.all(rec["rpm"] == 2000.0)
    assert len(dlg._curves) == 3
    dlg.to_inspector()
    assert window.sim_model.runs[-1].label == "OBD recording"
    dlg.close()


def test_stop_and_bad_port(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = window.show_obd()
    dlg.port.setCurrentText("/dev/does-not-exist")
    assert not dlg.connect_car()
    assert "does-not-exist" in dlg.status.text() or "pyserial" in dlg.status.text()
    assert dlg.connect_car(Elm327(SimulatedEcu({"rpm": 900.0})))
    dlg.interval.setValue(0.02)
    assert dlg.start()  # until Stop
    qtbot.wait(150)
    dlg.toggle()
    qtbot.waitUntil(lambda: dlg.recording is not None, timeout=10000)
    assert len(dlg.recording.t) >= 1
    dlg.close()
