"""End-to-end simulations checked against analytical solutions."""

import math

import numpy as np
import pytest

from nervus import Diagram, SimulationError, simulate
from nervus.blocks import (
    PID,
    Constant,
    DiscretePID,
    Gain,
    Integrator,
    Pulse,
    Scope,
    Sine,
    Step,
    Sum,
    ToWorkspace,
    TransferFunction,
    UnitDelay,
    ZeroOrderHold,
)


@pytest.mark.parametrize("solver", ["auto", "RK23", "DOP853", "LSODA", "BDF", "rk4"])
def test_first_order_step(first_order: Diagram, solver: str) -> None:
    res = simulate(first_order, 3.0, solver=solver)
    exact = 1 - np.exp(-res.t / 0.5)
    np.testing.assert_allclose(res["y"], exact, atol=1e-4)


def test_euler_is_first_order(first_order: Diagram) -> None:
    def err(h: float) -> float:
        r = simulate(first_order, 1.0, solver="euler", step=h)
        return float(abs(r["y"][-1] - (1 - math.exp(-2.0))))

    assert math.log2(err(0.01) / err(0.005)) == pytest.approx(1.0, abs=0.1)


def mass_spring_damper(m: float, c: float, k: float, force: float) -> Diagram:
    """m x'' + c x' + k x = F (step at t=0)."""
    d = Diagram("msd")
    f = d.add(Step(time=0.0, final=force), name="F")
    s = d.add(Sum(signs="+--"), name="sum")
    inv_m = d.add(Gain(gain=1 / m), name="1/m")
    v = d.add(Integrator(), name="v")
    x = d.add(Integrator(), name="x")
    gc = d.add(Gain(gain=c), name="c")
    gk = d.add(Gain(gain=k), name="k")
    d.connect(f, (s, 0))
    d.connect(gc, (s, 1))
    d.connect(gk, (s, 2))
    d.chain(s, inv_m, v, x)
    d.connect(v, gc)
    d.connect(x, gk)
    d.chain(x, d.add(Scope()))
    return d


def test_underdamped_second_order() -> None:
    m, c, k, force = 1.0, 0.4, 4.0, 2.0
    res = simulate(mass_spring_damper(m, c, k, force), 10.0, rtol=1e-9, atol=1e-11)
    wn = math.sqrt(k / m)
    zeta = c / (2 * math.sqrt(k * m))
    wd = wn * math.sqrt(1 - zeta**2)
    t = res.t
    exact = force / k * (1 - np.exp(-zeta * wn * t) * (np.cos(wd * t) + zeta / math.sqrt(1 - zeta**2) * np.sin(wd * t)))
    np.testing.assert_allclose(res["x"], exact, atol=1e-6)


def test_transfer_function_matches_integrator_loop(first_order: Diagram) -> None:
    d = Diagram()
    u = d.add(Step(time=0.0))
    tf = d.add(TransferFunction(numerator=[1.0], denominator=[0.5, 1.0]), name="tf")
    d.chain(u, tf, d.add(Scope()))
    a = simulate(d, 3.0, solver="rk4", step=0.001)
    b = simulate(first_order, 3.0, solver="rk4", step=0.001)
    np.testing.assert_allclose(a["tf"], b["y"], atol=1e-9)


def test_step_at_breakpoint_is_exact() -> None:
    d = Diagram()
    u = d.add(Step(time=1.0), name="u")
    i = d.add(Integrator(), name="i")
    d.chain(u, i, d.add(Scope()))
    res = simulate(d, 3.0)
    assert 1.0 in res.t
    np.testing.assert_allclose(res["i"], np.maximum(0.0, res.t - 1.0), atol=1e-10)


def test_sine_integral() -> None:
    d = Diagram()
    s = d.add(Sine(frequency=2.0))
    i = d.add(Integrator(), name="i")
    d.chain(s, i, d.add(Scope()))
    res = simulate(d, 5.0, solver="rk4", step=1e-3)
    np.testing.assert_allclose(res["i"], (1 - np.cos(2 * res.t)) / 2, atol=1e-9)


def test_integrator_limits() -> None:
    d = Diagram()
    c = d.add(Constant(value=1.0))
    i = d.add(Integrator(upper=0.5), name="i")
    d.chain(c, i, d.add(Scope()))
    res = simulate(d, 2.0)
    assert res["i"].max() == pytest.approx(0.5)
    np.testing.assert_allclose(res["i"], np.minimum(res.t, 0.5), atol=1e-6)


def test_unit_delay_sequence() -> None:
    """Discrete accumulator y[k+1] = y[k] + 1 sampled at T=0.1."""
    d = Diagram()
    one = d.add(Constant(value=1.0))
    s = d.add(Sum(), name="s")
    ud = d.add(UnitDelay(sample_time=0.1), name="ud")
    d.connect(one, (s, 0))
    d.connect(ud, (s, 1))
    d.connect(s, ud)
    d.chain(ud, d.add(Scope()))
    res = simulate(d, 1.0)
    np.testing.assert_allclose(res.t, np.linspace(0, 1, 11), atol=1e-12)
    np.testing.assert_allclose(res["ud"], np.arange(11), atol=1e-12)


