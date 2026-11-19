"""Zero-crossing detection locates discontinuities exactly with variable-step solvers."""

import math
import time

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import PID, Abs, Constant, Integrator, Saturation, Scope, Sine, Step, Sum, Switch, TransferFunction


def _integral_of(block, t_final: float, zc: bool, source=None):  # type: ignore[no-untyped-def]
    d = Diagram()
    s = d.add(source or Sine(frequency=1.0), name="u")
    b = d.add(block, name="b")
    i = d.add(Integrator(), name="i")
    d.chain(s, b, i, d.add(Scope()))
    d.settings.zero_crossing = zc
    d.settings.max_step = 1.0  # large steps: without event location the corners are stepped over
    return simulate(d, t_final, rtol=1e-8, atol=1e-10)


def test_saturation_integral_is_exact() -> None:
    t_f = 2 * math.pi
    # ∫ clip(sin t, -0.5, 0.5) over a full period is 0; over a half period it is 2*(pi/6*0.5 + (1-cos(pi/6))) ...
    exact = 2 * (0.5 * (5 * math.pi / 6 - math.pi / 6) / 2 + (1 - math.cos(math.pi / 6)))
    on = _integral_of(Saturation(upper=0.5, lower=-0.5), math.pi, zc=True)
    off = _integral_of(Saturation(upper=0.5, lower=-0.5), math.pi, zc=False)
    err_on = abs(on["i"][-1] - exact)
    err_off = abs(off["i"][-1] - exact)
    assert err_on < 1e-7
    assert err_on < err_off
    assert on.stats is not None and on.stats.zero_crossings >= 2
    assert abs(_integral_of(Saturation(upper=0.5, lower=-0.5), t_f, zc=True)["i"][-1]) < 1e-7


def test_abs_integral() -> None:
    res = _integral_of(Abs(), 3 * math.pi, zc=True)
    assert res["i"][-1] == pytest.approx(6.0, abs=1e-7)  # ∫|sin| over 3 half-periods


def test_switch_event_time() -> None:
    d = Diagram()
    clock_like = d.add(Sine(frequency=1.0), name="c")
    sw = d.add(Switch(threshold=0.5), name="sw")
    i = d.add(Integrator(), name="i")
    d.connect(d.add(Constant(value=1.0)), (sw, 0))
    d.connect(clock_like, (sw, 1))
    d.connect(d.add(Constant(value=0.0)), (sw, 2))
    d.chain(sw, i, d.add(Scope()))
    d.settings.max_step = 1.0
    res = simulate(d, math.pi, rtol=1e-9, atol=1e-11)
    # sin(t) >= 0.5 between pi/6 and 5pi/6
    assert res["i"][-1] == pytest.approx(2 * math.pi / 3, abs=1e-7)


def test_integrator_hits_limit_exactly() -> None:
    d = Diagram()
    i = d.add(Integrator(upper=1.0), name="i")
    d.chain(d.add(Constant(value=1.0)), i, d.add(Scope()))
    d.settings.max_step = 10.0
    res = simulate(d, 3.0)
    k = int(np.argmin(abs(res.t - 1.0)))
    assert res.t[k] == pytest.approx(1.0, abs=1e-9)  # an event exactly at the limit
    assert res["i"][-1] == pytest.approx(1.0)


def _clamped_pid_loop(aw: str, d_gain: float = 0.0) -> Diagram:
    d = Diagram()
    r = d.add(Step(time=0.0, final=1.2), name="r")
    e = d.add(Sum(signs="+-"), name="e")
    c = d.add(PID(P=1.0, I=5.0, D=d_gain, upper=1.5, lower=-1.5, anti_windup=aw), name="pid")
    p = d.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]), name="y")
    d.connect(r, (e, 0))
    d.connect(p, (e, 1))
    d.chain(e, c, p, d.add(Scope()))
    return d


@pytest.mark.parametrize("aw", ["clamping", "none", "back_calculation"])
@pytest.mark.parametrize("d_gain", [0.0, 0.01])
def test_saturated_pid_matches_a_fine_fixed_step_reference(aw: str, d_gain: float) -> None:
    """The clamped integrator slides along the limit. Variable step must follow the same trajectory as a
    very fine fixed-step run (it used to stay clamped too long, and only the final value was right)."""
    t0 = time.perf_counter()
    res = simulate(_clamped_pid_loop(aw, d_gain), 15.0)
    elapsed = time.perf_counter() - t0
    ref = simulate(_clamped_pid_loop(aw, d_gain), 15.0, solver="rk4", step=2e-3)  # within 2e-4 of 1e-4
    t = np.linspace(0, 15, 601)
    err = np.abs(np.interp(t, res.t, res["y"].ravel()) - np.interp(t, ref.t, ref["y"].ravel()))
    assert err.max() < 0.01
    assert elapsed < 5.0
    assert not res.stats.warnings


def test_zero_crossing_can_be_disabled() -> None:
    res = _integral_of(Saturation(upper=0.5, lower=-0.5), math.pi, zc=False)
    assert res.stats is not None and res.stats.zero_crossings == 0


def test_stop_simulation_and_assertion() -> None:
    from nervus import SimulationError
    from nervus.blocks import Assertion, Clock, CompareToConstant, StopSimulation

    d = Diagram()
    clk = d.add(Clock(), name="t")
    cmp_ = d.add(CompareToConstant(operator=">=", constant=1.5), name="late")
    d.chain(clk, cmp_, d.add(StopSimulation(), name="stop"))
    res = simulate(d, 10.0)
    assert res.t[-1] == pytest.approx(1.5, abs=1e-9)  # located exactly by the zero crossing
    assert res.stats is not None and res.stats.stopped_early

    d2 = Diagram()
    c2 = d2.add(Clock(), name="t")
    ok = d2.add(CompareToConstant(operator="<", constant=2.0), name="ok")
    d2.chain(c2, ok, d2.add(Assertion(message="t must stay below 2"), name="assert"))
    with pytest.raises(SimulationError, match="t must stay below 2 at t = 2"):
        simulate(d2, 5.0)
