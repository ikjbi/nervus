"""Semiconductor devices (Newton-Raphson) checked against hand calculations."""

import math

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    BJT,
    MOSFET,
    CurrentSensor,
    ElectricalReference,
    OpAmp,
    Resistor,
    Scope,
    SemiconductorDiode,
    VoltageSensor,
    VoltageSource,
)

VT = 0.025852


class Circuit:
    """A tiny helper: blocks by name, nets by name (all ports in a net are linked)."""

    def __init__(self) -> None:
        self.d = Diagram()
        self.nets: dict[str, tuple] = {}
        self.gnd = self.d.add(ElectricalReference(), name="gnd")
        self.nets["0"] = (self.gnd, "p")

    def add(self, name: str, block, **pins):  # type: ignore[no-untyped-def]
        self.d.add(block, name=name)
        for port, net in pins.items():
            if net in self.nets:
                self.d.link(self.nets[net], (block, port))
            else:
                self.nets[net] = (block, port)
        return block

    def volt(self, name: str, net: str) -> None:
        self.add(name, VoltageSensor(), p=net, n="0")
        self.d.connect(self.d.block(name), self.d.add(Scope()))

    def run(self):  # type: ignore[no-untyped-def]
        return simulate(self.d, 0.01, solver="rk4", step=0.005)


def test_diode_forward_voltage() -> None:
    c = Circuit()
    c.add("V", VoltageSource(V=5.0), p="in", n="0")
    c.add("R", Resistor(R=1000.0), p="in", n="a")
    c.add("D", SemiconductorDiode(Is=1e-14), p="a", n="0")
    c.volt("vd", "a")
    vd = c.run()["vd"][-1]
    i = (5.0 - vd) / 1000.0
    assert vd == pytest.approx(VT * math.log(i / 1e-14 + 1), abs=1e-6)  # the Shockley equation holds
    assert 0.6 < vd < 0.75


def test_zener_regulates() -> None:
    c = Circuit()
    c.add("V", VoltageSource(V=12.0), p="in", n="0")
    c.add("R", Resistor(R=1000.0), p="in", n="out")
    c.add("Z", SemiconductorDiode(BV=5.1, IBV=1e-3), p="0", n="out")  # reverse biased
    c.volt("vout", "out")
    v = c.run()["vout"][-1]
    assert 5.1 < v < 5.4  # about 6.9 mA through the Zener: a little above BV


def test_bjt_common_emitter_gain() -> None:
    c = Circuit()
    c.add("Vcc", VoltageSource(V=10.0), p="vcc", n="0")
    c.add("Vin", VoltageSource(V=5.0), p="in", n="0")
    c.add("Rb", Resistor(R=100e3), p="in", n="base")
    c.add("Rc", Resistor(R=1000.0), p="vcc", n="col")
    c.add("Q", BJT(BF=100.0), c="col", b="base", e="0")
    c.volt("vb", "base")
    c.volt("vc", "col")
    r = c.run()
    vb, vc = r["vb"][-1], r["vc"][-1]
    ib, ic = (5.0 - vb) / 100e3, (10.0 - vc) / 1000.0
    assert ic / ib == pytest.approx(100.0, rel=0.02)  # active region: Ic = beta Ib
    assert 0.6 < vb < 0.75 and vc > 1.0


def test_pnp_mirror_of_npn() -> None:
    c = Circuit()
    c.add("Vee", VoltageSource(V=-10.0), p="vee", n="0")
    c.add("Vin", VoltageSource(V=-5.0), p="in", n="0")
    c.add("Rb", Resistor(R=100e3), p="in", n="base")
    c.add("Rc", Resistor(R=1000.0), p="vee", n="col")
    c.add("Q", BJT(type="PNP", BF=100.0), c="col", b="base", e="0")
    c.volt("vc", "col")
    assert c.run()["vc"][-1] == pytest.approx(-5.65, abs=0.1)


def test_mosfet_switch_linear_region() -> None:
    c = Circuit()
    c.add("Vdd", VoltageSource(V=10.0), p="vdd", n="0")
    c.add("Vg", VoltageSource(V=5.0), p="gate", n="0")
    c.add("Rd", Resistor(R=100.0), p="vdd", n="drain")
    c.add("M", MOSFET(K=0.1, Vth=2.0), d="drain", g="gate", s="0")
    c.volt("vds", "drain")
    vds = c.run()["vds"][-1]
    i_resistor = (10.0 - vds) / 100.0
    i_fet = 0.1 * ((5.0 - 2.0) * vds - vds * vds / 2)  # linear region (vds < 3 V)
    assert vds < 3.0 and i_resistor == pytest.approx(i_fet, rel=1e-6)


def test_inverting_amplifier_and_saturation() -> None:
    for vin, expected in ((0.5, -5.0), (3.0, -15.0)):
        c = Circuit()
        c.add("Vin", VoltageSource(V=vin), p="in", n="0")
        c.add("R1", Resistor(R=1e3), p="in", n="sum")
        c.add("R2", Resistor(R=10e3), p="sum", n="out")
        c.add("U", OpAmp(), plus="0", minus="sum", out="out")
        c.volt("vout", "out")
        assert c.run()["vout"][-1] == pytest.approx(expected, abs=0.02)


def test_large_resistor_ladder_uses_sparse_solver() -> None:
    """200 resistors in series: the solve switches to sparse matrices, the divider is still exact."""
    c = Circuit()
    c.add("V", VoltageSource(V=1.0), p="n0", n="0")
    for k in range(200):
        c.add(f"R{k}", Resistor(R=1.0), p=f"n{k}", n=f"n{k + 1}" if k < 199 else "0")
    c.volt("mid", "n100")
    assert c.run()["mid"][-1] == pytest.approx(0.5, abs=1e-8)  # GMIN (1e-12 S per node) shifts it by 2.5e-9
    _ = CurrentSensor, np


def test_operating_point_and_dc_sweep() -> None:
    from nervus.circuit import dc_sweep, operating_point

    c = Circuit()
    c.add("Vin", VoltageSource(V=1.0), p="in", n="0")
    c.add("R", Resistor(R=1000.0), p="in", n="a")
    c.add("D", SemiconductorDiode(Is=1e-14), p="a", n="0")
    c.volt("vd", "a")
    op = operating_point(c.d)
    assert op["vd"] == pytest.approx(op["R.n"], abs=1e-9)  # the sensor and the node agree
    assert op["Vin.p"] == pytest.approx(1.0)
    sweep = dc_sweep(c.d, "Vin", "V", np.linspace(0.0, 5.0, 11), ["vd"])
    vd = sweep["vd"]
    assert vd[0] == pytest.approx(0.0, abs=1e-6) and np.all(np.diff(vd) > 0)  # the diode curve rises ...
    assert vd[-1] < 0.72  # ... and flattens out
    assert c.d.block("Vin").params["V"] == 1.0  # the swept parameter is restored
    assert "R.n" in op.table()
