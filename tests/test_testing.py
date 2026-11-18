import numpy as np
import pytest

from nervus import Diagram, ModelError, ParameterSet, load, save, simulate
from nervus.blocks import DiscretePID, Gain, Inport, Integrator, Outport, Scope, Sum, ZeroOrderHold
from nervus.core import Check, Signal, TestCase
from nervus.io import dumps, loads
from nervus.sim import SimResult
from nervus.testing import compare_results, run_test, run_tests


def loop_model() -> Diagram:
    """Setpoint (In) -> discrete PI -> integrating plant -> Out."""
    d = Diagram("loop")
    d.workspace["Kp"] = 2.0
    d.workspace["Ki"] = 1.0
    r = d.add(Inport(port=1), name="setpoint")
    e = d.add(Sum(signs="+-"), name="e")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="zoh")
    c = d.add(DiscretePID(P="Kp", I="Ki", sample_time=0.01), name="pi")
    g = d.add(Gain(gain=1.0), name="g")
    y = d.add(Integrator(), name="y")
    d.connect(r, (e, 0))
    d.connect(y, (e, 1))
    d.chain(e, z, c, g, y)
    d.connect(y, d.add(Outport(port=1), name="out"))
    d.connect(y, d.add(Scope()))
    d.settings.t_final = 5.0
    return d


def test_signals() -> None:
    s = Signal.steps([(0, 1.0), (1, 3.0)])
    assert s(0.5)[0] == 1.0 and s(1.0)[0] == 3.0 and s(9)[0] == 3.0
    r = Signal.ramps([(0, 0.0), (2, 4.0)])
    assert r(1.0)[0] == 2.0
    assert Signal.coerce(2.5)(7.0)[0] == 2.5
    assert Signal.coerce(([0, 1], [[1, 2], [3, 4]])).width == 2
    assert Signal.from_dict(s.to_dict())(1.5)[0] == 3.0


def test_signal_from_csv(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "log.csv"
    p.write_text("t,rpm,load\n0,800,10\n1,2000,50\n")
    s = Signal.from_csv(p, "load")
    assert s(0.5)[0] == 30.0


def test_inputs_drive_inports() -> None:
    d = loop_model()
    res = simulate(d, 15.0, inputs={"setpoint": Signal.steps([(0, 0.0), (1, 2.0)])})
    assert res["y"][-1] == pytest.approx(2.0, abs=0.05)
    with pytest.raises(ModelError, match="no top-level In"):
        simulate(d, inputs={"nope": 1.0})


def _case() -> TestCase:
    return TestCase(
        name="step_to_2",
        stop_time=15.0,
        inputs={"setpoint": Signal.steps([(0, 0.0), (1, 2.0)])},
        checks=[
            Check("reaches", "y", {"value": 1.9, "before": 4.0}),
            Check("max", "y", {"value": 2.6}),
            Check("final_value", "y", {"value": 2.0, "tolerance": 0.05}),
            Check("bounds", "y", {"lower": -0.01, "upper": 0.01, "t_to": 1.0}),
        ],
    )


def test_run_test_passes() -> None:
    r = run_test(loop_model(), _case())
    assert r.passed, r.summary()
    assert "PASS" in r.summary()


def test_failing_checks_and_messages() -> None:
    case = _case()
    case.parameters = {"Kp": 0.05, "Ki": 0.0}  # far too slow
    r = run_test(loop_model(), case)
    assert not r.passed
    failed = [c for c in r.checks if not c.passed]
    assert any(c.check.kind == "reaches" for c in failed)
    assert "✗" in r.summary()


def test_errors_are_reported() -> None:
    r = run_test(loop_model(), TestCase("bad", parameters={"missing": 1.0}))
    assert not r.passed and "unknown" in r.error


def test_parameter_set_in_case(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ParameterSet("slow", {"Kp": 0.05, "Ki": 0.0}).save(tmp_path / "slow.nervcal")
    case = _case()
    case.parameter_set = "slow.nervcal"
    assert not run_test(loop_model(), case, base_dir=tmp_path).passed


def test_tests_saved_with_model(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = loop_model()
    d.tests.append(_case())
    again = loads(dumps(d))
    assert again.tests[0].name == "step_to_2"
    assert again.tests[0].checks[0].args == {"value": 1.9, "before": 4.0}
    results = run_tests(again)
    assert len(results) == 1 and results[0].passed


def test_result_files_and_baseline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = loop_model()
    res = simulate(d, inputs={"setpoint": 1.0})
    path = res.save(tmp_path / "baseline")
    assert path.suffix == ".nervres"
    again = SimResult.load(path)
    np.testing.assert_array_equal(again["y"], res["y"])
    assert again.inputs("out")[0].shape == res.t.shape
    assert compare_results(res, again) == {k: 0.0 for k in compare_results(res, again)}
    case = TestCase(
        "regression",
        inputs={"setpoint": Signal.constant(1.0)},
        checks=[Check("baseline", "y", {"path": "baseline.nervres", "tolerance": 1e-9})],
    )
    assert run_test(d, case, base_dir=tmp_path).passed
    d.workspace["Kp"] = 3.0
    assert not run_test(d, case, base_dir=tmp_path).passed


def test_mat_export(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from scipy.io import loadmat

    res = simulate(loop_model(), inputs={"setpoint": 1.0})
    res.to_mat(tmp_path / "r.mat")
    m = loadmat(tmp_path / "r.mat")
    assert "t" in m and "y" in m


def test_check_validation() -> None:
    with pytest.raises(Exception, match="unknown check kind"):
        Check("nope", "y")


def test_saved_tests_in_file_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = loop_model()
    d.tests.append(_case())
    save(d, tmp_path / "m")
    assert load(tmp_path / "m.nervus").tests[0].inputs["setpoint"](2.0)[0] == 2.0
