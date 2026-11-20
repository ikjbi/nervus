import numpy as np
import pytest

from nervus import Diagram, ParameterError, compile_diagram, simulate
from nervus.blocks import (
    CompareToConstant,
    Constant,
    DataTypeConversion,
    Gain,
    Integrator,
    Scope,
    Step,
    Sum,
    Switch,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core.datatypes import BOOLEAN, DOUBLE, parse_datatype, round_values


@pytest.mark.parametrize(
    ("text", "name", "lo", "hi"),
    [
        ("int8", "int8", -128, 127),
        ("uint16", "uint16", 0, 65535),
        ("fixdt(1, 16, 8)", "fixdt(1, 16, 8)", -128, 127.99609375),
        ("fixdt(0, 8, 0.5, -40)", "fixdt(0, 8, 0.5, -40.0)", -40, 87.5),
        ("fixdt(1,16,2^-4,0)", "fixdt(1, 16, 4)", -2048, 2047.9375),
    ],
)
def test_parse(text: str, name: str, lo: float, hi: float) -> None:
    t = parse_datatype(text)
    assert t is not None and t.name == name and t.min == lo and t.max == hi


def test_parse_errors() -> None:
    assert parse_datatype("inherit") is None
    for bad in ("int7", "fixdt(1, 64, 0)", "fixdt(1, 16)", "fixdt(1, 16, 0, 0, 0)", "fixdt(1, 8, -1, 0)"):
        with pytest.raises(ParameterError):
            parse_datatype(bad)


def test_rounding_matches_c() -> None:
    x = np.array([-2.5, -1.5, -0.5, 0.49999999999999994, 0.5, 1.5, 2.5])
    np.testing.assert_array_equal(round_values(x, "nearest"), [-3, -2, -1, 0, 1, 2, 3])
    np.testing.assert_array_equal(round_values(x, "zero"), [-2, -1, -0, 0, 0, 1, 2])
    np.testing.assert_array_equal(round_values(x, "floor"), [-3, -2, -1, 0, 0, 1, 2])


def test_saturate_and_wrap() -> None:
    i8 = parse_datatype("int8")
    assert i8 is not None
    np.testing.assert_array_equal(i8.quantize(np.array([200.0, -200.0])), [127, -128])
    np.testing.assert_array_equal(i8.quantize(np.array([200.0, -200.0]), overflow="wrap"), [-56, 56])
    assert parse_datatype("single").quantize(np.array([0.1]))[0] == np.float32(0.1)  # type: ignore[union-attr]
    assert BOOLEAN.quantize(np.array([0.0, -3.0])).tolist() == [0.0, 1.0]


def test_short_names() -> None:
    assert parse_datatype("fixdt(1, 16, 8)").short_name == "sfix16_En8"  # type: ignore[union-attr]
    assert parse_datatype("fixdt(0, 8, 0.5, -40)").short_name == "ufix8_S0.5_B-40"  # type: ignore[union-attr]
    assert parse_datatype("int16").short_name == "int16"  # type: ignore[union-attr]


def _types(d: Diagram) -> dict[str, str]:
    m = compile_diagram(d)
    return {n: str(ts[0]) for n, ts in zip(m.names, m.out_types, strict=True) if ts}


def test_propagation() -> None:
    d = Diagram()
    c = d.add(Constant(value=3.7), name="c")
    dtc = d.add(DataTypeConversion(output_type="int16"), name="dtc")
    g = d.add(Gain(gain=0.5), name="g")  # inherits int16
    s = d.add(Sum(), name="s")  # int16 + double -> double
    cmp_ = d.add(CompareToConstant(constant=1.0), name="cmp")  # boolean
    sw = d.add(Switch(), name="sw")  # type of inputs 0 and 2 only
    d.chain(c, dtc, g)
    d.connect(g, (s, 0))
    d.connect(c, (s, 1))
    d.chain(c, cmp_)
    d.connect(g, (sw, 0))
    d.connect(cmp_, (sw, 1))
    d.connect(dtc, (sw, 2))
    for b in (s, sw):
        d.connect(b, d.add(Scope()))
    assert _types(d) == {"c": "double", "dtc": "int16", "g": "int16", "s": "double", "cmp": "boolean", "sw": "int16"}
    r = simulate(d, 0.0)
    assert r["dtc"][-1] == 4.0 and r["g"][-1] == 2.0  # 3.7 -> 4, 0.5*4 = 2


def test_types_around_a_loop() -> None:
    d = Diagram()
    z = d.add(ZeroOrderHold(sample_time=0.1), name="z")
    dtc = d.add(DataTypeConversion(output_type="int16"), name="dtc")
    s = d.add(Sum(), name="acc")
    ud = d.add(UnitDelay(), name="ud")
    d.chain(d.add(Constant(value=1.4)), z, dtc)
    d.connect(dtc, (s, 0))
    d.connect(ud, (s, 1))
    d.chain(s, ud, d.add(Scope()))
    assert _types(d)["ud"] == "int16"
    r = simulate(d, 1.0)
    np.testing.assert_array_equal(r["ud"], np.arange(11))  # 1.4 -> 1 each step


def test_continuous_blocks_stay_double() -> None:
    d = Diagram()
    dtc = d.add(DataTypeConversion(output_type="int8"), name="dtc")
    i = d.add(Integrator(), name="i")
    d.chain(d.add(Step(time=0.0)), dtc, i, d.add(Scope()))
    assert _types(d)["i"] == "double"


def test_invalid_type_parameter() -> None:
    with pytest.raises(ParameterError):
        Gain(output_type="int128")
    assert DOUBLE.is_double


def test_arithmetic_on_booleans_gives_numbers() -> None:
    from nervus.blocks import CompareToConstant, Constant, Gain, Scope, Sum

    d = Diagram()
    flag = d.add(CompareToConstant(operator=">", constant=0.0), name="flag")
    d.chain(d.add(Constant(value=1.0)), flag)
    g = d.add(Gain(gain=3.0), name="g")
    total = d.add(Sum(signs="++"), name="count")
    d.chain(flag, g, d.add(Scope()))
    d.connect(flag, (total, 0))
    d.connect(flag, (total, 1))
    d.connect(total, d.add(Scope()))
    r = simulate(d, 0.1, solver="rk4", step=0.1)
    assert r["g"][-1] == 3.0 and r["count"][-1] == 2.0
