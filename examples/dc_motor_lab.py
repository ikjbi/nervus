"""DC motor speed and position control: the servo experiment of every control lab.

The plant is a small permanent-magnet DC motor with an inertia disk, the size of the motors on common teaching
rigs: armature resistance 8.4 Ω, inductance 1.16 mH, torque constant 0.042 N·m/A, rotor plus disk
2.1·10⁻⁵ kg·m². A ±10 V amplifier drives it; an encoder measures the angle and speed. The controller runs at
1 kHz, as on the lab computer.

From voltage to speed the motor is (nearly) a first-order system:

    ω(s) / V(s) = K / (τ s + 1),    K = 1 / k_m = 23.8 rad/s/V,    τ = R J / k_m² = 0.10 s

Two models are built:

* ``dc_motor_speed.nervus``: speed control with a PI controller. With ``closed_loop = 0`` the amplifier gets a
  5 V step instead (to identify K and τ).
* ``dc_motor_position.nervus``: angle control with a PD controller.

Run with ``uv run python examples/dc_motor_lab.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    AngleSensor,
    Constant,
    DCMotor,
    DiscretePID,
    ElectricalReference,
    Inertia,
    Outport,
    RotationalDamper,
    RotationalReference,
    Scope,
    SpeedSensor,
    Step,
    Sum,
    Switch,
    VoltageSource,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.001

PLANT = {
    "R_m": (8.4, "Ω", "Armature resistance"),
    "L_m": (1.16e-3, "H", "Armature inductance"),
    "k_m": (0.042, "N·m/A", "Torque constant (= back-EMF constant in V·s/rad)"),
    "J": (2.1e-5, "kg·m²", "Rotor and inertia disk"),
    "b": (1e-7, "N·m·s/rad", "Viscous friction"),
    "V_max": (10.0, "V", "Amplifier limit"),
}


def _plant(d: Diagram) -> tuple[object, object, object]:
    """Amplifier (controlled voltage source), motor, disk and encoder. Returns (source, speed, angle) blocks."""
    gnd = d.add(ElectricalReference(), name="gnd")
    amp = d.add(VoltageSource(controlled=True), name="amplifier")
    motor = d.add(DCMotor(R="R_m", L="L_m", k="k_m"), name="motor")
    disk = d.add(Inertia(J="J"), name="disk")
    friction = d.add(RotationalDamper(d="b"), name="friction")
    frame = d.add(RotationalReference(), name="frame")
    speed = d.add(SpeedSensor(), name="speed_sensor")
    angle = d.add(AngleSensor(), name="encoder")
    for a, b in (((amp, "p"), (motor, "p")), ((amp, "n"), (gnd, "p")), ((motor, "n"), (gnd, "p")),
                 ((motor, "shaft"), (disk, "a")), ((motor, "shaft"), (friction, "a")), ((friction, "b"), (frame, "a")),
                 ((motor, "shaft"), (speed, "a")), ((motor, "shaft"), (angle, "a"))):  # fmt: skip
        d.link(a, b)
    return amp, speed, angle


def _base(name: str, t_final: float) -> Diagram:
    d = Diagram(name)
    d.settings.t_final = t_final
    d.settings.solver = "auto"
    d.settings.max_step = 2e-4
    for k, (value, unit, desc) in PLANT.items():
        d.workspace.add(Variable(k, value, desc, unit))
    return d


def build_speed() -> Diagram:
    d = _base("dc_motor_speed", 1.0)
    ws = d.workspace
    ws.add(Variable("Kp_w", 0.122, "Speed controller: proportional gain", "V/(rad/s)"))
    ws.add(Variable("Ki_w", 1.26, "Speed controller: integral gain (Kp / τ: cancels the motor pole)", "V/rad"))
    ws.add(Variable("closed_loop", 1.0, "1: PI speed control, 0: open-loop 5 V step (identification)", "-"))
    amp, speed, _angle = _plant(d)
    ref = d.add(Step(time=0.1, final=50.0), name="speed_ref")
    meas = d.add(ZeroOrderHold(sample_time=TS), name="speed_meas")
    err = d.add(Sum(signs="+-"), name="error")
    pi = d.add(DiscretePID(P="Kp_w", I="Ki_w", upper="V_max", lower="-V_max", anti_windup="clamping",
                           sample_time=TS), name="pi")  # fmt: skip
    test_v = d.add(Step(time=0.1, final=5.0), name="test_voltage")
    mode = d.add(Constant(value="closed_loop"), name="mode")
    sel = d.add(Switch(threshold=0.5), name="mode_switch")
    d.chain(speed, meas)
    d.connect(ref, (err, 0))
    d.connect(meas, (err, 1))
    d.chain(err, pi)
    d.connect(pi, (sel, 0))
    d.connect(mode, (sel, 1))
    d.connect(test_v, (sel, 2))
    d.connect(sel, amp)
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(ref, (scope, 0))
    d.connect(speed, (scope, 1))
    d.connect(speed, d.add(Outport(port=1), name="speed"))
    d.connect(sel, d.add(Outport(port=2), name="voltage"))
    _place(d, {"speed_ref": (0, 0), "error": (140, 10), "pi": (270, 10), "test_voltage": (270, 110),
               "mode": (270, 200), "mode_switch": (420, 60), "amplifier": (560, 60), "gnd": (560, 180),
               "motor": (700, 60), "disk": (850, 0), "friction": (850, 100), "frame": (1000, 100),
               "speed_sensor": (850, 200), "encoder": (850, 300), "speed_meas": (700, 260), "scope": (1000, -80),
               "speed": (1000, 200), "voltage": (560, -60)})  # fmt: skip
    d.tests = [
        TestCase(
            "speed loop: 50 rad/s within 0.15 s, no overshoot",
            "The PI cancels the motor's time constant: a first-order response with τ ≈ 33 ms",
            stop_time=1.0,
            checks=[
                Check("bounds", "speed", {"lower": 49.0, "upper": 50.5, "t_from": 0.25}),
                Check("bounds", "voltage", {"lower": -10.0, "upper": 10.0}),
            ],
        )
    ]
    return d


def build_position() -> Diagram:
    d = _base("dc_motor_position", 0.6)
    ws = d.workspace
    ws.add(Variable("Kp_th", 6.5, "Position controller: proportional gain (ωn = 40 rad/s)", "V/rad"))
    ws.add(Variable("Kd_th", 0.186, "Position controller: derivative gain (ζ = 0.7)", "V·s/rad"))
    amp, _speed, angle = _plant(d)
    ref = d.add(Step(time=0.05, final=1.0), name="angle_ref")
    meas = d.add(ZeroOrderHold(sample_time=TS), name="angle_meas")
    err = d.add(Sum(signs="+-"), name="error")
    pd = d.add(DiscretePID(P="Kp_th", I=0.0, D="Kd_th", N=500.0, upper="V_max", lower="-V_max",
                           anti_windup="clamping", sample_time=TS), name="pd")  # fmt: skip
    d.chain(angle, meas)
    d.connect(ref, (err, 0))
    d.connect(meas, (err, 1))
    d.chain(err, pd, amp)
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(ref, (scope, 0))
    d.connect(angle, (scope, 1))
    d.connect(angle, d.add(Outport(port=1), name="angle"))
    d.connect(pd, d.add(Outport(port=2), name="voltage"))
    _place(d, {"angle_ref": (0, 0), "error": (140, 10), "pd": (270, 10), "amplifier": (420, 60),
               "gnd": (420, 180), "motor": (560, 60), "disk": (710, 0), "friction": (710, 100), "frame": (860, 100),
               "speed_sensor": (710, 300), "encoder": (710, 200), "angle_meas": (560, 260), "scope": (860, -80),
               "angle": (860, 200), "voltage": (420, -60)})  # fmt: skip
    d.tests = [
        TestCase(
            "position loop: 1 rad step, small overshoot",
            "ζ = 0.7, ωn = 40 rad/s: about 5 % overshoot, settled within 2 % after 0.2 s",
            stop_time=0.6,
            checks=[
                Check("bounds", "angle", {"upper": 1.08}),
                Check("bounds", "angle", {"lower": 0.98, "upper": 1.02, "t_from": 0.25}),
            ],
        )
    ]
    return d


def _place(d: Diagram, positions: dict[str, tuple[int, int]]) -> None:
    for name, (x, y) in positions.items():
        if name in d:
            d.block(name).meta["position"] = [float(x), float(y)]


def identify(res: SimResult) -> tuple[float, float]:
    """Gain K [rad/s/V] and time constant τ [s] from the open-loop 5 V step (63 % rule)."""
    w = np.ravel(res["speed"])
    final = float(w[-1])
    k = int(np.argmax(w >= 0.632 * final))
    return final / 5.0, float(res.t[k]) - 0.1


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    speed, position = build_speed(), build_position()
    save(speed, HERE / "dc_motor_speed.nervus")
    save(position, HERE / "dc_motor_position.nervus")
    for d in (speed, position):
        for r in run_tests(d):
            print(r.summary())
    open_loop = simulate(speed, params={"closed_loop": 0.0})
    k, tau = identify(open_loop)
    print(f"identified: K = {k:.1f} rad/s/V, tau = {1000 * tau:.0f} ms")
    return {"open_loop": open_loop, "speed": simulate(speed), "position": simulate(position)}


if __name__ == "__main__":
    main()
