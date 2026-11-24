"""Shared type aliases."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]
"""A float64 NumPy array. Signals are 1-D arrays of this type."""


def as_signal(value: object) -> Array:
    """Convert a scalar or array-like into a 1-D float64 signal array."""
    if isinstance(value, float | int):
        return np.array([value], dtype=np.float64)  # fast path: this is called in hot loops
    if isinstance(value, np.ndarray) and value.ndim == 1 and value.dtype == np.float64:
        return value
    return np.atleast_1d(np.asarray(value, dtype=np.float64)).ravel()


def widened(value: Array, shape: tuple[int, ...]) -> Array:
    """A copy of ``value`` with ``shape`` (a scalar is repeated); fast when it already has the shape."""
    if value.shape == shape:
        return value.copy()
    return np.broadcast_to(value, shape).copy()


EMPTY: Array = np.zeros(0)
