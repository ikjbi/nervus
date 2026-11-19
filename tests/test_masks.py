import numpy as np
import pytest

from nervus import Diagram, ModelError, simulate
from nervus.blocks import Constant, Gain, Inport, Outport, Scope, Subsystem
from nervus.core import Variable
from nervus.io import dumps, loads


def scaled(k_expr: str = "K") -> Subsystem:
    inner = Diagram()
    u = inner.add(Inport(port=1), name="u")
    g = inner.add(Gain(gain=k_expr), name="gain")
    inner.chain(u, g, inner.add(Outport(port=1), name="y"))
    sub = Subsystem(system=inner)
    sub.mask.add(Variable("K", 2.0, "Scale factor"))
    sub.mask_icon = "×K"
    return sub


def model() -> Diagram:
    d = Diagram()
    d.workspace["base"] = 10.0
    c = d.add(Constant(value=1.0), name="c")
    a = d.add(scaled(), name="a")
    b = d.add(scaled(), name="b")
    b.mask["K"] = "3 * base"  # mask values can use the model workspace
    d.chain(c, a, d.add(Scope()))
    d.chain(c, b, d.add(Scope()))
    return d


def test_two_instances_different_mask_values() -> None:
    r = simulate(model(), 0.0)
    assert r["a/gain"][-1] == 2.0
    assert r["b/gain"][-1] == 30.0
    assert simulate(model(), 0.0, params={"base": 1.0})["b/gain"][-1] == 3.0


def test_mask_shadows_workspace_and_errors() -> None:
    d = model()
    d.workspace["K"] = 99.0
    assert simulate(d, 0.0)["a/gain"][-1] == 2.0  # the mask's K wins inside the subsystem
    d.block("a").mask["K"] = "nope * 2"
    with pytest.raises(ModelError, match="mask of 'a'"):
        simulate(d, 0.0)


def test_nested_masks() -> None:
    d = Diagram()
    inner = scaled("K * M")
    outer_sys = Diagram()
    i = outer_sys.add(Inport(port=1), name="i")
    s = outer_sys.add(inner, name="inner")
    outer_sys.chain(i, s, outer_sys.add(Outport(port=1), name="o"))
    outer = d.add(Subsystem(system=outer_sys), name="outer")
    outer.mask.add(Variable("M", 5.0))
    d.chain(d.add(Constant(value=1.0)), outer, d.add(Scope()))
    assert simulate(d, 0.0)["outer/inner/gain"][-1] == 10.0  # K=2 (inner mask) * M=5 (outer mask)


def test_mask_roundtrip() -> None:
    again = loads(dumps(model()))
    b = again.block("b")
    assert isinstance(b, Subsystem) and b.mask.variable("K").value == "3 * base"
    assert b.mask_icon == "×K" and b.mask.variable("K").description == "Scale factor"
    np.testing.assert_allclose(simulate(again, 0.0)["b/gain"], [30.0])
