import numpy as np
import pytest

from nervus import Diagram, ModelError, simulate
from nervus.blocks import Gain, Inport, Integrator, Outport, Scope, Step, Subsystem, Sum
from nervus.io import dumps, loads


def first_order_subsystem(tau: str | float = 0.5) -> Subsystem:
    """dy/dt = (u - y)/tau inside a subsystem with one input and one output."""
    inner = Diagram("plant")
    u = inner.add(Inport(port=1), name="u")
    e = inner.add(Sum(signs="+-"), name="e")
    k = inner.add(Gain(gain=1.0 if isinstance(tau, str) else 1 / tau), name="k")
    if isinstance(tau, str):
        k.set_param("gain", f"1/{tau}")
    y = inner.add(Integrator(), name="y")
    out = inner.add(Outport(port=1), name="y_out")
    inner.connect(u, (e, 0))
    inner.connect(y, (e, 1))
    inner.chain(e, k, y, out)
    return Subsystem(system=inner)


def test_subsystem_simulates_like_flat_model() -> None:
    d = Diagram()
    step = d.add(Step(time=0.0), name="u")
    sub = d.add(first_order_subsystem(), name="plant")
    d.chain(step, sub, d.add(Scope(), name="scope"))
    r = simulate(d, 2.0)
    np.testing.assert_allclose(r["plant/y"], 1 - np.exp(-r.t / 0.5), atol=1e-5)
    np.testing.assert_array_equal(r.inputs("scope")[0], r["plant/y_out"])
    assert sub.num_inputs() == 1 and sub.num_outputs() == 1


def test_nested_subsystems_and_workspace() -> None:
    d = Diagram()
    d.workspace["tau"] = 0.25
    outer_sys = Diagram("outer")
    i = outer_sys.add(Inport(port=1), name="in")
    inner = outer_sys.add(first_order_subsystem("tau"), name="inner")
    o = outer_sys.add(Outport(port=1), name="out")
    outer_sys.chain(i, inner, o)
    outer = d.add(Subsystem(system=outer_sys), name="outer")
    d.chain(d.add(Step(time=0.0)), outer, d.add(Scope()))
    r = simulate(d, 1.0)
    np.testing.assert_allclose(r["outer/inner/y"], 1 - np.exp(-r.t / 0.25), atol=1e-5)
    assert [name for name, _ in d.walk()][:3] == ["outer", "outer/in", "outer/inner"]
    r2 = simulate(d, 1.0, params={"tau": 0.5})
    assert r2["outer/inner/y"][-1] == pytest.approx(1 - np.exp(-2), abs=1e-5)


def test_multiple_ports_follow_port_numbers() -> None:
    inner = Diagram()
    a = inner.add(Inport(port=2), name="a")
    b = inner.add(Inport(port=1), name="b")
    diff = inner.add(Sum(signs="+-"), name="diff")
    inner.connect(a, (diff, 0))
    inner.connect(b, (diff, 1))
    inner.connect(diff, inner.add(Outport(port=1), name="o"))
    d = Diagram()
    sub = d.add(Subsystem(system=inner), name="s")
    from nervus.blocks import Constant

    d.connect(d.add(Constant(value=10.0)), (sub, 0))  # -> port 1 = b
    d.connect(d.add(Constant(value=3.0)), (sub, 1))  # -> port 2 = a
    d.connect(sub, d.add(Scope()))
    assert simulate(d, 0.0)["s/diff"][-1] == -7.0  # a - b = 3 - 10


def test_errors_inside_subsystems_have_paths() -> None:
    inner = Diagram()
    inner.add(Inport(port=1), name="in")
    inner.add(Gain(), name="g")  # unconnected
    inner.add(Outport(port=1), name="out")
    d = Diagram()
    sub = d.add(Subsystem(system=inner), name="s")
    d.chain(d.add(Step()), sub, d.add(Scope()))
    with pytest.raises(ModelError) as exc:
        simulate(d, 1.0)
    assert "s/g" in str(exc.value) or "s/out" in str(exc.value)
    assert any(b.startswith("s/") for b in exc.value.blocks)


def test_port_numbers_must_be_contiguous() -> None:
    inner = Diagram()
    inner.add(Inport(port=1), name="a")
    inner.add(Inport(port=3), name="b")
    d = Diagram()
    d.add(Subsystem(system=inner), name="s")
    assert any("without gaps" in i.message for i in d.check())


def test_default_subsystem_passes_through() -> None:
    d = Diagram()
    sub = d.add(Subsystem(), name="s")
    d.chain(d.add(Step(time=0.0, final=2.0)), sub, d.add(Scope()))
    assert simulate(d, 0.5)["s/In1"][-1] == 2.0


def test_top_level_ports() -> None:
    d = Diagram()
    u = d.add(Inport(port=1, value=[1.0, 2.0]), name="u")
    g = d.add(Gain(gain=3.0), name="g")
    y = d.add(Outport(port=1), name="y")
    d.chain(u, g, y)
    r = simulate(d, 0.0)
    np.testing.assert_array_equal(r.inputs("y")[0][-1], [3.0, 6.0])


def test_subsystem_roundtrip() -> None:
    d = Diagram()
    d.workspace["tau"] = 0.5
    sub = d.add(first_order_subsystem("tau"), name="plant")
    sub.system.block("y").meta["position"] = [100, 0]
    d.chain(d.add(Step(time=0.0)), sub, d.add(Scope()))
    again = loads(dumps(d))
    s2 = again.block("plant")
    assert isinstance(s2, Subsystem)
    assert s2.system.block("y").meta == {"position": [100, 0]}
    assert s2.system.block("k").expressions == {"gain": "1/tau"}
    np.testing.assert_allclose(simulate(again, 1.0)["plant/y"], simulate(d, 1.0)["plant/y"])
