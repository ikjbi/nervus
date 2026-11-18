"""Variable-step integration using :func:`scipy.integrate.solve_ivp`."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.integrate import solve_ivp

from nervus.core.errors import SimulationError
from nervus.core.types import Array


def integrate_variable(
    f: Callable[[float, Array], Array],
    t0: float,
    t1: float,
    x0: Array,
    method: str,
    rtol: float,
    atol: float,
    max_step: float,
    events: list[Callable[[float, Array], float]] | None = None,
) -> tuple[Array, Array, int | None]:
    """Integrate from ``t0`` towards ``t1``, stopping early at the first event (zero crossing).

    Returns the accepted time points, the states (shape ``(n_states, n_points)``) including both end points,
    and the index of the event that stopped the integration (``None`` if it reached ``t1``).
    """
    if events:
        for ev in events:
            ev.terminal = True  # type: ignore[attr-defined]
    sol = solve_ivp(f, (t0, t1), x0, method=method, rtol=rtol, atol=atol, max_step=max_step, events=events or None)
    if not sol.success:
        raise SimulationError(f"solver {method} failed between t={t0:g} and t={t1:g}: {sol.message}")
    fired = None
    if sol.status == 1 and sol.t_events is not None:
        fired = next((k for k, te in enumerate(sol.t_events) if len(te)), None)
    return np.asarray(sol.t, dtype=np.float64), np.asarray(sol.y, dtype=np.float64), fired
