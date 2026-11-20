"""Cranking an engine: battery, starter relay, starter motor and the engine's compression.

When the key turns to *start*, the starter relay connects the starter motor to the battery. At standstill the
motor has no back-EMF, so the current is limited only by the resistances: several hundred amperes. The battery
voltage collapses (its internal resistance), which is why ECUs must keep working down to about 6-8 V
(*cranking* in ISO 16750-2). As the engine turns, the motor's back-EMF reduces the current; each compression
stroke slows the crankshaft, so speed and current ripple at the firing frequency.

* battery: 12.6 V open circuit, 10 mΩ internal resistance;
* starter motor: 20 mΩ, 0.02 N·m/A, geared 1:12 onto the flywheel; its rotor's inertia is lumped with the
  engine's (reflected through the gear);
* engine: inertia, friction, and a compression torque that depends on the crank angle (4 cylinders: two
  compressions per revolution).

Run with ``uv run python examples/starter_motor.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    AngleSensor,
    Battery,
    CurrentSensor,
    DCMotor,
    ElectricalReference,
    Gain,
    IdealGear,
    Inertia,
    PythonFunction,
    RelayContact,
    RotationalDamper,
    RotationalReference,
    Scope,
    SpeedSensor,
    Step,
    TorqueSource,
    VoltageSensor,
    VoltageSource,
)
from nervus.core import Check, TestCase

HERE = Path(__file__).parent
RPM = 60 / (2 * math.pi)

COMPRESSION = '''def f(t, phi):
    """Compression torque [N·m] of a 4-cylinder engine at crank angle phi: two peaks per revolution."""
    return p[0] * max(0.0, math.sin(2 * phi)) ** 2 + p[1]
'''


def build() -> Diagram:
    d = Diagram("starter_motor")
    d.settings.t_final = 1.5
    d.settings.solver = "BDF"
    d.settings.max_step = 2e-3
    gnd = d.add(ElectricalReference(), name="gnd")
    battery = d.add(Battery(capacity=60.0, R_internal=0.010, soc0=0.95), name="battery")
    key = d.add(Step(time=0.2, final=12.0), name="key_start")
    key_line = d.add(VoltageSource(controlled=True), name="ignition_switch")
    relay = d.add(RelayContact(R=4.0, L=0.02, I_pull=1.5, I_drop=0.5, tau=5e-3, R_contact=2e-3), name="starter_relay")
    amps = d.add(CurrentSensor(), name="starter_current")
    vbat = d.add(VoltageSensor(), name="battery_voltage")
    motor = d.add(DCMotor(R=0.020, L=50e-6, k=0.02), name="starter_motor")
    pinion = d.add(IdealGear(n=12.0), name="pinion_ring_gear")
    engine = d.add(Inertia(J=0.15 + 12**2 * 2e-4), name="crankshaft")  # engine + reflected starter rotor
    friction = d.add(RotationalDamper(d=0.5), name="engine_friction")
    block = d.add(RotationalReference(), name="engine_block")
    angle = d.add(AngleSensor(), name="crank_angle")
    speed = d.add(SpeedSensor(), name="crank_speed")
    compression = d.add(PythonFunction(code=COMPRESSION, num_inputs=1, parameters="[90.0, 0.0]"), name="compression")
    load = d.add(TorqueSource(controlled=True), name="compression_torque")
    negate = d.add(Gain(gain=-1.0), name="opposes_rotation")
    for a, b in (((battery, "p"), (relay, "a")), ((relay, "b"), (amps, "p")), ((amps, "n"), (motor, "p")),
                 ((motor, "n"), (gnd, "p")), ((battery, "n"), (gnd, "p")), ((key_line, "p"), (relay, "p")),
                 ((key_line, "n"), (gnd, "p")), ((relay, "n"), (gnd, "p")), ((vbat, "p"), (battery, "p")),
                 ((vbat, "n"), (gnd, "p")), ((motor, "shaft"), (pinion, "a")), ((pinion, "b"), (engine, "a")),
                 ((engine, "a"), (friction, "a")), ((friction, "b"), (block, "a")), ((engine, "a"), (angle, "a")),
                 ((engine, "a"), (speed, "a")), ((engine, "a"), (load, "a"))):  # fmt: skip
        d.link(a, b)
    d.connect(key, key_line)
    d.chain(angle, compression, negate, load)
    rpm = d.add(Gain(gain=RPM), name="engine_rpm")
    d.chain(speed, rpm)
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(vbat, (scope, 0))
    d.connect(amps, (scope, 1))
    d.connect(rpm, (scope, 2))
    positions = {"key_start": (0, 0), "ignition_switch": (130, 0), "starter_relay": (300, 60), "battery": (130, 130),
                 "gnd": (130, 260), "battery_voltage": (0, 200), "starter_current": (460, 60),
                 "starter_motor": (610, 60), "pinion_ring_gear": (760, 60), "crankshaft": (910, 0),
                 "engine_friction": (910, 110), "engine_block": (1060, 110), "crank_angle": (910, 220),
                 "crank_speed": (760, 220), "compression": (1060, 240), "opposes_rotation": (1060, 330),
                 "compression_torque": (910, 330), "engine_rpm": (610, 220), "scope": (460, 220)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = [
        TestCase(
            "cranking",
            "Inrush of several hundred amperes, the battery dips below 10 V, the engine cranks at 150-300 rpm",
            stop_time=1.5,
            checks=[
                Check("bounds", "starter_current", {"lower": 300.0, "upper": 1000.0, "t_from": 0.21, "t_to": 0.23}),
                Check("bounds", "battery_voltage", {"lower": 5.0, "upper": 10.0, "t_from": 0.21, "t_to": 0.23}),
                Check("bounds", "engine_rpm", {"lower": 120.0, "upper": 350.0, "t_from": 1.0, "t_to": 1.5}),
            ],
        )
    ]
    return d


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "starter_motor.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    late = res.t > 1.0
    print(f"inrush {res['starter_current'].max():.0f} A, battery minimum {res['battery_voltage'].min():.2f} V")
    print(f"cranking: {res['engine_rpm'][late].mean():.0f} rpm, {res['starter_current'][late].mean():.0f} A, "
          f"battery {res['battery_voltage'][late].mean():.2f} V")  # fmt: skip
    return res


if __name__ == "__main__":
    main()
