"""Unit tests for individual blocks, using a tiny harness."""

from __future__ import annotations

import numpy as np
import pytest

from nervus import Diagram, ParameterError, simulate
from nervus.blocks import (
    Abs,
    Clock,
    Constant,
    Demux,
    Derivative,
    DiscreteIntegrator,
    DiscreteTransferFunction,
    FromWorkspace,
    Gain,
    MathFunction,
    Mux,
    Product,
    PythonFunction,
    Ramp,
    Saturation,
    Scope,
    StateSpace,
    Step,
    Sum,
    Switch,
    Terminator,
    TransferFunction,
    block_types,
    categories,
    create_block,
)
from nervus.core import Block


def run(block: Block, *inputs: Block, t_final: float = 1.0, **kw: object) -> np.ndarray:
    d = Diagram()
    b = d.add(block, name="dut")
    for k, src in enumerate(inputs):
        d.add(src)
        d.connect(src, (b, k))
    for p in range(b.num_outputs()):
        d.connect((b, p), d.add(Terminator()))
    res = simulate(d, t_final, **kw)  # type: ignore[arg-type]
    return res.signal("dut") if b.num_outputs() else res.t


def test_registry() -> None:
    types = block_types()
    assert len(types) >= 25
    assert all(cls.__doc__ for cls in types.values())
    assert all(cls.category for cls in types.values())
    assert "Sources" in categories()
    g = create_block("math.gain", "g", gain=3.0)
    assert isinstance(g, Gain) and g.name == "g"


def test_every_block_constructs_with_defaults() -> None:
    for cls in block_types().values():
        cls()


def test_gain_matrix() -> None:
    y = run(Gain(gain=[[1, 2], [3, 4]], multiplication="matrix"), Constant(value=[1.0, 1.0]))
    np.testing.assert_allclose(y[-1], [3.0, 7.0])


def test_gain_matrix_needs_2d() -> None:
    with pytest.raises(ParameterError):
        Gain(gain=[1, 2], multiplication="matrix")


def test_sum_and_product() -> None:
    assert run(Sum(signs="+-+"), Constant(value=5), Constant(value=2), Constant(value=1))[-1] == 4
    assert run(Product(ops="*/"), Constant(value=6), Constant(value=3))[-1] == 2


def test_abs_saturation_math() -> None:
    assert run(Abs(), Constant(value=-3))[-1] == 3
    assert run(Saturation(upper=1, lower=-1), Constant(value=-3))[-1] == -1
    assert run(MathFunction(function="sqrt"), Constant(value=16))[-1] == 4


def test_saturation_validation() -> None:
    with pytest.raises(ParameterError):
        Saturation(upper=-1, lower=1)


def test_ramp_and_clock() -> None:
    y = run(Ramp(slope=2, start_time=0.5), solver="rk4", step=0.25)
    np.testing.assert_allclose(y, [0, 0, 0, 0.5, 1.0])
    y = run(Clock(), solver="rk4", step=0.5)
    np.testing.assert_allclose(y, [0, 0.5, 1.0])


def test_step_vector() -> None:
    y = run(Step(time=0.5, initial=[0, 1], final=[2, 3]), solver="rk4", step=0.5)
    np.testing.assert_allclose(y, [[0, 1], [2, 3], [2, 3]])


def test_from_workspace_linear_and_hold() -> None:
    lin = run(FromWorkspace(time=[0, 1], data=[0, 10]), solver="rk4", step=0.25)
    np.testing.assert_allclose(lin, [0, 2.5, 5, 7.5, 10])
    hold = run(FromWorkspace(time=[0, 0.5], data=[1, 2], interpolation="hold"), solver="rk4", step=0.25)
    np.testing.assert_allclose(hold, [1, 1, 2, 2, 2])


