"""Solving algebraic loops (Simulation Settings ▸ Algebraic loops = solve)."""

import numpy as np
import pytest

from nervus import Diagram, ModelError, simulate
from nervus.blocks import Constant, Gain, MathFunction, Scope, Sine, Sum
from nervus.core.errors import AlgebraicLoopError, SimulationError


def _loop(k: float = 0.5) -> Diagram:
    """y = u - k·y, so y = u / (1 + k): a feedback without delay."""
    d = Diagram("loop")
    u = d.add(Sine(amplitude=2.0), name="u")
    s = d.add(Sum(signs="+-"), name="sum")
    g = d.add(Gain(gain=k), name="k")
    d.connect(u, (s, 0))
    d.connect(g, (s, 1))
    d.chain(s, g)
    d.connect(s, d.add(Scope(), name="sc"))
    return d


def test_error_by_default_and_solved_on_request() -> None:
    d = _loop()
    with pytest.raises(AlgebraicLoopError, match="Algebraic loops to 'solve'"):
        simulate(d, 1.0)
    d.settings.algebraic_loops = "solve"
    r = simulate(d, 2.0, solver="rk4", step=0.01)
    assert np.allclose(r["sum"], 2.0 * np.sin(r.t) / 1.5, atol=1e-9)
    assert any("algebraic loop solved by iteration: sum -> k" in w for w in r.stats.warnings or [])
    # Per run, without changing the model's settings.
    d.settings.algebraic_loops = "error"
    from nervus import SimulationSettings

    r2 = simulate(d, 1.0, settings=SimulationSettings(t_final=1.0, algebraic_loops="solve"))
    assert r2["sum"][-1] == pytest.approx(2.0 * np.sin(1.0) / 1.5, abs=1e-9)


def test_nonlinear_loop_and_two_loops() -> None:
    # x = cos(x): the Dottie number 0.739085..., and a second, independent loop y = 3 - y/2 → y = 2.
    d = Diagram()
    d.settings.algebraic_loops = "solve"
    cosx = d.add(MathFunction(function="cos"), name="cos")
    x = d.add(Sum(signs="++"), name="x")  # x = 0 + cos(x); the constant sets the signal width
    d.connect(d.add(Constant(value=0.0)), (x, 0))
    d.connect(cosx, (x, 1))
    d.chain(x, cosx)
    s = d.add(Sum(signs="+-"), name="s2")
    half = d.add(Gain(gain=0.5), name="half")
    d.connect(d.add(Constant(value=3.0)), (s, 0))
    d.connect(half, (s, 1))
    d.chain(s, half)
    d.connect(cosx, d.add(Scope()))
    d.connect(s, d.add(Scope()))
    r = simulate(d, 0.1, solver="rk4", step=0.05)
    assert r["cos"][-1] == pytest.approx(0.7390851332, abs=1e-9)
    assert r["s2"][-1] == pytest.approx(2.0, abs=1e-9)
    assert len([w for w in r.stats.warnings or [] if "algebraic loop" in w]) == 2


def test_downstream_blocks_see_the_solution_and_no_solution_is_reported() -> None:
    d = _loop(k=1.0)
    d.settings.algebraic_loops = "solve"
    after = d.add(Gain(gain=10.0), name="after")
    d.connect(d.block("sum"), after)
    d.connect(after, d.add(Scope()))
    r = simulate(d, 1.0, solver="rk4", step=0.1)
    assert np.allclose(r["after"], 10 * r["sum"]) and np.allclose(r["sum"], np.sin(r.t))
    bad = _loop(k=-1.0)  # y = u + y: no solution unless u = 0
    bad.settings.algebraic_loops = "solve"
    bad.block("u").set_param("bias", 1.0)
    with pytest.raises(SimulationError, match="has no solution"):
        simulate(bad, 1.0, solver="rk4", step=0.1)


def test_codegen_is_refused() -> None:
    from nervus.codegen import CodegenError, generate_c

    d = _loop()
    d.settings.algebraic_loops = "solve"
    with pytest.raises((CodegenError, ModelError), match="algebraic loop"):
        generate_c(d)
