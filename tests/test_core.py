import math

import numpy as np
import pytest

from nervus import Diagram, ModelError, ParameterError
from nervus.blocks import Constant, Gain, Integrator, Scope, Sum
from nervus.core import Param, ParamKind, SampleTime, Severity
from nervus.core.block import broadcast_widths
from nervus.core.params import to_jsonable


class TestParams:
    def test_float_and_limits(self) -> None:
        p = Param("x", 1.0, ParamKind.FLOAT, min=0.0)
        assert p.coerce("2.5") == 2.5
        with pytest.raises(ParameterError):
            p.coerce(-1)
        with pytest.raises(ParameterError):
            p.coerce("abc")

    def test_int(self) -> None:
        p = Param("n", 1, ParamKind.INT)
        assert p.coerce(3.0) == 3
        with pytest.raises(ParameterError):
            p.coerce(2.5)

    def test_bool(self) -> None:
        p = Param("b", False, ParamKind.BOOL)
        assert p.coerce("yes") is True
        assert p.coerce("off") is False
        with pytest.raises(ParameterError):
            p.coerce("maybe")

    def test_array(self) -> None:
        p = Param("a", 0.0, ParamKind.ARRAY)
        np.testing.assert_array_equal(p.coerce([[1, 2], [3, 4]]), [[1, 2], [3, 4]])
        assert p.coerce(["inf", 1.0])[0] == math.inf
        with pytest.raises(ParameterError):
            p.coerce(np.zeros((2, 2, 2, 2, 2)))  # up to 4-D (n-D lookup tables)

    def test_choice(self) -> None:
        p = Param("c", "a", ParamKind.CHOICE, choices=("a", "b"))
        assert p.coerce("b") == "b"
        with pytest.raises(ParameterError):
            p.coerce("z")

    def test_jsonable(self) -> None:
        assert to_jsonable(np.array([1.0, math.inf])) == [1.0, "inf"]
        assert to_jsonable(-math.inf) == "-inf"

    def test_block_rejects_unknown_param(self) -> None:
        with pytest.raises(ParameterError, match="no parameter"):
            Gain(gian=2)

    def test_set_param_keeps_old_value_on_failure(self) -> None:
        s = Sum(signs="++")
        with pytest.raises(ParameterError):
            s.set_param("signs", "+x")
        assert s.params["signs"] == "++"


class TestSampleTime:
    @pytest.mark.parametrize(
        ("value", "attr"),
        [
            (0, "is_continuous"),
            (-1, "is_inherited"),
            (math.inf, "is_constant"),
            (0.1, "is_discrete"),
        ],
    )
    def test_kinds(self, value: float, attr: str) -> None:
        assert getattr(SampleTime.from_value(value), attr)

    def test_offset(self) -> None:
        st = SampleTime.from_value([0.1, 0.05])
        assert st.period == 0.1 and st.offset == 0.05
        with pytest.raises(ParameterError):
            SampleTime.from_value([0.1, 0.2])
        with pytest.raises(ParameterError):
            SampleTime.from_value(-2)


def test_broadcast_widths() -> None:
    assert broadcast_widths([1, 3, None]) == 3
    assert broadcast_widths([None]) is None
    assert broadcast_widths([1, 1]) == 1
    with pytest.raises(ValueError):
        broadcast_widths([2, 3])


class TestDiagram:
    def test_unique_names(self) -> None:
        d = Diagram()
        a = d.add(Gain())
        b = d.add(Gain())
        c = d.add(Gain())
        assert (a.name, b.name, c.name) == ("Gain", "Gain1", "Gain2")

    def test_duplicate_name(self) -> None:
        d = Diagram()
        d.add(Gain(), name="g")
        with pytest.raises(ModelError):
            d.add(Gain(), name="g")

    def test_block_in_two_diagrams(self) -> None:
        g = Gain()
        Diagram().add(g)
        with pytest.raises(ModelError):
            Diagram().add(g)

    def test_connect_twice_to_same_input(self) -> None:
        d = Diagram()
        a, b, g = d.add(Constant()), d.add(Constant()), d.add(Gain())
        d.connect(a, g)
        with pytest.raises(ModelError, match="already driven"):
            d.connect(b, g)

    def test_connect_bad_port(self) -> None:
        d = Diagram()
        a, g = d.add(Constant()), d.add(Gain())
        with pytest.raises(IndexError):
            d.connect(a, (g, 3))

    def test_connect_foreign_block(self) -> None:
        d = Diagram()
        a = d.add(Constant())
        with pytest.raises(ModelError):
            d.connect(a, Gain())

    def test_remove_drops_connections(self) -> None:
        d = Diagram()
        a, g, s = d.add(Constant()), d.add(Gain()), d.add(Scope())
        d.chain(a, g, s)
        removed = d.remove(g)
        assert len(removed) == 2
        assert d.connections == []
        assert g.diagram is None

    def test_rename(self) -> None:
        d = Diagram()
        a = d.add(Constant(), name="a")
        d.add(Gain(), name="g")
        d.rename(a, "source")
        assert d.block("source") is a
        assert [b.name for b in d] == ["source", "g"]
        with pytest.raises(ModelError):
            d.rename(a, "g")

    def test_check(self) -> None:
        d = Diagram()
        d.add(Gain(), name="g")
        issues = d.check()
        assert any(i.severity is Severity.ERROR and "input 0" in i.message for i in issues)
        assert any(i.severity is Severity.WARNING and "output 0" in i.message for i in issues)

    def test_check_dangling_after_port_change(self) -> None:
        d = Diagram()
        a, b, c = d.add(Constant()), d.add(Constant()), d.add(Sum(signs="++"))
        d.connect(a, (c, 0))
        d.connect(b, (c, 1))
        c.set_param("signs", "+")
        assert any("dangling" in i.message for i in d.check())

    def test_integrator_block_metadata(self) -> None:
        assert Integrator.type_id == "continuous.integrator"
        assert Integrator.__doc__


def test_auto_layout_places_blocks_left_to_right(first_order: Diagram) -> None:
    from nervus.core.layout import auto_layout

    assert auto_layout(first_order) == 5
    x = {b.name: b.meta["position"][0] for b in first_order}
    assert x["u"] < x["err"] < x["k"] < x["y"] < x["scope"]  # the y -> err feedback is ignored
    positions = [tuple(b.meta["position"]) for b in first_order]
    assert len(set(positions)) == len(positions)
    assert auto_layout(first_order) == 0  # nothing missing any more
