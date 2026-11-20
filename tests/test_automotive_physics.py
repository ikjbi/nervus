"""Automotive electrical components and hydraulics, checked against hand calculations."""

import math

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    Alternator,
    Battery,
    CurrentSensor,
    ElectricalReference,
    FlowSensor,
    FlowSource,
    FuelInjector,
    GlowPlug,
    HydraulicReference,
    HydraulicVolume,
    Orifice,
    PressureSensor,
    RelayContact,
    Resistor,
    Scope,
    SpeedSource,
    Step,
    TemperatureSource,
    TorqueSensor,
    VoltageSource,
)


def _log(d: Diagram, block, port: int = 0) -> None:  # type: ignore[no-untyped-def]
    d.connect((block, port), d.add(Scope()))


def test_injector_opening_delay() -> None:
    d = Diagram()
    gnd = d.add(ElectricalReference(), name="gnd")
    drive = d.add(VoltageSource(controlled=True), name="ecu")
    d.connect(d.add(Step(time=1e-3, final=12.0)), drive)
    inj = d.add(FuelInjector(R=12.0, L=0.01, I_pull=0.6, I_drop=0.3, tau=0.2e-3), name="inj")
    d.link((drive, "p"), (inj, "p"))
    d.link((inj, "n"), (gnd, "p"))
    d.link((drive, "n"), (gnd, "p"))
    _log(d, inj, 0)
    _log(d, inj, 1)
    res = simulate(d, 5e-3, solver="rk4", step=1e-6)
    t_pull = 1e-3 + 0.01 / 12.0 * -math.log(1 - 0.6)  # the current reaches 0.6 A of its final 1 A: 0.76 ms
    lift = res["inj"]
    assert np.interp(t_pull - 0.1e-3, res.t, lift) < 0.01  # still closed just before
    assert np.interp(t_pull + 1.0e-3, res.t, lift) > 0.99  # open after the armature travel
    assert res["inj:1"][-1] == pytest.approx(3.5, rel=1e-3)  # full static flow


def test_relay_switches_a_lamp() -> None:
    d = Diagram()
    gnd = d.add(ElectricalReference(), name="gnd")
    bat = d.add(VoltageSource(V=12.0), name="bat")
    coil_drive = d.add(VoltageSource(controlled=True), name="switch")
    d.connect(d.add(Step(time=0.01, final=12.0)), coil_drive)
    relay = d.add(RelayContact(), name="relay")
    lamp = d.add(Resistor(R=2.4), name="lamp")  # a 60 W lamp
    amp = d.add(CurrentSensor(), name="lamp_current")
    for a, b in (((coil_drive, "p"), (relay, "p")), ((relay, "n"), (gnd, "p")), ((coil_drive, "n"), (gnd, "p")),
                 ((bat, "p"), (relay, "a")), ((relay, "b"), (amp, "p")), ((amp, "n"), (lamp, "p")),
                 ((lamp, "n"), (gnd, "p")), ((bat, "n"), (gnd, "p"))):  # fmt: skip
        d.link(a, b)
    _log(d, amp)
    _log(d, relay)
    res = simulate(d, 0.05, solver="rk4", step=1e-5)
    assert res["lamp_current"][res.t < 0.009].max() < 1e-3
    assert res["lamp_current"][-1] == pytest.approx(5.0, rel=1e-2)  # 12 V / 2.4 Ω
    closed_at = res.t[np.argmax(res["relay"] > 0.5)]
    assert 0.01 < closed_at < 0.02  # the coil current needs a few ms to reach the pull-in current


