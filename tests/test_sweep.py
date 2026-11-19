import numpy as np
import pytest

from nervus import Diagram
from nervus.blocks import Gain, Integrator, Scope, Step, Sum
from nervus.core import Check, TestCase
from nervus.sweep import monte_carlo, sweep
from nervus.testing import html_report, load_suite, run_tests, save_suite


def first_order() -> Diagram:
    d = Diagram("pt1")
    d.workspace["tau"] = 0.5
    d.workspace["K"] = 1.0
    u = d.add(Step(time=0.0, final="K"), name="u")
    e = d.add(Sum(signs="+-"), name="e")
    g = d.add(Gain(gain="1 / tau"), name="g")
    y = d.add(Integrator(), name="y")
    d.connect(u, (e, 0))
    d.connect(y, (e, 1))
    d.chain(e, g, y, d.add(Scope()))
    d.settings.t_final = 1.0
    return d


def test_sweep_grid_and_csv(tmp_path) -> None:  # type: ignore[no-untyped-def]
    table = sweep(first_order(), {"tau": [0.1, 0.5], "K": [1.0, 2.0]}, metrics={"y_end": lambda r: r["y"][-1]})
    assert len(table.rows) == 4 and table.parameters == ["tau", "K"]
    by = {(r["tau"], r["K"]): r["y_end"] for r in table.rows}
    assert by[(0.1, 2.0)] == pytest.approx(2 * (1 - np.exp(-10)), rel=1e-4)
    assert by[(0.5, 1.0)] == pytest.approx(1 - np.exp(-2), rel=1e-4)
    text = table.to_csv(tmp_path / "s.csv").read_text()
    assert text.splitlines()[0] == "tau,K,y_end,error"
    assert "4 runs, 0 failed" in table.summary()


def test_monte_carlo_is_reproducible_and_reports_failures() -> None:
    d = first_order()
    a = monte_carlo(d, {"tau": ("uniform", 0.2, 0.8)}, runs=5, metrics={"y": lambda r: r["y"][-1]}, seed=3)
    b = monte_carlo(d, {"tau": ("uniform", 0.2, 0.8)}, runs=5, metrics={"y": lambda r: r["y"][-1]}, seed=3)
    np.testing.assert_array_equal(a.column("tau"), b.column("tau"))
    assert np.all((a.column("tau") >= 0.2) & (a.column("tau") <= 0.8))
    bad = sweep(d, {"tau": [0.5]}, metrics={"vector": lambda r: r["y"]})  # not one number
    assert bad.failed and "error" in bad.rows[0]


def test_suite_files_and_html_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = first_order()
    d.tests = [
        TestCase("settles", checks=[Check("final_value", "y", {"value": 0.86, "tolerance": 0.01})]),
        TestCase(
            "fast", parameters={"tau": 0.1}, checks=[Check("final_value", "y", {"value": 2.0, "tolerance": 0.01})]
        ),
    ]
    path = save_suite(d.tests, tmp_path / "suite")
    assert path.suffix == ".nervtest"
    again = load_suite(path)
    assert [t.to_dict() for t in again] == [t.to_dict() for t in d.tests]
    report = html_report(run_tests(d), "Report")
    assert "1 of 2 test cases passed" in report and "FAIL" in report and "tau = 0.1" in report
