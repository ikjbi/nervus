"""Parameter sweeps and Monte Carlo runs.

Run a model many times with different workspace values and collect what you care about::

    from nervus.sweep import monte_carlo, sweep

    # Every combination: 3 × 2 = 6 runs.
    table = sweep(model, {"Kp": [0.5, 1.0, 2.0], "m": [1300, 1800]},
                  metrics={"overshoot": lambda r: r["speed"].max() - 50})

    # Tolerances: 200 runs with normally distributed parameters.
    table = monte_carlo(model, {"tau_sensor": ("normal", 0.1, 0.01), "q_inj": ("uniform", 3.8, 4.2)},
                        runs=200, metrics={"lambda_min": lambda r: r["lambda_cyl"].min()}, seed=1)
    table.to_csv("monte_carlo.csv")

Each row of the result has the parameter values and the metrics (or the error, if a run failed).
"""

from __future__ import annotations

import csv
import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.diagram import Diagram
from nervus.core.errors import NervusError
from nervus.sim.result import SimResult
from nervus.sim.simulator import simulate

Metric = Callable[[SimResult], float]


@dataclass
class SweepTable:
    """The outcome of a sweep: one row per run."""

    parameters: list[str]
    metrics: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)

    def column(self, name: str) -> np.ndarray:
        return np.array([r.get(name, np.nan) for r in self.rows], dtype=float)

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [r for r in self.rows if r.get("error")]

    def to_csv(self, path: str | Path) -> Path:
        p = Path(path)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[*self.parameters, *self.metrics, "error"])
            w.writeheader()
            for r in self.rows:
                w.writerow({k: r.get(k, "") for k in w.fieldnames})
        return p

    def summary(self) -> str:
        lines = [f"{len(self.rows)} runs, {len(self.failed)} failed"]
        for m in self.metrics:
            v = self.column(m)
            v = v[np.isfinite(v)]
            if v.size:
                lines.append(f"{m}: min {v.min():g}, mean {v.mean():g}, max {v.max():g}")
        return "\n".join(lines)


def _run(
    diagram: Diagram, points: Sequence[dict[str, Any]], metrics: Mapping[str, Metric], t_final: float | None, keep: bool
) -> SweepTable:
    table = SweepTable(list(points[0]) if points else [], list(metrics))
    for point in points:
        row: dict[str, Any] = dict(point)
        try:
            res = simulate(diagram, t_final, params=point)
            for name, fn in metrics.items():
                row[name] = float(np.squeeze(fn(res)))  # a metric must be one number
            if keep:
                row["result"] = res
        except (NervusError, ValueError, TypeError, ArithmeticError) as exc:
            row["error"] = str(exc).splitlines()[0]
        table.rows.append(row)
    return table


def sweep(
    diagram: Diagram,
    grid: Mapping[str, Sequence[Any]],
    metrics: Mapping[str, Metric] | None = None,
    t_final: float | None = None,
    keep_results: bool = False,
) -> SweepTable:
    """Simulate every combination of the values in ``grid`` (workspace variable name -> values)."""
    names = list(grid)
    points = [dict(zip(names, combo, strict=True)) for combo in itertools.product(*(grid[n] for n in names))]
    return _run(diagram, points, metrics or {}, t_final, keep_results)


def monte_carlo(
    diagram: Diagram,
    distributions: Mapping[str, tuple[Any, ...]],
    runs: int = 100,
    metrics: Mapping[str, Metric] | None = None,
    t_final: float | None = None,
    seed: int | None = None,
    keep_results: bool = False,
) -> SweepTable:
    """Simulate ``runs`` times with random workspace values.

    Distributions: ``("normal", mean, std)``, ``("uniform", low, high)`` or ``("choice", [values...])``.
    """
    rng = np.random.default_rng(seed)

    def draw(spec: tuple[Any, ...]) -> Any:
        kind = spec[0]
        if kind == "normal":
            return float(rng.normal(spec[1], spec[2]))
        if kind == "uniform":
            return float(rng.uniform(spec[1], spec[2]))
        if kind == "choice":
            return spec[1][int(rng.integers(len(spec[1])))]
        raise ValueError(f"unknown distribution {kind!r} (use normal, uniform or choice)")

    points = [{name: draw(spec) for name, spec in distributions.items()} for _ in range(runs)]
    return _run(diagram, points, metrics or {}, t_final, keep_results)