def test_glow_plug_steady_temperature() -> None:
    d = Diagram()
    gnd = d.add(ElectricalReference(), name="gnd")
    bat = d.add(VoltageSource(V=11.0), name="bat")
    plug = d.add(GlowPlug(R0=0.5, alpha=0.006, C=3.0, R_th=25.0), name="plug")
    head = d.add(TemperatureSource(T=20.0), name="head")
    d.link((bat, "p"), (plug, "p"))
    d.link((plug, "n"), (gnd, "p"))
    d.link((bat, "n"), (gnd, "p"))
    d.link((plug, "case"), (head, "a"))
    _log(d, plug)
    res = simulate(d, 1000.0, solver="BDF")  # thermal time constant C·R_th = 75 s
    temp = res["plug"][-1]
    r = 0.5 * (1 + 0.006 * (temp - 20))
    assert 11.0**2 / r == pytest.approx((temp - 20) / 25.0, rel=1e-3)  # heating = losses
    assert 800 < temp < 1200
    early = res["plug"][np.searchsorted(res.t, 2.0)]
    assert early > 100  # a glow plug is hot within seconds


def test_alternator_regulates_and_loads_the_engine() -> None:
    d = Diagram()
    gnd = d.add(ElectricalReference(), name="gnd")
    bat = d.add(Battery(soc0=0.8, R_internal=0.01), name="battery")
    load = d.add(Resistor(R=0.5), name="loads")  # about 28 A at 14 V
    alt = d.add(Alternator(), name="alt")
    engine = d.add(SpeedSource(w=2000 * 2 * math.pi / 60), name="engine")
    belt = d.add(TorqueSensor(), name="belt_torque")
    for a, b in (((bat, "p"), (alt, "p")), ((load, "p"), (alt, "p")), ((alt, "n"), (gnd, "p")),
                 ((bat, "n"), (gnd, "p")), ((load, "n"), (gnd, "p")), ((engine, "a"), (belt, "a")),
                 ((belt, "b"), (alt, "shaft"))):  # fmt: skip
        d.link(a, b)
    vs = d.add(__import__("nervus.blocks", fromlist=["VoltageSensor"]).VoltageSensor(), name="v_bat")
    d.link((vs, "p"), (bat, "p"))
    d.link((vs, "n"), (gnd, "p"))
    for blk in (vs, alt, belt):
        _log(d, blk)
    res = simulate(d, 2.0, solver="BDF")
    v, i, tau = res["v_bat"][-1], res["alt"][-1], res["belt_torque"][-1]
    assert v == pytest.approx(14.2 - i / 50.0, abs=0.05)  # held near the set point (proportional regulator)
    w = 2000 * 2 * math.pi / 60
    assert tau == pytest.approx(v * i / (0.6 * w), rel=1e-3)  # the electrical power comes from the engine


def test_fuel_rail_pressure() -> None:
    """An electric pump feeds the rail; a regulator returns the excess to the tank above 4 bar."""
    d = Diagram()
    tank = d.add(HydraulicReference(), name="tank")
    pump = d.add(FlowSource(Q=1.5), name="pump")
    rail = d.add(HydraulicVolume(V=0.05, beta=5000.0), name="rail")
    from nervus.blocks import ReliefValve

    reg = d.add(ReliefValve(p_crack=4.0, k=20.0), name="regulator")
    injectors = d.add(Orifice(q1=0.2), name="injectors")
    pressure = d.add(PressureSensor(), name="p_rail")
    injected = d.add(FlowSensor(), name="q_injected")
    for a, b in (((tank, "a"), (pump, "a")), ((pump, "b"), (rail, "a")), ((rail, "a"), (reg, "a")),
                 ((reg, "b"), (tank, "a")), ((rail, "a"), (injected, "a")), ((injected, "b"), (injectors, "a")),
                 ((injectors, "b"), (tank, "a")), ((pressure, "a"), (rail, "a"))):  # fmt: skip
        d.link(a, b)
    _log(d, pressure)
    _log(d, injected)
    res = simulate(d, 1.0, solver="BDF")
    p = res["p_rail"][-1]
    q_inj = res["q_injected"][-1]
    assert 4.0 < p < 4.1  # just above the cracking pressure
    assert q_inj == pytest.approx(0.2 * p / math.sqrt(p + 0.01), rel=1e-6)  # turbulent: q ~ sqrt(dp)
