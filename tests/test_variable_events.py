"""Zero-crossing location in the variable-step solvers."""

import numpy as np
import pytest

from nervus.solvers.variable import _locate, integrate_variable


@pytest.mark.parametrize("method", ["RK45", "BDF", "Radau", "LSODA"])
def test_event_time_is_exact(method: str) -> None:
    """A falling ball (x'' = -9.81 from 10 m) reaches the ground at sqrt(2 * 10 / 9.81) s."""

    def ground(t: float, x: np.ndarray) -> float:
        return float(x[0])

    ts, ys, fired = integrate_variable(lambda t, x: np.array([x[1], -9.81]), 0.0, 5.0, np.array([10.0, 0.0]),
                                       method, 1e-9, 1e-12, 0.1, [ground])  # fmt: skip
    assert fired == 0 and ts[-1] == pytest.approx(np.sqrt(20 / 9.81), rel=1e-7) and abs(ys[0, -1]) < 1e-6


def test_direction_is_respected() -> None:
    """With direction +1 only the upward crossing of sin(t) (at 2π) counts, not the downward one at π."""

    def ev(t: float, x: np.ndarray) -> float:
        return float(np.sin(t))

    ev.direction = 1.0  # type: ignore[attr-defined]
    ts, _ys, fired = integrate_variable(lambda t, x: np.zeros(1), 0.5, 10.0, np.zeros(1), "RK45", 1e-9, 1e-12, 0.1,
                                        [ev])  # fmt: skip
    assert fired == 0 and ts[-1] == pytest.approx(2 * np.pi, abs=1e-9)


def test_rounding_at_the_start_of_the_step() -> None:
    """The crossing was detected from g(t_old) = 0 exactly, but the step's polynomial gives a tiny value with the
    same sign as at t_new: no bracket. scipy's solve_ivp raises an error there; the crossing is at t_old."""

    def ev(t: float, x: np.ndarray) -> float:
        return float(x[0])

    sol = lambda t: np.array([1e-17 + t])  # noqa: E731  (rounding: positive already at t_old = 0)
    assert _locate(ev, sol, 0.0, 1.0, g_old=0.0) == 0.0
    assert _locate(ev, sol, 0.0, 1.0, g_old=-1e-3) == 1.0  # g was negative at t_old: the crossing is at t_new
    assert _locate(ev, lambda t: np.array([t - 0.25]), 0.0, 1.0, g_old=-0.25) == pytest.approx(0.25, abs=1e-12)
