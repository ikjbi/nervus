"""Bundled drive cycles and the Drive Cycle block."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import DriveCycle, Scope
from nervus.cycles import cycle, cycle_stats


@pytest.mark.parametrize(
    ("name", "duration", "km", "vmax"),
    [("wltc3b", 1800.0, 23.266, 131.3), ("ftp75", 1874.0, 17.770, 91.25), ("ece15", 195.0, 0.994, 50.0)],
)
def test_official_figures(name: str, duration: float, km: float, vmax: float) -> None:
    st = cycle_stats(name)
    assert st["duration_s"] == duration
    assert st["distance_km"] == pytest.approx(km, abs=0.002)
    assert st["max_kmh"] == pytest.approx(vmax, abs=0.01)


def test_wltc_phases() -> None:
    t, v = cycle("wltc3b")
    for (a, b), km in zip(
        ((0, 589), (589, 1022), (1022, 1477), (1477, 1800)), (3.095, 4.756, 7.162, 8.254), strict=True
    ):
        m = (t >= a) & (t <= b)
        assert np.trapezoid(v[m], t[m]) / 3600 == pytest.approx(km, abs=0.003)


def test_block_outputs_speed_and_acceleration(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram()
    blk = d.add(DriveCycle(cycle="ece15", unit="m/s"), name="cyc")
    d.connect((blk, 0), d.add(Scope()))
    d.connect((blk, 1), d.add(Scope()))
    r = simulate(d, 200.0, solver="rk4", step=0.5)
    k = np.searchsorted(r.t, 13.0)
    assert r["cyc"][k] == pytest.approx(15 / 3.6 * (13 - 11) / 4, rel=1e-6)
    assert r["cyc:1"][k] == pytest.approx(15 / 3.6 / 4, rel=1e-6)
    assert r["cyc"][-1] == 0.0  # after the end
    f = tmp_path / "mine.csv"
    f.write_text("0,0\n10,36\n20,0\n")
    own = DriveCycle(cycle="csv_file", csv_file=str(f))
    own.out_widths = [1, 1]
    assert own.outputs(5.0, [], np.zeros(0), np.zeros(0))[0][0] == pytest.approx(18.0)
