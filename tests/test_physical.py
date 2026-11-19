"""Physical networks checked against analytical results."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    PID,
    Battery,
    Capacitor,
    Constant,
    CurrentSensor,
    DCMotor,
    Diode,
    ElectricalReference,
    HBridge,
    IdealGear,
    Inductor,
    Inertia,
    Resistor,
    RotationalDamper,
    Scope,
    Sine,
    SpeedSensor,
    Sum,
    TemperatureSensor,
    TemperatureSource,
    ThermalMass,
    ThermalResistance,
    VoltageSensor,
    VoltageSource,
)
from nervus.core.errors import ModelError


def _probe(d: Diagram, block, name: str):  # type: ignore[no-untyped-def]
    d.add(block, name=name)
    d.connect(block, d.add(Scope()))
    return block


def test_rc_charging() -> None:
    d = Diagram()
    src = d.add(VoltageSource(V=10.0), name="supply")
    r = d.add(Resistor(R=1000.0), name="R")
    c = d.add(Capacitor(C=1e-3), name="C")
    gnd = d.add(ElectricalReference(), name="gnd")
    vc = _probe(d, VoltageSensor(), "vc")
    d.link((src, "p"), (r, "p"))
    d.link((r, "n"), (c, "p"))
    d.link((c, "n"), (gnd, "p"))
    d.link((src, "n"), (gnd, "p"))
    d.link((vc, "p"), (c, "p"))
    d.link((vc, "n"), (gnd, "p"))
    res = simulate(d, 3.0, solver="RK45", rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(res["vc"], 10 * (1 - np.exp(-res.t)), atol=1e-6)  # tau = R C = 1 s


def test_rlc_series_current() -> None:
    """Series RLC at a 1 V step: underdamped current i(t) = (1/(L wd)) e^(-a t) sin(wd t)."""
    res_ohm, ind_h, cap_f = 2.0, 1.0, 0.25  # a = 1, w0 = 2, wd = sqrt(3)
    d = Diagram()
    src = d.add(VoltageSource(V=1.0), name="V")
    r, ind = d.add(Resistor(R=res_ohm), name="R"), d.add(Inductor(L=ind_h), name="L")
    cap = d.add(Capacitor(C=cap_f), name="C")
    am = _probe(d, CurrentSensor(), "i")
    gnd = d.add(ElectricalReference(), name="gnd")
    d.link((src, "p"), (am, "p"))
    d.link((am, "n"), (r, "p"))
    d.link((r, "n"), (ind, "p"))
    d.link((ind, "n"), (cap, "p"))
    d.link((cap, "n"), (gnd, "p"))
    d.link((src, "n"), (gnd, "p"))
    res = simulate(d, 5.0, solver="RK45", rtol=1e-9, atol=1e-12)
    wd = np.sqrt(3.0)
    expected = np.exp(-res.t) * np.sin(wd * res.t) / (ind_h * wd)
    np.testing.assert_allclose(res["i"], expected, atol=1e-6)


def _motor_rig(d: Diagram, volts):  # type: ignore[no-untyped-def]
    motor = d.add(DCMotor(R=2.0, L=0.01, k=0.1), name="motor")
    rotor = d.add(Inertia(J=1e-4), name="rotor")
    friction = d.add(RotationalDamper(d=1e-4), name="friction")
    speed = _probe(d, SpeedSensor(), "speed")
    gnd = d.add(ElectricalReference(), name="gnd")
    d.link((motor, "shaft"), (rotor, "a"))
    d.link((motor, "shaft"), (friction, "a"))
    d.link((motor, "shaft"), (speed, "a"))
    from nervus.blocks import RotationalReference

    fixed = d.add(RotationalReference(), name="housing")
    d.link((friction, "b"), (fixed, "a"))
    d.link((motor, "n"), (gnd, "p"))
    return motor, gnd


def test_dc_motor_steady_state_speed() -> None:
    d = Diagram()
    motor, gnd = _motor_rig(d, 12.0)
    src = d.add(VoltageSource(V=12.0), name="supply")
    d.link((src, "p"), (motor, "p"))
    d.link((src, "n"), (gnd, "p"))
    res = simulate(d, 2.0, solver="RK45", rtol=1e-8)
    k, r_arm, damping = 0.1, 2.0, 1e-4
    assert res["speed"][-1] == pytest.approx(k * 12.0 / (r_arm * damping + k * k), rel=1e-4)  # 117.6 rad/s


def test_h_bridge_halves_the_voltage() -> None:
    d = Diagram()
    motor, gnd = _motor_rig(d, 12.0)
    bat = d.add(VoltageSource(V=12.0), name="battery")
    bridge = d.add(HBridge(), name="bridge")
    d.connect(d.add(Constant(value=-0.5), name="duty"), bridge)
    d.link((bat, "p"), (bridge, "supply_p"))
    d.link((bat, "n"), (gnd, "p"))
    d.link((bridge, "supply_n"), (gnd, "p"))
    d.link((bridge, "a"), (motor, "p"))
    d.link((bridge, "b"), (gnd, "p"))
    supply = _probe(d, CurrentSensor(), "supply_current")
    d.unlink(next(k for k in d.links if k.a is bat and k.a_port == "p"))
    d.link((bat, "p"), (supply, "p"))
    d.link((supply, "n"), (bridge, "supply_p"))
    res = simulate(d, 2.0, solver="RK45", rtol=1e-8)
    k, r_arm, damping = 0.1, 2.0, 1e-4
    w = res["speed"][-1]
    assert w == pytest.approx(-k * 6.0 / (r_arm * damping + k * k), rel=1e-4)  # reversed, at half the voltage
    motor_current = (-6.0 - k * w) / r_arm
    assert res["supply_current"][-1] == pytest.approx(-0.5 * motor_current, rel=1e-4)  # power balance


def test_gear_reflects_inertia() -> None:
    """A torque on a 1:n gear accelerates the load inertia J as if it were J/n² on the input side."""
    from nervus.blocks import TorqueSource

    d = Diagram()
    torque = d.add(TorqueSource(tau=1.0), name="torque")
    gear = d.add(IdealGear(n=10.0), name="gear")
    load = d.add(Inertia(J=1.0), name="load")
    out = _probe(d, SpeedSensor(), "out_speed")
    d.link((torque, "a"), (gear, "a"))
    d.link((gear, "b"), (load, "a"))
    d.link((out, "a"), (load, "a"))
    # The input side has no inertia of its own: add a tiny one so the input speed is a state.
    tiny = d.add(Inertia(J=1e-6), name="input_inertia")
    d.link((tiny, "a"), (gear, "a"))
    with pytest.raises(ModelError, match="cannot be solved"):
        simulate(d, 1.0)  # two inertias rigidly coupled by the gear: an index problem
    d.remove("input_inertia")
    res = simulate(d, 1.0, solver="rk4", step=0.01)
    assert res["out_speed"][-1] == pytest.approx(10.0 * 1.0 / 1.0, rel=1e-6)  # tau_out = n tau_in = 10 N·m


def test_thermal_cooling() -> None:
    d = Diagram()
    mass = d.add(ThermalMass(C=500.0, T0=90.0), name="block")
    wall = d.add(ThermalResistance(R=0.2), name="to_air")
    air = d.add(TemperatureSource(T=20.0), name="air")
    temp = _probe(d, TemperatureSensor(), "T")
    d.link((mass, "a"), (wall, "a"))
    d.link((wall, "b"), (air, "a"))
    d.link((temp, "a"), (mass, "a"))
    res = simulate(d, 300.0, solver="RK45", rtol=1e-9, atol=1e-10)
    tau = 500.0 * 0.2
    assert res["T"][-1] == pytest.approx(20 + 70 * np.exp(-300 / tau), rel=1e-6)


def test_battery_discharge() -> None:
    d = Diagram()
    bat = d.add(Battery(capacity=60.0, R_internal=0.05, soc0=0.9), name="bat")
    d.connect(bat, d.add(Scope()))
    load = d.add(Resistor(R=1.2), name="load")
    gnd = d.add(ElectricalReference(), name="gnd")
    d.link((bat, "p"), (load, "p"))
    d.link((load, "n"), (gnd, "p"))
    d.link((bat, "n"), (gnd, "p"))
    res = simulate(d, 600.0, solver="rk4", step=1.0)
    ocv = np.interp(0.9, [0, 0.2, 0.5, 0.8, 1.0], [11.6, 11.9, 12.2, 12.5, 12.8])
    i0 = ocv / 1.25
    assert res["bat"][0] == 0.9
    assert (0.9 - res["bat"][-1]) == pytest.approx(i0 * 600 / 3600 / 60.0, rel=0.01)  # 10 A for 10 minutes


def test_diode_half_wave_rectifier() -> None:
    d = Diagram()
    src = d.add(VoltageSource(controlled=True), name="ac")
    d.connect(d.add(Sine(amplitude=5.0, frequency=2 * np.pi * 50), name="mains"), src)
    diode = d.add(Diode(Vf=0.7, R_on=0.01), name="D")
    load = d.add(Resistor(R=100.0), name="load")
    vout = _probe(d, VoltageSensor(), "vout")
    gnd = d.add(ElectricalReference(), name="gnd")
    d.link((src, "p"), (diode, "p"))
    d.link((diode, "n"), (load, "p"))
    d.link((load, "n"), (gnd, "p"))
    d.link((src, "n"), (gnd, "p"))
    d.link((vout, "p"), (load, "p"))
    d.link((vout, "n"), (gnd, "p"))
    res = simulate(d, 0.04, solver="rk4", step=1e-4)
    vin = 5.0 * np.sin(2 * np.pi * 50 * res.t)
    expected = np.where(vin > 0.7, (vin - 0.7) * 100 / 100.01, 0.0)
    np.testing.assert_allclose(res["vout"], expected, atol=1e-3)


def test_speed_control_loop_is_not_algebraic() -> None:
    """A PI controller reads the motor speed and sets the voltage: the speed depends on states only."""
    d = Diagram()
    motor, gnd = _motor_rig(d, 0.0)
    drive = d.add(VoltageSource(controlled=True), name="drive")
    d.link((drive, "p"), (motor, "p"))
    d.link((drive, "n"), (gnd, "p"))
    err = d.add(Sum(signs="+-"), name="error")
    d.connect(d.add(Constant(value=50.0), name="target"), (err, 0))
    d.connect(d.block("speed"), (err, 1))
    pi = d.add(PID(P=0.05, I=1.0, upper=24.0, lower=-24.0), name="pi")
    d.chain(err, pi, drive)
    res = simulate(d, 1.0, solver="RK45")
    assert res["speed"][-1] == pytest.approx(50.0, rel=1e-3)


def test_circuit_without_ground_is_an_error() -> None:
    d = Diagram()
    src, r = d.add(VoltageSource(), name="V"), d.add(Resistor(), name="R")
    d.link((src, "p"), (r, "p"))
    d.link((src, "n"), (r, "n"))
    with pytest.raises(ModelError, match="Electrical Reference"):
        simulate(d, 1.0)


def test_links_are_saved_and_checked() -> None:
    from nervus.io import dumps, loads

    d = Diagram()
    r, c = d.add(Resistor(R=5.0), name="R"), d.add(Capacitor(), name="C")
    d.link((r, "n"), (c, "p"))
    back = loads(dumps(d))
    (link,) = back.links
    assert (link.a.name, link.a_port, link.b.name, link.b_port) == ("R", "n", "C", "p")
    with pytest.raises(ModelError, match="no physical port"):
        d.link((r, "x"), (c, "p"))
    rot = d.add(Inertia(), name="J")
    with pytest.raises(ModelError, match="cannot link"):
        d.link((r, "p"), (rot, "a"))
    d.remove("C")
    assert d.links == []
