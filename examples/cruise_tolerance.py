"""Robustness by Monte Carlo: does the cruise control work for every car it will be built into?

The cruise control of the first tutorial was tuned for a 1500 kg car. Real cars of the model range weigh 1200 to
2000 kg (driver, passengers, luggage), and the drag varies with tyres, roof boxes and the wind (here ±10 % as a
normal distribution). This script runs the set-speed step 200 times with random masses and drag coefficients
and checks the requirement:

    after the step to 100 km/h, the speed is within ±1 km/h of the set speed within 20 s, for every car.

Run with ``uv run python examples/cruise_tolerance.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from nervus import SimResult
from nervus.sweep import SweepTable, monte_carlo

HERE = Path(__file__).parent
TOLERANCES = {"m": ("uniform", 1200.0, 2000.0), "c_drag": ("normal", 8.0, 0.8)}
REQUIRED_S = 20.0


def _cruise():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("cruise_control", HERE / "cruise_control.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def settling_time(res: SimResult) -> float:
    """Seconds after the set-speed step (at 1 s) until the speed stays within ±1 km/h of 100 km/h."""
    v = np.ravel(res["speed"])
    out = np.where(np.abs(v - 100.0) > 1.0)[0]
    return float(res.t[out[-1]]) - 1.0 if len(out) else 0.0


def study(ki: float = 30.0, runs: int = 200, seed: int = 1) -> SweepTable:
    d = _cruise().build(ki=ki)
    return monte_carlo(d, TOLERANCES, runs=runs, seed=seed,
                       metrics={"settling_s": settling_time, "max_kmh": lambda r: float(np.max(r["speed"]))})  # fmt: skip


def report(table: SweepTable, label: str) -> None:
    ts, vmax = table.column("settling_s"), table.column("max_kmh")
    ok = np.mean(ts <= REQUIRED_S)
    print(f"{label}: settling {np.min(ts):.1f}-{np.max(ts):.1f} s (mean {np.mean(ts):.1f}, 95 % below "
          f"{np.percentile(ts, 95):.1f}), overshoot up to {np.max(vmax) - 100:.2f} km/h, "
          f"requirement met in {100 * ok:.0f} % of the cars")  # fmt: skip


def main() -> dict[str, SweepTable]:
    tables = {"Ki = 30": study(30.0), "Ki = 60": study(60.0)}
    for label, table in tables.items():
        report(table, label)
    table = tables["Ki = 30"]
    r = np.corrcoef(table.column("m"), table.column("settling_s"))[0, 1]
    print(f"correlation of the settling time with the mass: {r:.2f}")
    out = HERE / "generated"
    out.mkdir(exist_ok=True)
    table.to_csv(out / "cruise_monte_carlo.csv")
    return tables


if __name__ == "__main__":
    main()
