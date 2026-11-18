"""Variable-step integration using :func:`scipy.integrate.solve_ivp`."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.integrate import solve_ivp

from nervus.core.errors import SimulationError
from nervus.core.types import Array

VARIABLE_STEP_METHODS = ("RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA")
"""RK45/RK23/DOP853 are explicit (non-stiff); Radau/BDF/LSODA handle stiff systems."""


def integrate_variable(
    f: Callable[[float, Array], Array],
    t0: float,
    t1: float,
    x0: Array,
    method: str,
    rtol: float,
    atol: float,
    max_step: float,
) -> tuple[Array, Array]:
    """Integrate from ``t0`` to ``t1``. Returns the solver's accepted time points and states
    (shape ``(n_states, n_points)``), including both end points."""
    sol = solve_ivp(f, (t0, t1), x0, method=method, rtol=rtol, atol=atol, max_step=max_step)
    if not sol.success:
        raise SimulationError(f"solver {method} failed between t={t0:g} and t={t1:g}: {sol.message}")
    return np.asarray(sol.t, dtype=np.float64), np.asarray(sol.y, dtype=np.float64)
