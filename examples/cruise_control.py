"""Cruise control: the model built step by step in the first tutorial (docs/tutorials/first-model.md).

The car: the engine force F (at most 4000 N; braking down to -6000 N) accelerates the mass m against the
aerodynamic and rolling drag, here simply proportional to the speed:

    m · dv/dt = F − c · v          (v in km/h, so dv/dt [km/h/s] = 3.6 · (F − c·v) / m)

The cruise control is a PI controller on the speed error. The tutorial shows three steps: P only (the car stays
below the set speed), PI (no steady error, but a big overshoot from integrator windup) and PI with anti-windup.

Run with ``uv run python examples/cruise_control.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import PID, Gain, Integrator, Scope, Step, Sum
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent

POSITIONS = {
    "set_speed": (0, 0), "error": (150, 10), "cruise_control": (290, 0), "net_force": (450, 10),
    "accel": (590, 10), "speed": (730, 10), "drag": (590, 130), "scope": (900, 0),
}  # fmt: skip


def build(ki: float = 30.0, anti_windup: str = "clamping") -> Diagram:
    d = Diagram("cruise_control")
    d.settings.t_final = 40.0
    ws = d.workspace
    ws.add(Variable("m", 1500.0, "Vehicle mass", "kg"))
    ws.add(Variable("c_drag", 8.0, "Drag force per km/h", "N/(km/h)"))
    ws.add(Variable("Kp", 300.0, "Proportional gain", "N/(km/h)"))
    ws.add(Variable("Ki", ki, "Integral gain", "N/(km/h·s)"))
    sp = d.add(Step(time=1.0, initial=0.0, final=100.0), name="set_speed")
    err = d.add(Sum(signs="+-"), name="error")
    ctrl = d.add(PID(P="Kp", I="Ki", upper=4000.0, lower=-6000.0, anti_windup=anti_windup), name="cruise_control")
    net = d.add(Sum(signs="+-"), name="net_force")
    accel = d.add(Gain(gain="3.6 / m"), name="accel")
    speed = d.add(Integrator(), name="speed")
    drag = d.add(Gain(gain="c_drag"), name="drag")
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(sp, (err, 0))
    d.connect(speed, (err, 1))
    d.chain(err, ctrl)
    d.connect(ctrl, (net, 0))
    d.connect(drag, (net, 1))
    d.chain(net, accel, speed, drag)
    d.connect(sp, (scope, 0))
    d.connect(speed, (scope, 1))
    for name, (x, y) in POSITIONS.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.block("drag").meta["flipped"] = True
    d.tests = [
        TestCase(
            "reaches the set speed without overshoot",
            "With anti-windup the speed stays below 101 km/h and is within 1 km/h of 100 after 20 s",
            stop_time=40.0,
            checks=[
                Check("bounds", "speed", {"upper": 101.0}),
                Check("bounds", "speed", {"lower": 99.0, "upper": 101.0, "t_from": 20.0}),
            ],
        )
    ]
    return d


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "cruise_control.nervus")
    for r in run_tests(d):
        print(r.summary())
    runs = {
        "P only": simulate(build(ki=0.0, anti_windup="none")),
        "PI": simulate(build(anti_windup="none")),
        "PI + anti-windup": simulate(d),
    }
    for label, r in runs.items():
        print(f"{label:17s} max {np.max(r['speed']):6.1f} km/h, after 40 s {r['speed'][-1]:6.1f} km/h")
    return runs


if __name__ == "__main__":
    main()
