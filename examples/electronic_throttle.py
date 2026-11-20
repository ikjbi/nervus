"""Electronic throttle control (drive-by-wire) with a real DC motor, H-bridge, gear and return spring.

The pedal no longer pulls a cable: the ECU reads the pedal and moves the throttle plate with a DC motor.

* **Plant (physical blocks)**: the 12 V battery feeds an H-bridge (PWM, averaged); the motor drives the plate
  through a 20:1 gear; a return spring pulls the plate towards closed (its preload holds it shut when the
  motor is off, the safety requirement); friction damps it. The plate angle is measured (the throttle position
  sensor). The motor's and the plate's inertia are lumped on the motor side (the plate's reflected through the
  gear: J_plate / n²): a stiff gear between two inertias would have no unique solution.
* **ECU (signal blocks, 1 ms task)**: a PID controller on the angle error sets the H-bridge duty cycle, with
  feed-forward of the spring torque so the controller only has to correct the rest. This subsystem becomes C
  code.

Run with ``uv run python examples/electronic_throttle.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    AngleSensor,
    Battery,
    DCMotor,
    DiscretePID,
    ElectricalReference,
    FromWorkspace,
    Gain,
    HBridge,
    IdealGear,
    Inertia,
    Inport,
    Outport,
    RotationalDamper,
    RotationalReference,
    RotationalSpring,
    Scope,
    Subsystem,
    Sum,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
DEG = math.pi / 180

CONSTANTS = {
    "n_gear": (20.0, "-", "Gear ratio motor : plate"),
    "k_motor": (0.02, "N·m/A", "Motor torque constant"),
    "R_motor": (1.5, "Ω", "Armature resistance"),
    "k_spring": (0.06, "N·m/rad", "Return spring stiffness (at the plate)"),
    "spring_preload": (0.05, "N·m", "Return spring torque at the closed position"),
    # From the PID tuner (Linear Analysis → PID Tuning, PID, 60° phase margin): crossover 100 rad/s.
    "Kp_etc": (0.08, "1/°", "Proportional gain: duty per degree of error"),
    "Ki_etc": (2.0, "1/(°·s)", "Integral gain"),
    "Kd_etc": (0.0008, "s/°", "Derivative gain"),
}

TARGET = [
    (0, 5),
    (0.05, 5),
    (0.051, 60),
    (0.3, 60),
    (0.301, 20),
    (0.6, 20),
    (0.601, 80),
    (0.9, 80),
    (0.901, 5),
    (1.2, 5),
]


def build_ecu() -> Subsystem:
    """Angle control: PID on the error plus spring feed-forward, duty limited to ±1. 1 ms task."""
    s = Diagram("ecu")
    target = s.add(Inport(port=1), name="target_deg")
    measured = s.add(Inport(port=2), name="tps_deg")
    err = s.add(Sum(signs="+-"), name="error")
    pid = s.add(DiscretePID(P="Kp_etc", I="Ki_etc", D="Kd_etc", N=1000.0, upper=1.0, lower=-1.0,
                            anti_windup="clamping", sample_time=0.001), name="pid")  # fmt: skip
    # Feed-forward: the duty that holds the plate against the spring at the target angle.
    ff = s.add(Gain(gain="(k_spring * pi / 180) / n_gear * R_motor / k_motor / 12"), name="spring_ff")
    total = s.add(Sum(signs="++"), name="duty_sum")
    s.connect(target, (err, 0))
    s.connect(measured, (err, 1))
    s.chain(err, pid)
    s.chain(target, ff)
    s.connect(pid, (total, 0))
    s.connect(ff, (total, 1))
    s.connect(total, s.add(Outport(port=1), name="duty"))
    positions = {"target_deg": (0, 0), "tps_deg": (0, 100), "error": (130, 40), "pid": (250, 40),
                 "spring_ff": (250, 150), "duty_sum": (400, 80), "duty": (520, 80)}  # fmt: skip
    for name, (x, y) in positions.items():
        s.block(name).meta["position"] = [float(x), float(y)]
    return Subsystem(system=s, sample_time=0.001)


def build() -> Diagram:
    d = Diagram("electronic_throttle")
    d.settings.t_final = 1.2
    d.settings.solver = "auto"
    d.settings.max_step = 5e-4
    for name, (value, unit, desc) in CONSTANTS.items():
        d.workspace.add(Variable(name, value, desc, unit))
    t, v = zip(*TARGET, strict=True)
    target = d.add(FromWorkspace(time=list(t), data=[[x] for x in v]), name="pedal_target")
    ecu = d.add(build_ecu(), name="ECU")
    # Physical plant.
    gnd = d.add(ElectricalReference(), name="gnd")
    battery = d.add(Battery(capacity=60.0, R_internal=0.02, soc0=0.8), name="battery")
    bridge = d.add(HBridge(), name="h_bridge")
    motor = d.add(DCMotor(R="R_motor", L=1.5e-3, k="k_motor"), name="motor")
    rotor = d.add(Inertia(J=4e-6 + 2e-4 / 400), name="rotor_and_plate")  # J_motor + J_plate / n²
    gear = d.add(IdealGear(n="n_gear"), name="gear")
    spring = d.add(RotationalSpring(k="k_spring", phi0="spring_preload / k_spring"), name="return_spring")
    friction = d.add(RotationalDamper(d=2e-3), name="friction")
    housing = d.add(RotationalReference(), name="housing")
    angle = d.add(AngleSensor(), name="plate_angle")
    for a, b in (((battery, "p"), (bridge, "supply_p")), ((battery, "n"), (gnd, "p")),
                 ((bridge, "supply_n"), (gnd, "p")), ((bridge, "a"), (motor, "p")), ((bridge, "b"), (motor, "n")),
                 ((motor, "shaft"), (rotor, "a")), ((motor, "shaft"), (gear, "a")), ((gear, "b"), (spring, "a")),
                 ((gear, "b"), (friction, "a")), ((gear, "b"), (angle, "a")), ((spring, "b"), (housing, "a")),
                 ((friction, "b"), (housing, "a"))):  # fmt: skip
        d.link(a, b)
    to_deg = d.add(Gain(gain=1 / DEG), name="angle_deg")
    tps = d.add(ZeroOrderHold(sample_time=0.001), name="tps")
    d.chain(angle, to_deg, tps)
    d.connect(target, (ecu, 0))
    d.connect(tps, (ecu, 1))
    d.connect(ecu, bridge)
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(target, (scope, 0))
    d.connect(to_deg, (scope, 1))
    d.connect(to_deg, d.add(Outport(port=1), name="throttle_deg"))
    d.connect(ecu, d.add(Outport(port=2), name="duty"))
    positions = {"pedal_target": (0, 0), "ECU": (150, 10), "battery": (330, 140), "gnd": (330, 260),
                 "h_bridge": (480, 140), "motor": (640, 150), "rotor_and_plate": (800, 80), "gear": (800, 180),
                 "return_spring": (960, 120), "friction": (960, 220), "housing": (1110, 170),
                 "plate_angle": (960, 300), "angle_deg": (800, 360), "tps": (640, 360), "scope": (330, -100),
                 "throttle_deg": (1110, 330), "duty": (330, 30)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = tests()
    return d


def tests() -> list[TestCase]:
    return [
        TestCase(
            "step to 60°",
            "Full duty during the jump: 90 % in 50 ms, under 8° overshoot, within 1° after 150 ms",
            stop_time=0.3,
            checks=[
                Check("bounds", "throttle_deg", {"lower": 54.0, "upper": 68.0, "t_from": 0.1, "t_to": 0.3}),
                Check("bounds", "throttle_deg", {"lower": 59.0, "upper": 61.0, "t_from": 0.2, "t_to": 0.3}),
                Check("bounds", "throttle_deg", {"lower": -0.5, "upper": 68.0}),
            ],
        ),
        TestCase(
            "accurate at part throttle",
            "At 20° the integral removes the steady error caused by friction and the spring",
            stop_time=0.6,
            checks=[Check("bounds", "throttle_deg", {"lower": 19.5, "upper": 20.5, "t_from": 0.45, "t_to": 0.6})],
        ),
    ]


def main() -> SimResult:
    from nervus.codegen import generate_c
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "electronic_throttle.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    for t in (0.1, 0.3, 0.55, 0.85, 1.15):
        k = np.searchsorted(res.t, t)
        print(f"t = {t:4.2f} s: plate {res['throttle_deg'][k]:5.1f}°, duty {res['duty'][k]:+.2f}")
    code = generate_c(d.block("ECU"))
    print("ECU C code:", ", ".join(code.files))
    return res


if __name__ == "__main__":
    main()
