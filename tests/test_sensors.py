"""Sensor and actuator models."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import ActuatorModel, Ramp, Scope, SensorModel, Step


def _run(block, source, t_final: float = 1.0):  # type: ignore[no-untyped-def]
    d = Diagram()
    d.chain(d.add(source, name="u"), d.add(block, name="y"), d.add(Scope()))
    return simulate(d, t_final, solver="rk4", step=0.01)


def test_gain_offset_resolution_range() -> None:
    r = _run(SensorModel(gain=1.02, offset=0.5, resolution=0.25, y_max=10.0), Ramp(slope=10.0))
    y, u = r["y"], r["u"]
    assert np.all(np.abs(y[1:-1] - np.clip(1.02 * u[:-2] + 0.5, None, 10.0)) <= 0.125 + 1e-9)  # one sample late
    assert np.allclose(y / 0.25, np.round(y / 0.25))
    assert y.max() == 10.0


def test_noise_is_reproducible() -> None:
    a = _run(SensorModel(noise=0.1, seed=3), Step(time=0.0, final=5.0))["y"]
    b = _run(SensorModel(noise=0.1, seed=3), Step(time=0.0, final=5.0))["y"]
    c = _run(SensorModel(noise=0.1, seed=4), Step(time=0.0, final=5.0))["y"]
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert np.std(a[10:]) == pytest.approx(0.1, rel=0.3)


def test_delay_in_samples() -> None:
    r = _run(SensorModel(delay=5), Step(time=0.2, final=1.0))
    first = r.t[np.argmax(r["y"] > 0.5)]
    assert first == pytest.approx(0.2 + 0.06, abs=1e-9)  # 5 samples of delay plus the output one sample later


@pytest.mark.parametrize(
    ("fault", "expected"),
    [("stuck", 3.0), ("open_circuit", 0.0), ("short_to_supply", 5.0), ("drift", 9.9 + 2.0 * 0.69)],
)
def test_faults(fault: str, expected: float) -> None:
    sensor = SensorModel(fault=fault, fault_time=0.3, y_min=0.0, y_max=5.0 if fault != "drift" else 100.0,
                         drift_rate=2.0)  # fmt: skip
    r = _run(sensor, Ramp(slope=10.0))
    assert r["y"][-1] == pytest.approx(expected, abs=0.11)


def test_actuator_rate_limit_and_stuck() -> None:
    r = _run(ActuatorModel(rate=2.0, y_max=1.5), Step(time=0.1, final=3.0))
    k = np.searchsorted(r.t, 0.5)
    assert r["y"][k] == pytest.approx(2.0 * (0.5 - 0.1 - 0.01), abs=0.03)  # moving at 2 per second
    assert r["y"][-1] == 1.5
    stuck = _run(ActuatorModel(rate=2.0, fault="stuck", fault_time=0.3), Step(time=0.1, final=3.0))
    assert stuck["y"][-1] == pytest.approx(stuck["y"][np.searchsorted(stuck.t, 0.31)], abs=1e-12)
