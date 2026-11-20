"""Data Inspector: load an MDF4 measurement file."""

import numpy as np
import pytest

asammdf = pytest.importorskip("asammdf")


def test_load_mdf_into_inspector(window, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mdf = asammdf.MDF(version="4.10")
    t = np.arange(0, 2, 0.01)
    mdf.append([asammdf.Signal(800 + 100 * t, t, name="n_engine", unit="rpm")])
    mdf.save(tmp_path / "log.mf4")
    insp = window.show_inspector()
    assert insp.load_file(str(tmp_path / "log.mf4"))
    run = window.sim_model.runs[-1]
    assert run.label == "log.mf4" and "n_engine" in run.result.names()
    warnings = []
    monkeypatch.setattr("nervus.gui.views.data_inspector.QMessageBox.warning", lambda *a: warnings.append(a))
    (tmp_path / "bad.mf4").write_text("not an MDF file")
    assert not insp.load_file(str(tmp_path / "bad.mf4")) and warnings
