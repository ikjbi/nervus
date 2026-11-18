import numpy as np
import pytest

from nervus.solvers import euler_step, rk4_step


def _integrate(step, h: float) -> float:  # type: ignore[no-untyped-def]
    x = np.array([1.0])
    t = 0.0
    for _ in range(round(1.0 / h)):
        x = step(lambda t, x: -x, t, x, h)
        t += h
    return float(x[0])


@pytest.mark.parametrize(("step", "order"), [(euler_step, 1), (rk4_step, 4)])
def test_convergence_order(step, order: int) -> None:  # type: ignore[no-untyped-def]
    exact = np.exp(-1.0)
    e1 = abs(_integrate(step, 0.01) - exact)
    e2 = abs(_integrate(step, 0.005) - exact)
    observed = np.log2(e1 / e2)
    assert observed == pytest.approx(order, abs=0.15)
