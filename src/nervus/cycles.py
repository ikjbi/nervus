"""Standard drive cycles: the speed-over-time profiles of type approval tests.

    from nervus.cycles import cycle, cycle_stats
    t, v_kmh = cycle("wltc3b")
    cycle_stats("wltc3b")      # {'duration_s': 1800.0, 'distance_km': 23.27, 'max_kmh': 131.3, ...}

=========== ============================================================= ======== ========
name        cycle                                                         duration distance
=========== ============================================================= ======== ========
``wltc3b``  WLTC class 3b (WLTP; most cars), UNECE GTR No. 15, Annex 1    1800 s   23.27 km
``ftp75``   FTP-75 (US city cycle), US EPA dynamometer drive schedules    1874 s   17.77 km
``ece15``   ECE-15 / UDC (the urban part of the old European NEDC)        195 s    0.99 km
=========== ============================================================= ======== ========

The WLTC and FTP-75 tables are the official second-by-second values (bundled in ``nervus/data/cycles``); the
ECE-15 is defined by its corner points, linear in between.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import numpy as np

from nervus.core.types import Array

DATA = Path(__file__).parent / "data" / "cycles"
ECE15 = [
    (0, 0), (11, 0), (15, 15), (23, 15), (28, 0), (49, 0), (61, 32), (85, 32), (96, 0), (117, 0),
    (143, 50), (155, 50), (163, 35), (176, 35), (188, 0), (195, 0),
]  # fmt: skip
CYCLES = {
    "wltc3b": "WLTC class 3b (WLTP)",
    "ftp75": "FTP-75 (US EPA city cycle)",
    "ece15": "ECE-15 urban cycle (UDC)",
}


@cache
def cycle(name: str) -> tuple[Array, Array]:
    """(time [s], speed [km/h]) of a standard cycle, one point per second (ECE-15: its corner points)."""
    key = name.lower().replace("-", "").replace("_", "").replace(" ", "")
    if key in ("wltc3b", "wltc", "wltp", "wltcclass3b"):
        data = np.loadtxt(DATA / "wltc_class3b.csv", delimiter=",", comments="#")
    elif key in ("ftp75", "ftp"):
        data = np.loadtxt(DATA / "ftp75.csv", delimiter=",", comments="#")
    elif key in ("ece15", "udc"):
        data = np.array(ECE15, dtype=float)
    else:
        raise KeyError(f"unknown drive cycle {name!r}; known: {', '.join(CYCLES)}")
    return data[:, 0].copy(), data[:, 1].copy()


def cycle_stats(name: str) -> dict[str, float]:
    """Duration, distance, maximum and average speed, and the share of standstill."""
    t, v = cycle(name)
    tt = np.arange(t[0], t[-1] + 0.5, 1.0)
    vv = np.interp(tt, t, v)
    return {
        "duration_s": float(t[-1] - t[0]),
        "distance_km": float(np.trapezoid(v, t) / 3600.0),
        "max_kmh": float(v.max()),
        "mean_kmh": float(np.trapezoid(v, t) / (t[-1] - t[0])),
        "standstill_share": float(np.mean(vv < 0.5)),
    }
