"""Reading and writing SPICE netlists."""

import numpy as np
import pytest

from nervus import simulate
from nervus.spice import format_number, parse_number, read_netlist, write_netlist

RECTIFIER = """* Half-wave rectifier with a smoothing capacitor (as exported by LTspice)
V1 in 0 SIN(0 10 50)
D1 in out D1N4007
C1 out 0 100u
R1 out 0 1k
.model D1N4007 D(IS=7n N=1.8 BV=1000 IBV=5u)
.tran 50u 100m
.end
"""

RELAY_DRIVER = """Transistor switch
Vcc vcc 0 DC 12
Vin in 0 PULSE(0 5 1m 1u 1u 2m 4m)
Rb in base 4.7k
Rc vcc col {Rload}
Q1 col base 0 QN
.param Rload=240
.model QN NPN(IS=1e-14 BF=150)
.tran 10u 8m
.end
"""


def test_numbers() -> None:
    assert parse_number("4.7k") == 4700.0
    assert parse_number("10uF") == pytest.approx(1e-5)
    assert parse_number("1meg") == 1e6
    assert parse_number("2.2m") == pytest.approx(2.2e-3)
    assert parse_number("1e-3") == 1e-3
    assert format_number(4700.0) == "4.7k" and format_number(1e-5) == "10u"


def test_rectifier_netlist() -> None:
    d = read_netlist(RECTIFIER, name="rectifier")
    assert d.settings.t_final == pytest.approx(0.1)
    res = simulate(d)
    vout = res["V(out)"]
    late = res.t > 0.06
    # Peak about 10 V minus the diode drop; ripple about I/(f C) = 9 mA / (50 Hz · 100 uF) = 1.8 V.
    assert 8.6 < vout[late].max() < 9.6
    ripple = vout[late].max() - vout[late].min()
    assert 1.2 < ripple < 2.2
    assert np.all(res["V(in)"] <= 10.0 + 1e-9)


def test_transistor_switch_netlist() -> None:
    d = read_netlist(RELAY_DRIVER)
    assert d.workspace["Rload"] == 240.0
    res = simulate(d)
    vc = res["V(col)"]
    on = (res.t > 1.5e-3) & (res.t < 2.8e-3)
    off = res.t < 0.9e-3
    assert vc[off].min() > 11.9  # transistor off: no collector current
    assert vc[on].max() < 0.3  # saturated: the 50 mA load is switched on


def test_write_and_read_back(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = read_netlist(RECTIFIER)
    text = write_netlist(d, tmp_path / "out.cir")
    assert "D1 in out D_D1" in text and ".model D_D1 D(IS=7e-09" in text and "C1 out 0 100u" in text
    assert ".tran 50u 100m" in text
    assert "V1 in 0 SIN(0 10 50)" in text
    again = read_netlist(tmp_path / "out.cir")
    r1, r2 = simulate(read_netlist(RECTIFIER), 0.02), simulate(again, 0.02)
    np.testing.assert_allclose(r2["V(out)"][-1], r1["V(out)"][-1], rtol=1e-6)  # the same circuit
    relay = write_netlist(read_netlist(RELAY_DRIVER))
    assert "PULSE(0 5 1m 0 0 2m 4m)" in relay


def test_file_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "rc.cir"
    f.write_text("RC\nV1 a 0 5\nR1 a b 1k\nC1 b 0 1m\n.tran 1m 5\n.end\n")
    d = read_netlist(f)
    assert d.name == "rc"
    assert simulate(d)["V(b)"][-1] == pytest.approx(5.0 * (1 - np.exp(-5.0)), rel=1e-3)
