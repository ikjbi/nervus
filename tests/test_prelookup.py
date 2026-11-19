import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Inport, Interpolation, Lookup1D, Lookup2D, Outport, Prelookup, Ramp, Scope, ZeroOrderHold

SPEED = [800.0, 1500.0, 3000.0, 6000.0]
LOAD = [0.2, 0.5, 1.0]
MAP = [[10.0, 8.0, 5.0], [20.0, 16.0, 10.0], [30.0, 25.0, 18.0], [35.0, 30.0, 22.0]]


@pytest.mark.parametrize("extrap", ["clip", "linear"])
def test_prelookup_matches_lookup_tables(extrap: str) -> None:
    d = Diagram()
    rpm = d.add(Ramp(slope=1000.0, start_time=0.0, initial=0.0), name="rpm")  # 0 .. 7000 rpm
    load = d.add(Ramp(slope=0.15, initial=0.1), name="load")  # 0.1 .. 1.15
    pr, pl = (
        d.add(Prelookup(breakpoints=SPEED, extrapolation=extrap), name="pr"),
        d.add(Prelookup(breakpoints=LOAD, extrapolation=extrap), name="pl"),
    )
    ign = d.add(Interpolation(dimensions=2, table=MAP), name="ign")
    curve = d.add(Interpolation(dimensions=1, table=[1.0, 2.0, 4.0, 8.0]), name="curve")
    ref2 = d.add(Lookup2D(row_breakpoints=SPEED, column_breakpoints=LOAD, table=MAP, extrapolation=extrap), name="ref2")
    ref1 = d.add(Lookup1D(breakpoints=SPEED, table=[1.0, 2.0, 4.0, 8.0], extrapolation=extrap), name="ref1")
    d.chain(rpm, pr)
    d.chain(load, pl)
    for k, (src, port) in enumerate(((pr, 0), (pr, 1), (pl, 0), (pl, 1))):
        d.connect((src, port), (ign, k))
    d.connect((pr, 0), (curve, 0))
    d.connect((pr, 1), (curve, 1))
    d.connect(rpm, (ref2, 0))
    d.connect(load, (ref2, 1))
    d.connect(rpm, ref1)
    for b in (ign, curve, ref1, ref2):
        d.connect(b, d.add(Scope()))
    r = simulate(d, 7.0, solver="rk4", step=0.05)
    np.testing.assert_allclose(r["ign"], r["ref2"], atol=1e-12)
    np.testing.assert_allclose(r["curve"], r["ref1"], atol=1e-12)


def test_prelookup_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("pre")
    rpm, load = d.add(Inport(port=1), name="rpm"), d.add(Inport(port=2), name="load")
    z1, z2 = d.add(ZeroOrderHold(sample_time=0.01)), d.add(ZeroOrderHold(sample_time=0.01))
    pr, pl = d.add(Prelookup(breakpoints=SPEED, extrapolation="linear")), d.add(Prelookup(breakpoints=LOAD))
    ign = d.add(Interpolation(dimensions=2, table=MAP), name="ign")
    curve = d.add(Interpolation(table=[1.0, 2.0, 4.0, 8.0]), name="curve")
    d.chain(rpm, z1, pr)
    d.chain(load, z2, pl)
    for k, (src, port) in enumerate(((pr, 0), (pr, 1), (pl, 0), (pl, 1))):
        d.connect((src, port), (ign, k))
    d.connect((pr, 0), (curve, 0))
    d.connect((pr, 1), (curve, 1))
    d.connect(ign, d.add(Outport(port=1), name="advance"))
    d.connect(curve, d.add(Outport(port=2), name="c"))
    k = np.arange(100)
    res = back_to_back(d, {"rpm": 70.0 * k, "load": 0.012 * k}, 100, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()


def test_table_from_workspace_expression() -> None:
    """A 2-D table given as a workspace name is validated after it is resolved, not with the 1-D default."""
    d = Diagram()
    d.workspace["ign_map"] = MAP
    ign = d.add(Interpolation(dimensions=2, table="ign_map"), name="ign")
    np.testing.assert_array_equal(ign.params["table"], MAP)
    standalone = Interpolation(dimensions=2, table="not_defined_yet")  # no model yet: validated later
    assert standalone.expressions["table"] == "not_defined_yet"
