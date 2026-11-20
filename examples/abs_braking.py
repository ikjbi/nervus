"""ABS: an emergency stop from 100 km/h, with and without anti-lock braking.

A quarter car (one wheel carrying a quarter of a 1600 kg car) brakes as hard as the driver can from 0.5 s. The tyre
transmits force through **slip**, the difference between the car's speed and the wheel's circumferential speed:

    slip = (v - ω·r) / v          (0: rolling freely, 1: locked)

The friction peaks at about 10-15 % slip and falls when the wheel locks; a locked wheel also cannot steer. The
**ABS** ECU (every 5 ms) watches the slip and switches the brake pressure valves, like the classic threshold ABS:

* **build**: pressure (brake torque) rises towards what the driver asks for;
* **hold**: above ``slip_hold`` (10 %), the inlet valve closes and the pressure is held;
* **release**: above ``slip_release`` (20 %), the outlet valve opens and the pressure falls, until the slip is
  back below ``slip_hold``.

Below 2 m/s (7 km/h) the ABS stops controlling and the wheel may lock, as in real cars.

Set ``abs_on`` = 0 to brake without ABS, and ``mu_road`` to 1.0 (dry), 0.5 (wet) or 0.15 (ice).

Run with ``uv run python examples/abs_braking.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Constant,
    Gain,
    Integrator,
    Outport,
    PythonFunction,
    Scope,
    StateChart,
    Step,
    Sum,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.005

CONSTANTS = {
    "m_quarter": (400.0, "kg", "A quarter of the car's mass"),
    "J_wheel": (1.2, "kg·m²", "Wheel, tyre and brake disc"),
    "r_tyre": (0.31, "m", "Tyre radius"),
    "mu_road": (1.0, "-", "Road friction: dry 1.0, wet 0.5, ice 0.15"),
    "T_driver": (2500.0, "N·m", "Brake torque the driver asks for (full braking)"),
    "build_rate": (8000.0, "N·m/s", "How fast the pressure (torque) rises with the inlet valve open"),
    "release_rate": (16000.0, "N·m/s", "How fast it falls with the outlet valve open"),
    "slip_hold": (0.10, "-", "ABS: hold the pressure above this slip"),
    "slip_release": (0.20, "-", "ABS: release the pressure above this slip"),
    "abs_on": (1.0, "-", "1: ABS active, 0: no ABS (the pressure follows the driver)"),
}

TYRE = '''def f(t, slip, fz):
    """Longitudinal tyre force [N] (Pacejka's magic formula) for a slip 0..1, scaled by the road friction."""
    mu, b, c, e = p[0], 12.0, 1.65, 0.5  # peak at 15 % slip; a locked wheel keeps 71 % of the peak
    x = b * slip
    return mu * fz * math.sin(c * math.atan(x - e * (x - math.atan(x))))
'''

SLIP = '''def f(t, v, omega):
    """Braking slip: 0 rolling freely, 1 locked. The 0.1 m/s floor keeps a locked wheel braking down to standstill."""
    return min(1.0, max(0.0, (v - omega * p[0]) / max(v, omega * p[0], 0.1)))
'''

BRAKE = '''def f(t, torque, demand, mode, abs_on):
    """Rate of change of the brake torque [N·m/s]: towards the driver's demand without ABS (a 50 ms lag), or by
    the ABS valve mode (1 build, 0 hold, -1 release) with ABS."""
    if abs_on < 0.5 or demand <= 0.0:
        return (demand - torque) / 0.05
    if mode > 0.5:
        return p[0] if torque < demand else 0.0
    if mode < -0.5:
        return -p[1] if torque > 0.0 else 0.0
    return 0.0
'''

ABS_CHART = """
input slip, v
output mode = 1
param slip_hold, slip_release

state build
  entry: mode = 1
state hold
  entry: mode = 0
state release
  entry: mode = -1

transition build -> release: v > 2 and slip > slip_release
transition build -> hold: v > 2 and slip > slip_hold
transition hold -> release: v > 2 and slip > slip_release
transition hold -> build: slip < slip_hold or v < 2
transition release -> build: slip < slip_hold or v < 2
"""


def build() -> Diagram:
    d = Diagram("abs_braking")
    d.settings.t_final = 5.0
    d.settings.solver = "rk4"
    d.settings.step = 0.001
    for name, (value, unit, desc) in CONSTANTS.items():
        d.workspace.add(Variable(name, value, desc, unit))
    # Vehicle and wheel.
    v = d.add(Integrator(initial=100 / 3.6, lower=0.0), name="car_speed")
    omega = d.add(Integrator(initial=100 / 3.6 / 0.31, lower=0.0), name="wheel_omega")
    dist = d.add(Integrator(), name="distance")
    slip = d.add(PythonFunction(code=SLIP, num_inputs=2, parameters="[r_tyre]"), name="slip")
    fz = d.add(Constant(value="m_quarter * 9.81"), name="normal_force")
    tyre = d.add(PythonFunction(code=TYRE, num_inputs=2, parameters="[mu_road]"), name="tyre_force")
    decel = d.add(Gain(gain="-1 / m_quarter"), name="car_accel")
    tyre_torque = d.add(Gain(gain="r_tyre"), name="tyre_torque")
    wheel_net = d.add(Sum(signs="+-"), name="wheel_net_torque")
    wheel_acc = d.add(Gain(gain="1 / J_wheel"), name="wheel_accel")
    # Brake: driver demand, hydraulic modulation.
    pedal = d.add(Step(time=0.5, final=1.0), name="driver_brakes")
    demand = d.add(Gain(gain="T_driver"), name="torque_demand")
    rate = d.add(PythonFunction(code=BRAKE, num_inputs=4, parameters="[build_rate, release_rate]"), name="valves")
    torque = d.add(Integrator(lower=0.0), name="brake_torque")
    abs_flag = d.add(Constant(value="abs_on"), name="abs_switch")
    # ABS ECU (5 ms).
    slip_s = d.add(ZeroOrderHold(sample_time=TS), name="slip_sensor")
    v_s = d.add(ZeroOrderHold(sample_time=TS), name="speed_sensor")
    abs_ecu = d.add(StateChart(definition=ABS_CHART, sample_time=TS, state_output=False), name="abs_ecu")
    # Wiring.
    d.connect(v, (slip, 0))
    d.connect(omega, (slip, 1))
    d.connect(slip, (tyre, 0))
    d.connect(fz, (tyre, 1))
    d.chain(tyre, decel, v, dist)
    d.chain(tyre, tyre_torque)
    d.connect(tyre_torque, (wheel_net, 0))
    d.connect(torque, (wheel_net, 1))
    d.chain(wheel_net, wheel_acc, omega)
    d.chain(pedal, demand)
    d.connect(torque, (rate, 0))
    d.connect(demand, (rate, 1))
    d.connect(abs_ecu, (rate, 2))
    d.connect(abs_flag, (rate, 3))
    d.chain(rate, torque)
    d.chain(slip, slip_s)
    d.chain(v, v_s)
    d.connect(slip_s, (abs_ecu, 0))
    d.connect(v_s, (abs_ecu, 1))
    kmh = d.add(Gain(gain=3.6), name="speed_kmh")
    wheel_kmh = d.add(Gain(gain="3.6 * r_tyre"), name="wheel_kmh")
    d.chain(v, kmh)
    d.chain(omega, wheel_kmh)
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(kmh, (scope, 0))
    d.connect(wheel_kmh, (scope, 1))
    outs = ((kmh, "speed"), (wheel_kmh, "wheel_speed"), (slip, "wheel_slip"), (dist, "stopping_distance"),
            (torque, "brake_torque_out"))  # fmt: skip
    for k, (src, name) in enumerate(outs):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    positions = {"driver_brakes": (0, 300), "torque_demand": (130, 300), "abs_switch": (130, 400),
                 "valves": (300, 300), "brake_torque": (430, 300), "wheel_net_torque": (560, 200),
                 "wheel_accel": (680, 200), "wheel_omega": (800, 200), "car_speed": (800, 40), "distance": (930, 40),
                 "slip": (930, 140), "normal_force": (930, 260), "tyre_force": (1060, 160), "car_accel": (680, 40),
                 "tyre_torque": (560, 120), "slip_sensor": (1060, 300), "speed_sensor": (1060, 380),
                 "abs_ecu": (1200, 330), "speed_kmh": (930, -60), "wheel_kmh": (1060, 230), "scope": (1200, -60),
                 "speed": (1200, 0), "wheel_speed": (1340, 230), "wheel_slip": (1200, 140),
                 "stopping_distance": (1060, 40), "brake_torque_out": (560, 400)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    for name in ("car_accel", "tyre_torque"):
        d.block(name).meta["flipped"] = True
    d.tests = [
        TestCase(
            "ABS keeps the wheel turning",
            "With ABS the slip stays below 30 % after the first cycle: the wheel never locks and the car can steer",
            stop_time=4.0,
            checks=[Check("bounds", "wheel_slip", {"upper": 0.3, "t_from": 0.7, "t_to": 3.0})],
        ),
        TestCase(
            "without ABS the wheel locks",
            "Full braking without ABS on a dry road locks the wheel within 0.2 s",
            stop_time=2.0,
            parameters={"abs_on": 0.0},
            checks=[Check("bounds", "wheel_slip", {"lower": 0.99, "t_from": 0.75, "t_to": 2.0})],
        ),
    ]
    return d


def stopping(res: SimResult) -> tuple[float, float]:
    """Stopping distance [m] (from the start of braking) and time [s]."""
    v = np.ravel(res["speed"])
    k = int(np.argmax(v < 0.5)) if np.any(v < 0.5) else len(v) - 1
    s = np.ravel(res["stopping_distance"])
    start = int(np.searchsorted(res.t, 0.5))
    return float(s[k] - s[start]), float(res.t[k] - 0.5)


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "abs_braking.nervus")
    for r in run_tests(d):
        print(r.summary())
    out = {}
    for mu, road in ((1.0, "dry"), (0.5, "wet"), (0.15, "ice")):
        for abs_on in (1.0, 0.0):
            res = simulate(d, 26.0 if mu < 0.3 else 12.0, params={"mu_road": mu, "abs_on": abs_on})
            dist, t = stopping(res)
            out[f"{road}_{'abs' if abs_on else 'locked'}"] = res
            print(f"{road:4s} {'ABS     ' if abs_on else 'no ABS  '} stops in {dist:5.1f} m, {t:4.1f} s")
    return out


if __name__ == "__main__":
    main()
