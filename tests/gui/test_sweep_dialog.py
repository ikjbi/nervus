"""Parameter Sweep / Monte Carlo dialog."""

import numpy as np
import pytest

from nervus.gui.views.sweep_dialog import MONTE_CARLO, parse_distribution, parse_values


def test_parse_values_and_distributions() -> None:
    assert parse_values("0.5, 1, 2") == [0.5, 1.0, 2.0]
    assert parse_values("[1 2 3]") == [1.0, 2.0, 3.0]
    assert parse_values("linspace(0, 1, 5)") == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert parse_distribution("normal(1, 0.1)") == ("normal", 1.0, 0.1)
    assert parse_distribution("uniform(2*pi, 7)")[1] == pytest.approx(2 * np.pi)
    with pytest.raises(ValueError, match="normal"):
        parse_distribution("gauss(1, 2)")


def _model(window):  # type: ignore[no-untyped-def]
    from nervus.blocks import Constant, Gain, Integrator, Outport, Sum
    from nervus.core import Diagram, Variable

    d = Diagram("first_order")
    d.settings.t_final = 1.0
    d.settings.solver = "rk4"
    d.settings.step = 0.01
    d.workspace.add(Variable("k", 2.0))
    d.workspace.add(Variable("u0", 1.0))
    err = d.add(Sum(signs="+-"), name="err")
    d.connect(d.add(Constant(value="u0"), name="u"), (err, 0))
    integ = d.add(Integrator(), name="x")
    d.chain(err, d.add(Gain(gain="k"), name="gain"), integ)
    d.connect(integ, (err, 1))
    d.connect(integ, d.add(Outport(port=1), name="y"))
    window.diagram_model.set_diagram(d)
    return d


def test_sweep_runs_and_plots(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    _model(window)
    dlg = window.show_sweep()
    assert dlg.signal.currentText() == "y"
    dlg.add_parameter("k", "1, 2, 4")
    dlg.add_parameter("u0", "1, 2")
    dlg.stat.setCurrentText("final")
    assert dlg.start()
    assert not window.editor.editing_enabled  # locked while the runs read the model
    qtbot.waitUntil(lambda: dlg.table is not None, timeout=30000)
    assert window.editor.editing_enabled
    tab = dlg.table
    assert len(tab.rows) == 6 and not tab.failed
    final = tab.column("final(y)")
    expected = [u0 * (1 - np.exp(-k)) for k in (1, 2, 4) for u0 in (1, 2)]
    np.testing.assert_allclose(final, expected, rtol=1e-6)
    assert len(dlg.traces) == 6 and dlg.results.rowCount() == 6
    dlg.close()


def test_monte_carlo_histogram(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    _model(window)
    dlg = window.show_sweep()
    dlg.mode.setCurrentText(MONTE_CARLO)
    dlg.add_parameter("k", "normal(2, 0.2)")
    dlg.runs.setValue(20)
    dlg.stat.setCurrentText("max")
    assert dlg.start()
    qtbot.waitUntil(lambda: dlg.table is not None, timeout=30000)
    assert len(dlg.table.rows) == 20
    assert np.std(dlg.table.column("k")) > 0.05  # random values
    assert "20 runs" in dlg.status.text()
    dlg.close()


def test_invalid_input_is_reported(window) -> None:  # type: ignore[no-untyped-def]
    _model(window)
    dlg = window.show_sweep()
    assert not dlg.start()
    assert "add at least one variable" in dlg.status.text()
    dlg.close()