def test_zoh_holds_between_samples() -> None:
    d = Diagram()
    src = d.add(Sine(frequency=1.0))
    zoh = d.add(ZeroOrderHold(sample_time=0.25), name="zoh")
    i = d.add(Integrator(), name="i")  # forces continuous steps in between
    d.chain(src, zoh, i, d.add(Scope()))
    res = simulate(d, 2.0, solver="rk4", step=0.05)
    expected = np.sin(np.floor(res.t / 0.25 + 1e-9) * 0.25)
    np.testing.assert_allclose(res["zoh"], expected, atol=1e-12)


def test_multirate_fixed_step_default() -> None:
    d = Diagram()
    c = d.add(Constant())
    z1 = d.add(ZeroOrderHold(sample_time=0.2))
    z2 = d.add(ZeroOrderHold(sample_time=0.3))
    d.chain(c, z1, d.add(Scope()))
    d.connect(c, z2)
    d.chain(z2, d.add(Scope()))
    res = simulate(d, 1.2, solver="rk4")
    assert res.stats is not None and res.stats.step == pytest.approx(0.1)


def test_fixed_step_must_divide_sample_time() -> None:
    d = Diagram()
    d.chain(d.add(Constant()), d.add(ZeroOrderHold(sample_time=0.1)), d.add(Scope()))
    with pytest.raises(SimulationError, match="does not divide"):
        simulate(d, 1.0, solver="rk4", step=0.03)


def test_pulse_generator() -> None:
    d = Diagram()
    p = d.add(Pulse(period=1.0, duty=25.0), name="p")
    i = d.add(Integrator(), name="i")
    d.chain(p, i, d.add(Scope()))
    res = simulate(d, 4.0)
    assert res["i"][-1] == pytest.approx(1.0, abs=1e-9)  # 4 pulses * 0.25 s


def _plant_with_controller(controller: object, t_sample: float | None = None) -> Diagram:
    """Unity feedback around 1/(s+1) with reference step 1."""
    d = Diagram()
    r = d.add(Step(time=0.0), name="r")
    e = d.add(Sum(signs="+-"), name="e")
    ctrl = d.add(controller, name="ctrl")  # type: ignore[arg-type]
    plant = d.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]), name="plant")
    d.connect(r, (e, 0))
    d.connect(plant, (e, 1))
    if t_sample:
        zoh = d.add(ZeroOrderHold(sample_time=t_sample), name="zoh")
        d.chain(e, zoh, ctrl, plant)
    else:
        d.chain(e, ctrl, plant)
    d.add(ToWorkspace(variable="y"), name="out")
    d.connect(plant, d.block("out"))
    return d


def test_pi_removes_steady_state_error() -> None:
    res = simulate(_plant_with_controller(PID(P=2.0, I=3.0)), 10.0)
    assert res["y"][-1] == pytest.approx(1.0, abs=1e-4)


def test_p_only_has_steady_state_error() -> None:
    res = simulate(_plant_with_controller(PID(P=4.0)), 10.0)
    assert res["y"][-1] == pytest.approx(4 / 5, abs=1e-4)


@pytest.mark.parametrize(("method", "solver"), [("back_calculation", "auto"), ("clamping", "rk4")])
def test_pid_anti_windup_reduces_overshoot(method: str, solver: str) -> None:
    def overshoot(aw: str) -> float:
        pid = PID(P=1.0, I=5.0, upper=1.5, lower=-1.5, anti_windup=aw)
        d = _plant_with_controller(pid)
        d.block("r").set_param("final", 1.2)
        return float(simulate(d, 15.0, solver=solver, step=0.01)["y"].max())

    assert overshoot(method) < overshoot("none") - 0.05


def test_discrete_pid_clamping() -> None:
    def overshoot(aw: str) -> float:
        pid = DiscretePID(P=1.0, I=5.0, upper=1.5, lower=-1.5, anti_windup=aw, sample_time=0.01)
        d = _plant_with_controller(pid, t_sample=0.01)
        d.block("r").set_param("final", 1.2)
        return float(simulate(d, 15.0)["y"].max())

    assert overshoot("clamping") < overshoot("none") - 0.05


def test_discrete_pid_close_to_continuous() -> None:
    cont = simulate(_plant_with_controller(PID(P=2.0, I=3.0)), 5.0, solver="rk4", step=0.001)
    disc = simulate(
        _plant_with_controller(DiscretePID(P=2.0, I=3.0, sample_time=0.001), t_sample=0.001),
        5.0,
        solver="rk4",
        step=0.001,
    )
    np.testing.assert_allclose(disc["y"], cont["y"], atol=5e-3)


def test_stop_callback(first_order: Diagram) -> None:
    calls: list[float] = []
    res = simulate(
        first_order,
        10.0,
        solver="rk4",
        step=0.1,
        progress=calls.append,
        should_stop=lambda: len(calls) >= 5,
    )
    assert res.stats is not None and res.stats.stopped_early
    assert len(res.t) == 5


def test_result_access(first_order: Diagram, tmp_path) -> None:  # type: ignore[no-untyped-def]
    res = simulate(first_order, 1.0)
    _u, y = res.inputs("scope")
    np.testing.assert_array_equal(y, res["y"])
    assert "y" in res and "nope" not in res
    assert res.signal("y", 0).shape == res.t.shape
    path = tmp_path / "out.csv"
    res.to_csv(path)
    header = path.read_text().splitlines()[0]
    assert header.startswith("t,")
    with pytest.raises(KeyError):
        res["missing"]
