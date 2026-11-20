"""Adaptive Map: a 2-D table that learns per operating region."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import AdaptiveMap, Constant, FromWorkspace, Inport, Lookup1D, Outport, Scope, Sum


def _learning_loop(true_error):  # type: ignore[no-untyped-def]
    """The map learns the error the controller sees: correction = true error - learned value."""
    d = Diagram("adapt")
    t = [0.0, 10.0, 10.01, 20.0, 20.01, 30.0]
    x = d.add(FromWorkspace(time=t, data=[[1000.0], [1000.0], [4000.0], [4000.0], [1000.0], [1000.0]],
                            interpolation="hold"), name="rpm")  # fmt: skip
    y = d.add(Constant(value=30.0), name="load")
    amap = d.add(AdaptiveMap(row_breakpoints=[1000.0, 4000.0], column_breakpoints=[20.0, 80.0], rate=1.0,
                             limit=20.0, sample_time=0.01), name="ltft")  # fmt: skip
    truth = d.add(Lookup1D(breakpoints=[1000.0, 4000.0], table=list(true_error)), name="err")
    d.connect(x, truth)  # an error that depends on the engine speed
    err = d.add(Sum(signs="+-"), name="residual")
    d.connect(truth, (err, 0))
    d.connect(amap, (err, 1))
    d.connect(x, (amap, 0))
    d.connect(y, (amap, 1))
    d.connect(err, (amap, 2))
    d.connect(d.add(Constant(value=1.0), name="learn"), (amap, 3))
    d.connect(amap, d.add(Scope()))
    return d


def test_learns_each_region_separately() -> None:
    r = simulate(_learning_loop((8.0, -3.0)), 30.0, solver="rk4", step=0.01)
    k10, k20 = np.searchsorted(r.t, [9.99, 19.99])
    assert r["ltft"][k10] == pytest.approx(8.0, abs=0.05)  # learned at 1000 rpm
    assert r["ltft"][k20] == pytest.approx(-3.0, abs=0.05)  # learned at 4000 rpm
    assert r["ltft"][k20 + 3] == pytest.approx(8.0, abs=0.3)  # back at 1000 rpm: the first region was kept


def test_limit_and_no_learning() -> None:
    m = AdaptiveMap(row_breakpoints=[0, 1], column_breakpoints=[0, 1], rate=100.0, limit=2.0)
    m.out_widths = [1]
    x = m.initial_discrete_state()
    zero = np.array([0.0])
    for _ in range(100):
        x = m.update(0.0, [zero, zero, np.array([10.0]), np.array([1.0])], np.zeros(0), x)
    assert x[0] == 2.0 and np.all(x[1:] == 0)  # only the corner cell, limited
    held = m.update(0.0, [zero, zero, np.array([10.0]), np.array([0.0])], np.zeros(0), x)
    assert np.array_equal(held, x)


def test_adaptive_map_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("am")
    ins = [d.add(Inport(port=k + 1), name=n) for k, n in enumerate(("x", "y", "e", "learn"))]
    amap = d.add(AdaptiveMap(row_breakpoints=[0.0, 1.0, 3.0], column_breakpoints=[10.0, 20.0], rate=2.0, limit=5.0,
                             sample_time=0.01), name="map")  # fmt: skip
    for k, i in enumerate(ins):
        d.connect(i, (amap, k))
    d.connect(amap, d.add(Outport(port=1), name="out"))
    k = np.arange(300)
    inputs = {"x": 1.5 + 1.4 * np.sin(k / 20), "y": 15 + 6 * np.cos(k / 13), "e": 3 * np.sin(k / 7),
              "learn": (k % 50 < 40).astype(float)}  # fmt: skip
    sil = back_to_back(d, inputs, 300, tolerance=1e-12, folder=tmp_path)
    assert sil.passed, sil.summary()
