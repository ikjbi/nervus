"""Fixed-step explicit integration methods.

Fixed-step solvers are what runs on an ECU: the generated code calls ``model_step()`` at a fixed rate.
"""

from __future__ import annotations

from collections.abc import Callable

from nervus.core.types import Array

Derivative = Callable[[float, Array], Array]


def euler_step(f: Derivative, t: float, x: Array, h: float) -> Array:
    """Forward Euler: first-order accurate, cheapest."""
    return x + h * f(t, x)


def rk4_step(f: Derivative, t: float, x: Array, h: float) -> Array:
    """Classic fourth-order Runge–Kutta."""
    k1 = f(t, x)
    k2 = f(t + h / 2, x + h / 2 * k1)
    k3 = f(t + h / 2, x + h / 2 * k2)
    k4 = f(t + h, x + h * k3)
    return x + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


FIXED_STEP_METHODS: dict[str, Callable[[Derivative, float, Array, float], Array]] = {
    "euler": euler_step,
    "rk4": rk4_step,
}