def test_from_workspace_csv(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "d.csv"
    p.write_text("t,a,b\n0,0,1\n1,1,3\n")
    y = run(FromWorkspace(csv_file=str(p)), solver="rk4", step=0.5)
    np.testing.assert_allclose(y[-1], [1, 3])
    np.testing.assert_allclose(y[1], [0.5, 2])


def test_from_workspace_validation() -> None:
    with pytest.raises(ParameterError):
        FromWorkspace(time=[0, 1, 2], data=[1, 2])
    with pytest.raises(ParameterError):
        FromWorkspace(time=[1, 0], data=[1, 2])


def test_mux_demux_switch() -> None:
    np.testing.assert_allclose(run(Mux(), Constant(value=1), Constant(value=[2, 3]))[-1], [1, 2, 3])
    d = Diagram()
    c = d.add(Constant(value=[1, 2, 3, 4]))
    dm = d.add(Demux(num_outputs=2), name="dm")
    d.connect(c, dm)
    d.connect((dm, 0), d.add(Scope()))
    d.connect((dm, 1), d.add(Scope()))
    res = simulate(d, 1.0)
    np.testing.assert_allclose(res["dm:1"][-1], [3, 4])
    hi = run(
        Switch(threshold=0.5),
        Constant(value=1),
        Clock(),
        Constant(value=-1),
        solver="rk4",
        step=0.25,
    )
    np.testing.assert_allclose(hi, [-1, -1, 1, 1, 1])


def test_derivative_of_ramp() -> None:
    y = run(Derivative(time_constant=1e-3), Ramp(slope=3.0), solver="rk4", step=1e-4)
    assert y[-1] == pytest.approx(3.0, rel=1e-3)


def test_state_space_matches_tf() -> None:
    a = run(
        StateSpace(A=[[-2.0]], B=[[2.0]], C=[[1.0]], D=[[0.0]]),
        Step(time=0.0),
        solver="rk4",
        step=1e-3,
    )
    b = run(
        TransferFunction(numerator=[1.0], denominator=[0.5, 1.0]),
        Step(time=0.0),
        solver="rk4",
        step=1e-3,
    )
    np.testing.assert_allclose(a, b, atol=1e-12)


def test_state_space_validation() -> None:
    with pytest.raises(ParameterError):
        StateSpace(A=[[1, 2]])
    with pytest.raises(ParameterError):
        TransferFunction(numerator=[1, 2, 3], denominator=[1, 1])


def test_tf_with_feedthrough() -> None:
    tf = TransferFunction(numerator=[1.0, 0.0], denominator=[1.0, 1.0])  # s/(s+1)
    y = run(tf, Step(time=0.0), solver="rk4", step=1e-3)
    assert tf.direct_feedthrough()
    assert y[0] == pytest.approx(1.0)
    assert y[-1] == pytest.approx(np.exp(-1.0), abs=1e-6)


def test_discrete_integrator_methods() -> None:
    fwd = run(DiscreteIntegrator(sample_time=0.25), Constant(value=1.0))
    bwd = run(DiscreteIntegrator(sample_time=0.25, method="backward_euler"), Constant(value=1.0))
    np.testing.assert_allclose(fwd, [0, 0.25, 0.5, 0.75, 1.0])
    np.testing.assert_allclose(bwd, [0.25, 0.5, 0.75, 1.0, 1.25])


def test_discrete_tf_difference_equation() -> None:
    # H(z) = 1 / (z - 0.5)  =>  y[k] = 0.5 y[k-1] + u[k-1]
    y = run(
        DiscreteTransferFunction(numerator=[1.0], denominator=[1.0, -0.5], sample_time=1.0),
        Constant(value=1.0),
        t_final=5.0,
    )
    expected = [0.0]
    for _ in range(5):
        expected.append(0.5 * expected[-1] + 1.0)
    np.testing.assert_allclose(y, expected)


def test_python_function() -> None:
    code = "def f(t, a, b):\n    return a * b, a + b\n"
    d = Diagram()
    fn = d.add(PythonFunction(code=code, num_inputs=2, num_outputs=2), name="fn")
    d.connect(d.add(Constant(value=3.0)), (fn, 0))
    d.connect(d.add(Constant(value=4.0)), (fn, 1))
    d.connect((fn, 0), d.add(Scope()))
    d.connect((fn, 1), d.add(Scope()))
    res = simulate(d, 1.0)
    assert res["fn:0"][-1] == 12 and res["fn:1"][-1] == 7


def test_python_function_errors() -> None:
    with pytest.raises(ParameterError, match="syntax"):
        PythonFunction(code="def f(:\n")
    with pytest.raises(ParameterError, match="named f"):
        PythonFunction(code="def g(t, u):\n    return u\n")


def test_static_transfer_function() -> None:
    y = run(TransferFunction(numerator=[3.0], denominator=[2.0]), Step(time=0.0), solver="rk4", step=0.1)
    assert y[-1] == pytest.approx(1.5)
