"""Time-varying input signals for a model's top-level In blocks (test scenarios)."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.errors import ParameterError
from nervus.core.types import Array


@dataclass
class Signal:
    """A signal defined by points ``(time[k], values[k])``.

    *interpolation* ``hold`` keeps each value until the next time point (a staircase, like a recorded
    sampled signal); ``linear`` interpolates. Before the first and after the last point the end values hold.
    ``values`` has one row per time point and one column per element.
    """

    time: Array
    values: Array
    interpolation: str = "hold"

    def __post_init__(self) -> None:
        self.time = np.asarray(self.time, dtype=float).ravel()
        v = np.asarray(self.values, dtype=float)
        self.values = v.reshape(-1, 1) if v.ndim <= 1 else v
        if self.time.size == 0 or self.time.size != self.values.shape[0]:
            raise ParameterError("a signal needs as many values as time points")
        if np.any(np.diff(self.time) < 0):
            raise ParameterError("signal time points must be increasing")
        if self.interpolation not in ("hold", "linear"):
            raise ParameterError("interpolation must be 'hold' or 'linear'")

    @property
    def width(self) -> int:
        return int(self.values.shape[1])

    def __call__(self, t: float) -> Array:
        if self.interpolation == "hold":
            k = max(int(np.searchsorted(self.time, t, side="right")) - 1, 0)
            return self.values[k].copy()
        return np.array([np.interp(t, self.time, self.values[:, j]) for j in range(self.width)])

    def breakpoints(self) -> list[float]:
        return [float(t) for t in self.time] if self.interpolation == "hold" else []

    # ------------------------------------------------------------------ constructors

    @classmethod
    def constant(cls, value: float | Sequence[float]) -> Signal:
        return cls(np.array([0.0]), np.atleast_2d(np.asarray(value, dtype=float)))

    @classmethod
    def steps(cls, points: Sequence[tuple[float, Any]]) -> Signal:
        """Piecewise constant: ``Signal.steps([(0, 5), (0.2, 60), (1.2, 20)])``."""
        return cls(np.array([p[0] for p in points]), np.array([np.atleast_1d(p[1]) for p in points]))

    @classmethod
    def ramps(cls, points: Sequence[tuple[float, Any]]) -> Signal:
        """Piecewise linear through the points."""
        return cls(np.array([p[0] for p in points]), np.array([np.atleast_1d(p[1]) for p in points]), "linear")

    @classmethod
    def from_csv(cls, path: str | Path, column: int | str = 1, interpolation: str = "linear") -> Signal:
        """Load a signal from a CSV file whose first column is time. *column* is an index or header name."""
        with open(path, newline="") as fh:
            rows = list(csv.reader(fh))
        header = rows[0]
        try:
            [float(x) for x in header]
            data_rows, names = rows, None
        except ValueError:
            data_rows, names = rows[1:], header
        if isinstance(column, str):
            if names is None or column not in names:
                raise ParameterError(f"column {column!r} not found in {path}")
            column = names.index(column)
        arr = np.array([[float(r[0]), float(r[column])] for r in data_rows if r])
        return cls(arr[:, 0], arr[:, 1], interpolation)

    # ------------------------------------------------------------------ files

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time.tolist(), "values": self.values.tolist(), "interpolation": self.interpolation}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Signal:
        return cls(np.asarray(d["time"]), np.asarray(d["values"]), d.get("interpolation", "hold"))

    @classmethod
    def coerce(cls, value: Any) -> Signal:
        """Accept a Signal, a number/vector (constant), a ``(time, values)`` pair or a dict."""
        if isinstance(value, Signal):
            return value
        if isinstance(value, dict):
            return cls.from_dict(value)
        if isinstance(value, tuple) and len(value) == 2:
            return cls(np.asarray(value[0]), np.asarray(value[1]))
        return cls.constant(value)
