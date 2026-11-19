"""Electronic circuits, the way they are simulated in LTspice.

Four classic circuits an automotive engineer meets, each saved as a model:

* ``rectifier.nervus``: a half-wave rectifier with a smoothing capacitor, read from a SPICE netlist. The
  capacitor charges to the peak minus the diode drop and sags between the peaks (ripple ≈ I / (f C)).
* ``relay_driver.nervus``: a transistor switching a relay coil, like an ECU output stage. When the transistor
  switches off, the coil's current has nowhere to go: without the freewheeling diode the collector voltage
  shoots up (the inductive kick, L di/dt) until the transistor breaks down (here at 60 V), which wears it out;
  with the diode it is clamped one diode drop above the supply.
* ``buck_converter.nervus``: a DC/DC converter from 12 V down to about 5 V: a switch at 20 kHz, a diode, an
  inductor and a capacitor. The output is the duty cycle times the input, V_out ≈ D · V_in.
* ``active_filter.nervus``: a second-order Sallen-Key low-pass filter with an op-amp, cut-off 1 kHz;
  analyse it with Linear Analysis (Bode plot) from its In block to its Out block.

Run with ``uv run python examples/circuits.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    BJT,
    Capacitor,
    Diode,
    ElectricalReference,
    ElectricalSwitch,
    Inductor,
    Inport,
    OpAmp,
    Outport,
    Pulse,
    Resistor,
    Scope,
    SemiconductorDiode,
    VoltageSensor,
    VoltageSource,
)
from nervus.core import Check, TestCase
from nervus.spice import read_netlist

HERE = Path(__file__).parent

RECTIFIER_NETLIST = """* Half-wave rectifier with a smoothing capacitor
V1 in 0 SIN(0 10 50)
D1 in out D1N4007
C1 out 0 100u
R1 out 0 1k
.model D1N4007 D(IS=7n N=1.8 BV=1000 IBV=5u)
.tran 50u 100m
.end
"""


class Net:
    """Build a circuit by net names: every port on a net is linked."""

    def __init__(self, d: Diagram) -> None:
        self.d = d
        self.first: dict[str, tuple] = {}
        self.gnd = d.add(ElectricalReference(), name="gnd")
        self.first["0"] = (self.gnd, "p")

    def part(self, name: str, block, **pins):  # type: ignore[no-untyped-def]
        self.d.add(block, name=name)
        for port, net in pins.items():
            if net in self.first:
                self.d.link(self.first[net], (block, port))
            else:
                self.first[net] = (block, port)
        return block

    def probe(self, name: str, net: str):  # type: ignore[no-untyped-def]
        return self.part(name, VoltageSensor(), p=net, n="0")


def _grid(d: Diagram, cols: int = 5) -> None:
    for k, b in enumerate(d.blocks):
        b.meta["position"] = [float(170 * (k % cols)), float(120 * (k // cols))]


def rectifier() -> Diagram:
    d = read_netlist(RECTIFIER_NETLIST, name="rectifier")
    d.connect(d.block("V(out)"), d.add(Scope(), name="scope"))
    d.tests = [
        TestCase(
            "smoothed output",
            "The capacitor holds the output near the peak: about 9 V with less than 2 V of ripple",
            stop_time=0.1,
            checks=[Check("bounds", "V(out)", {"lower": 7.0, "upper": 9.6, "t_from": 0.06, "t_to": 0.1})],
        )
    ]
    _grid(d, 4)
    return d


def relay_driver(flyback: bool = True) -> Diagram:
    d = Diagram("relay_driver")
    d.settings.t_final = 0.02
    d.settings.solver = "BDF"  # stiff: the coil against a switched-off transistor (like LTspice, an implicit method)
    d.settings.max_step = 2e-5
    n = Net(d)
    n.part("battery", VoltageSource(V=12.0), p="vbat", n="0")
    n.part("ecu_output", VoltageSource(controlled=True), p="drive", n="0")
    d.connect(d.add(Pulse(amplitude=5.0, period=0.02, duty=50.0, delay=0.002), name="command"), d.block("ecu_output"))
    n.part("R_base", Resistor(R=2.2e3), p="drive", n="base")
    n.part("coil_R", Resistor(R=80.0), p="vbat", n="coil")  # a 12 V relay coil: 80 Ω, 0.1 H
    n.part("coil_L", Inductor(L=0.1), p="coil", n="col")
    n.part("Q1", BJT(BF=150.0), c="col", b="base", e="0")
    if flyback:
        n.part("D_flyback", SemiconductorDiode(Is=2.5e-9, N=1.75), p="col", n="vbat")
    else:  # a real transistor avalanches: its collector-emitter breakdown at 60 V
        n.part("Q1_breakdown", SemiconductorDiode(Is=1e-14, BV=60.0, IBV=1e-3), p="0", n="col")
    n.probe("V(col)", "col")
    d.connect(d.block("V(col)"), d.add(Scope(), name="scope"))
    d.connect(d.block("V(col)"), d.add(Outport(port=1), name="collector"))
    d.tests = [
        TestCase(
            "collector clamped by the freewheeling diode",
            "When the transistor switches off, the coil's current flows through the diode: V(col) stays below 13 V",
            stop_time=0.02,
            checks=[
                Check("bounds", "collector", {"lower": -0.5, "upper": 13.0}),
                Check("bounds", "collector", {"lower": 0.0, "upper": 0.4, "t_from": 0.005, "t_to": 0.011}),
            ],
        )
    ]
    _grid(d)
    return d


def buck_converter() -> Diagram:
    d = Diagram("buck_converter")
    d.settings.t_final = 0.005
    # Stiff (the coil against an open switch and a blocking diode), so an implicit method like LTspice's. The
    # switching instants come from the PWM source; the ideal switch and diode need no zero-crossing search.
    d.settings.solver = "BDF"
    d.settings.max_step = 2e-6
    d.settings.zero_crossing = False
    n = Net(d)
    n.part("V_in", VoltageSource(V=12.0), p="vin", n="0")
    n.part("S1", ElectricalSwitch(R_on=0.05), p="vin", n="sw")
    d.connect(d.add(Pulse(amplitude=1.0, period=50e-6, duty=42.0, sample_time=0.0), name="pwm_20kHz"), d.block("S1"))
    n.part("D1", Diode(Vf=0.4, R_on=0.02), p="0", n="sw")  # Schottky freewheeling diode
    n.part("L1", Inductor(L=100e-6), p="sw", n="out")
    n.part("C1", Capacitor(C=100e-6), p="out", n="0")
    n.part("R_load", Resistor(R=5.0), p="out", n="0")
    n.probe("V(out)", "out")
    d.connect(d.block("V(out)"), d.add(Scope(), name="scope"))
    d.connect(d.block("V(out)"), d.add(Outport(port=1), name="vout"))
    d.tests = [
        TestCase(
            "about 5 V out",
            "Duty cycle 42 % of 12 V, minus the losses: the output settles near 5 V",
            stop_time=0.005,
            checks=[Check("bounds", "vout", {"lower": 4.3, "upper": 5.3, "t_from": 0.003, "t_to": 0.005})],
        )
    ]
    _grid(d)
    return d


def active_filter(fc: float = 1000.0) -> Diagram:
    """Unity-gain Sallen-Key low-pass: R1 = R2 = R, C1 = 2 C2, Q = 0.707 (Butterworth)."""
    d = Diagram("active_filter")
    d.settings.t_final = 0.005
    d.settings.solver = "auto"
    d.settings.max_step = 1e-5
    r = 10e3
    c2 = 1.0 / (2 * math.pi * fc * r * math.sqrt(2.0))
    c1 = 2 * c2
    n = Net(d)
    n.part("V_in", VoltageSource(controlled=True), p="in", n="0")
    d.connect(d.add(Inport(port=1, value=0.0), name="u"), d.block("V_in"))
    n.part("R1", Resistor(R=r), p="in", n="a")
    n.part("R2", Resistor(R=r), p="a", n="b")
    n.part("C1", Capacitor(C=c1), p="a", n="out")
    n.part("C2", Capacitor(C=c2), p="b", n="0")
    n.part("U1", OpAmp(Vpos=12.0, Vneg=-12.0), plus="b", minus="out", out="out")
    n.probe("V(out)", "out")
    d.connect(d.block("V(out)"), d.add(Outport(port=1), name="y"))
    _grid(d)
    return d


def main() -> dict[str, SimResult]:
    from nervus.analysis import linearize
    from nervus.testing import run_tests

    results = {}
    for build in (rectifier, relay_driver, buck_converter):
        d = build()
        save(d, HERE / f"{d.name}.nervus")
        for r in run_tests(d):
            print(r.summary())
        results[d.name] = simulate(d)
    kick = simulate(relay_driver(flyback=False))
    print(f"relay driver: V(col) peak {results['relay_driver']['V(col)'].max():.1f} V with the diode, "
          f"{kick['V(col)'].max():.0f} V without")  # fmt: skip
    f = active_filter()
    save(f, HERE / "active_filter.nervus")
    lin = linearize(f)
    _w, mag, _ = lin.bode(np.array([2 * math.pi * 100, 2 * math.pi * 1000, 2 * math.pi * 10000]))
    print("active filter: gain at 100 Hz, 1 kHz, 10 kHz = " + ", ".join(f"{m:.1f} dB" for m in mag))
    return results


if __name__ == "__main__":
    main()
