import numpy as np
import pytest

from nervus import Diagram, ModelError, ParameterError, ParameterSet, simulate
from nervus.blocks import Constant, Gain, Integrator, Scope, Step, Sum
from nervus.core import Variable, Workspace
from nervus.core.expressions import UnknownNameError, names_in, parse_value
from nervus.io import dumps, loads, model_file


def test_parse_with_names() -> None:
    assert parse_value("2*Kp", {"Kp": 1.5}) == 3.0
    assert parse_value("m[1]", {"m": [1.0, 2.0, 3.0]}) == 2.0
    np.testing.assert_allclose(parse_value("2*v", {"v": [1.0, 2.0]}), [2.0, 4.0])
    with pytest.raises(UnknownNameError) as exc:
        parse_value("Kp + Ki", {"Kp": 1.0})
    assert exc.value.names == {"Ki"}
    assert names_in("sqrt(Kp) * pi + tau") == {"Kp", "tau"}


def test_workspace_namespace_and_expressions() -> None:
    ws = Workspace()
    ws["Kp"] = 2
    ws["Ti"] = 0.5
    ws["Ki"] = "Kp / Ti"
    ws["map"] = [[1, 2], [3, 4]]
    ns = ws.namespace()
    assert ns["Ki"] == 4.0
    assert ns["map"] == [[1.0, 2.0], [3.0, 4.0]]
    assert ws.namespace({"Kp": 1.0})["Ki"] == 2.0
    with pytest.raises(ModelError, match="unknown"):
        ws.namespace({"nope": 1.0})


def test_workspace_order_and_errors() -> None:
    ws = Workspace()
    ws["a"] = "b + 1"
    ws["b"] = 1.0
    with pytest.raises(ModelError, match="define it above"):
        ws.namespace()
    with pytest.raises(ParameterError):
        Variable("1bad", 0.0)


def test_ranges() -> None:
    ws = Workspace()
    ws.add(Variable("rpm", 9000.0, unit="1/min", min=0, max=7000))
    assert ws.check_ranges() == ["rpm is above its maximum 7000"]


def _gain_model() -> Diagram:
    d = Diagram()
    d.workspace["Kp"] = 3.0
    c = d.add(Constant(value=2.0), name="c")
    g = d.add(Gain(gain="Kp"), name="g")
    d.chain(c, g, d.add(Scope()))
    return d


def test_block_parameter_expression() -> None:
    d = _gain_model()
    g = d.block("g")
    assert g.expressions == {"gain": "Kp"}
    assert float(g.params["gain"]) == 3.0
    assert simulate(d, 1.0)["g"][-1] == 6.0
    d.workspace["Kp"] = 5.0
    assert simulate(d, 1.0)["g"][-1] == 10.0  # re-resolved at compile time
    assert simulate(d, 1.0, params={"Kp": 1.0})["g"][-1] == 2.0


def test_unknown_variable_reported() -> None:
    d = Diagram()
    g = d.add(Gain(gain="Kx"), name="g")
    d.chain(d.add(Constant()), g, d.add(Scope()))
    issues = [i.message for i in d.check()]
    assert any("unknown variable Kx" in m for m in issues)
    with pytest.raises(ModelError, match="Kx"):
        simulate(d, 1.0)


def test_set_param_expression_validation() -> None:
    d = _gain_model()
    g = d.block("g")
    with pytest.raises(ParameterError, match="unknown variable"):
        g.set_param("gain", "Kpp")
    assert g.expressions == {"gain": "Kp"}  # unchanged
    g.set_param("gain", "2*Kp")
    assert float(g.params["gain"]) == 6.0
    g.set_param("gain", 4.0)
    assert g.expressions == {}
    g.set_param("gain", "2*pi")  # a literal, not an expression
    assert g.expressions == {} and float(g.params["gain"]) == pytest.approx(2 * np.pi)


def test_expression_in_sum_feedback_and_sample_time() -> None:
    d = Diagram()
    d.workspace["tau"] = 0.5
    d.workspace["Ts"] = 0.1
    u = d.add(Step(time=0.0))
    e = d.add(Sum(signs="+-"), name="e")
    k = d.add(Gain(gain="1/tau"), name="k")
    y = d.add(Integrator(), name="y")
    d.connect(u, (e, 0))
    d.connect(y, (e, 1))
    d.chain(e, k, y, d.add(Scope()))
    r = simulate(d, 2.0)
    assert r["y"][-1] == pytest.approx(1 - np.exp(-4), abs=1e-5)


def test_model_file_keeps_expressions_and_workspace() -> None:
    d = _gain_model()
    d.workspace.variable("Kp").unit = "-"
    text = dumps(d)
    again = loads(text)
    assert again.block("g").expressions == {"gain": "Kp"}
    assert again.workspace.variable("Kp").unit == "-"
    assert simulate(again, 1.0)["g"][-1] == 6.0


def test_v1_files_migrate() -> None:
    data = model_file.to_dict(_gain_model())
    data["schema_version"] = 1
    del data["workspace"]
    data["blocks"][1]["params"]["gain"] = 2.0
    d = model_file.from_dict(data)
    assert len(d.workspace) == 0


def test_parameter_sets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = _gain_model()
    d.workspace["map"] = [[1.0, 2.0], [3.0, 4.0]]
    ps = ParameterSet.from_workspace(d.workspace, "petrol")
    path = ps.save(tmp_path / "petrol")
    assert path.suffix == ".nervcal"
    d.workspace["Kp"] = 0.0
    loaded = ParameterSet.load(path)
    assert loaded.name == "petrol"
    d.workspace.apply(loaded.values)
    assert d.workspace["Kp"] == 3.0 and d.workspace["map"] == [[1.0, 2.0], [3.0, 4.0]]
    with pytest.raises(ParameterError, match="no variable"):
        d.workspace.apply({"other": 1.0})
    with pytest.raises(ModelError):
        ParameterSet.load(tmp_path / "missing.nervcal")
