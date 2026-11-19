"""Integrator x0 input and saturation port; Initial Condition block; n-D Interpolation."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    Constant,
    InitialCondition,
    Inport,
    Integrator,
    Interpolation,
    Outport,
    Prelookup,
    Scope,
    Step,
    Sum,
    ZeroOrderHold,
)
from nervus.core.errors import ParameterError


@pytest.mark.parametrize("solver", ["rk4", "RK45"])
def test_integrator_external_initial_condition(solver: str) -> None:
    d = Diagram()
    u = d.add(Constant(value=1.0), name="u")
    x0 = d.add(Constant(value=20.0), name="x0")
    integ = d.add(Integrator(initial_source="external", upper=22.0, saturation_port=True), name="integ")
    d.connect(u, (integ, 0))
    d.connect(x0, (integ, 1))
    d.connect((integ, 0), d.add(Scope()))
    d.connect((integ, 1), d.add(Scope()))
    r = simulate(d, 3.0, solver=solver, step=0.01)
    y = r["integ"]
    assert y[0] == pytest.approx(20.0)  # starts at x0, not at the parameter's 0
    assert np.interp(1.0, r.t, y) == pytest.approx(21.0, abs=1e-6)
    assert y[-1] == pytest.approx(22.0)
    sat = r.signal("integ", 1)
    assert sat[0] == 0.0 and sat[-1] == 1.0


def test_external_x0_feeds_through_but_input_does_not() -> None:
    """A feedback loop through the integrator's input is fine; x0 is read in the first step, so a block
    computing x0 runs before the integrator."""
    d = Diagram()
    integ = d.add(Integrator(initial_source="external"), name="integ")
    neg = d.add(Sum(signs="-"), name="neg")
    x0 = d.add(Constant(value=4.0), name="x0")
    d.chain(integ, neg)
    d.connect(neg, (integ, 0))  # dx/dt = -x
    d.connect(x0, (integ, 1))
    d.connect(integ, d.add(Scope()))
    r = simulate(d, 1.0, solver="RK45")
    assert r["integ"][0] == pytest.approx(4.0)
    assert r["integ"][-1] == pytest.approx(4.0 * np.exp(-1.0), rel=1e-4)


def test_reset_to_external_x0() -> None:
    d = Diagram()
    integ = d.add(Integrator(initial_source="external", external_reset="rising"), name="integ")
    d.connect(d.add(Constant(value=1.0)), (integ, 0))
    d.connect(d.add(Step(time=1.0, initial=0.0, final=1.0)), (integ, 1))
    d.connect(d.add(Step(time=0.5, initial=-1.0, final=5.0)), (integ, 2))  # x0 changes before the reset
    d.connect(integ, d.add(Scope()))
    r = simulate(d, 1.5, solver="rk4", step=0.01)
    assert r["integ"][0] == pytest.approx(-1.0)
    assert r["integ"][-1] == pytest.approx(5.5, abs=1e-9)  # reset to 5 at t = 1, then +0.5


def test_initial_condition_block() -> None:
    d = Diagram()
    ic = d.add(InitialCondition(value=2.0), name="ic")
    d.chain(d.add(Constant(value=5.0)), ic, d.add(Scope()))  # not a constant block: changes after t0
    r = simulate(d, 1.0, solver="rk4", step=0.1, t_start=0.5)
    assert r["ic"][0] == 2.0
    assert np.all(r["ic"][1:] == 5.0)


def test_initial_condition_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("ic")
    u = d.add(Inport(port=1), name="u")
    ic = d.add(InitialCondition(value=[1.0, -2.0]), name="ic")
    d.chain(u, d.add(ZeroOrderHold(sample_time=0.01)), ic, d.add(Outport(port=1), name="y"))
    res = back_to_back(d, {"u": np.arange(10.0) + 3}, 10, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
    assert res.python["y"][0].tolist() == [1.0, -2.0]


rng = np.random.default_rng(1)
AXES = ([0.0, 1.0, 3.0], [10.0, 20.0], [-1.0, 0.0, 1.0, 2.0])
TABLE3 = rng.normal(size=(3, 2, 4))


def _ref3(x: list[float]) -> float:
    from scipy.interpolate import RegularGridInterpolator

    clipped = [np.clip(v, a[0], a[-1]) for v, a in zip(x, AXES, strict=True)]
    return float(RegularGridInterpolator(AXES, TABLE3)(clipped)[0])


def _interp3_model() -> Diagram:
    d = Diagram("map3d")
    interp = d.add(Interpolation(dimensions=3, table=TABLE3.tolist()), name="map")
    for k, axis in enumerate(AXES):
        i = d.add(Inport(port=k + 1), name=f"x{k}")
        z = d.add(ZeroOrderHold(sample_time=0.01))
        pre = d.add(Prelookup(breakpoints=axis), name=f"pre{k}")
        d.chain(i, z, pre)
        d.connect((pre, 0), (interp, 2 * k))
        d.connect((pre, 1), (interp, 2 * k + 1))
    d.connect(interp, d.add(Outport(port=1), name="y"))
    return d


def test_interpolation_3d_matches_scipy() -> None:
    d = _interp3_model()
    pts = [[0.5, 12.0, -0.5], [2.9, 19.0, 1.7], [-1.0, 25.0, 3.0], [1.0, 10.0, 0.0]]
    for p in pts:
        inputs = {f"x{k}": np.array([p[k]]) for k in range(3)}
        r = simulate(d, 0.0, solver="rk4", step=0.01, inputs=inputs)
        assert r["y"][0] == pytest.approx(_ref3(p), abs=1e-12)


def test_interpolation_3d_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    k = np.arange(50)
    inputs = {"x0": 0.07 * k - 0.2, "x1": 9.0 + 0.3 * k, "x2": np.sin(k) * 2}
    res = back_to_back(_interp3_model(), inputs, 50, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()


def test_interpolation_table_must_match_dimensions() -> None:
    with pytest.raises(ParameterError, match="3-D table"):
        Interpolation(dimensions=3, table=[[1.0, 2.0], [3.0, 4.0]])
    assert Interpolation(dimensions=4, table=np.ones((2, 2, 2, 2)).tolist()).num_inputs() == 8
