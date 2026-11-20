"""Traction control: a full-throttle launch on dry, wet and snowy roads, with tyre slip.

A tyre transmits force only through **slip**: the driven wheel turns a little faster than the car moves,

    slip = (ω_wheel · r - v) / max(ω_wheel · r, v)

The force rises with slip up to a peak (about 10 % slip) and then falls: a spinning wheel pushes less and
loses its side grip. The **magic formula** (Pacejka) describes this curve; the road's friction μ scales it.

The car (signal blocks, continuous): engine torque at the driven wheels, the wheels' inertia, the tyre force,
and the car's mass with drag and rolling resistance. On a wet road the full torque spins the wheels.

The **traction control** (TCS) ECU runs every 10 ms: it computes the slip from the wheel speed sensors (driven
wheel against the non-driven wheel, which turns with the car) and a PI controller reduces the engine torque
when the slip exceeds its target. Switch it off with ``tcs_enable = 0``.

Run with ``uv run python examples/traction_control.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Constant,
    DiscretePID,
    Gain,
    Inport,
    Integrator,
    Outport,
    Product,
    PythonFunction,
    Scope,
    Subsystem,
    Sum,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent

TIRE = '''def f(t, slip, normal_force):
    """Longitudinal tyre force [N]: Pacejka's magic formula, scaled by the road friction. p = [mu, B, C, E]"""
    mu, b, c, e = p[0], p[1], p[2], p[3]
    x = b * slip
    return mu * normal_force * math.sin(c * math.atan(x - e * (x - math.atan(x))))
'''

SLIP = '''def f(t, wheel_speed, car_speed):
    """Slip of the driven wheels from their speed [m/s at the tyre] and the car's speed [m/s]."""
    return (wheel_speed - car_speed) / max(wheel_speed, car_speed, 0.5)
'''

CONSTANTS = {
    "mu_road": (0.5, "-", "Road friction: dry 1.0, wet 0.5, snow 0.2"),
    "mass": (1500.0, "kg", "Vehicle mass"),
    "axle_load": (0.6, "-", "Share of the weight on the driven axle"),
    "r_tyre": (0.31, "m", "Tyre radius"),
    "J_wheels": (30.0, "kg·m²", "Wheels, driveline and the engine reflected through 1st gear (at the wheels)"),
    "T_wheel_max": (3000.0, "N·m", "Engine torque at the wheels in 1st gear, full throttle"),
    "slip_target": (0.10, "-", "Slip the TCS allows"),
    "tcs_enable": (1.0, "-", "1: traction control on, 0: off"),
}


def build_tcs() -> Subsystem:
    """Traction control: slip from the wheel speeds, PI torque reduction (0 = none, 1 = all), every 10 ms."""
    s = Diagram("tcs")
    driven = s.add(Inport(port=1), name="driven_wheel_m_s")
    free = s.add(Inport(port=2), name="free_wheel_m_s")
    slip = s.add(PythonFunction(code=SLIP, num_inputs=2), name="slip")
    err = s.add(Sum(signs="+-"), name="slip_error")
    target = s.add(Constant(value="slip_target"), name="target")
    pi = s.add(DiscretePID(P=4.0, I=40.0, upper=1.0, lower=0.0, anti_windup="clamping", sample_time=0.01),
               name="pi")  # fmt: skip
    enable = s.add(Constant(value="tcs_enable"), name="enable")
    cut = s.add(Product(ops="**"), name="torque_cut")
    s.connect(driven, (slip, 0))
    s.connect(free, (slip, 1))
    s.connect(slip, (err, 0))
    s.connect(target, (err, 1))
    s.chain(err, pi)
    s.connect(pi, (cut, 0))
    s.connect(enable, (cut, 1))
    s.connect(cut, s.add(Outport(port=1), name="reduction"))
    s.connect(slip, s.add(Outport(port=2), name="slip_out"))
    positions = {"driven_wheel_m_s": (0, 0), "free_wheel_m_s": (0, 90), "slip": (140, 40), "target": (140, 140),
                 "slip_error": (270, 60), "pi": (390, 60), "enable": (390, 160), "torque_cut": (520, 90),
                 "reduction": (650, 90), "slip_out": (270, -40)}  # fmt: skip
    for name, (x, y) in positions.items():
        s.block(name).meta["position"] = [float(x), float(y)]
    return Subsystem(system=s, sample_time=0.01)


def build() -> Diagram:
    d = Diagram("traction_control")
    d.settings.t_final = 6.0
    d.settings.solver = "rk4"
    d.settings.step = 0.001
    for name, (value, unit, desc) in CONSTANTS.items():
        d.workspace.add(Variable(name, value, desc, unit))
    # Car (continuous).
    one = d.add(Constant(value=1.0), name="one")
    remaining = d.add(Sum(signs="+-"), name="torque_left")  # 1 - reduction
    engine = d.add(Gain(gain="T_wheel_max"), name="wheel_torque")
    wheel_net = d.add(Sum(signs="+-"), name="wheel_net_torque")
    wheel = d.add(Integrator(lower=0.0), name="wheel_omega")
    wheel_speed = d.add(Gain(gain="r_tyre"), name="wheel_m_s")
    normal = d.add(Constant(value="mass * 9.81 * axle_load"), name="normal_force")
    tire_slip = d.add(PythonFunction(code=SLIP, num_inputs=2), name="tyre_slip")
    tire = d.add(PythonFunction(code=TIRE, num_inputs=2, parameters="[mu_road, 10.0, 1.9, 0.97]"), name="tyre_force")
    reaction = d.add(Gain(gain="r_tyre"), name="tyre_torque")
    net = d.add(Sum(signs="+-"), name="net_force")
    drag = d.add(PythonFunction(code="def f(t, v):\n    return 0.4 * v * v + 180.0\n", num_inputs=1), name="road_loads")
    accel = d.add(Gain(gain="1 / mass"), name="accel")
    car = d.add(Integrator(lower=0.0), name="car_m_s")
    wheel_acc = d.add(Gain(gain="1 / J_wheels"), name="wheel_accel")
    kmh = d.add(Gain(gain=3.6), name="speed_kmh")
    # Wheel speed sensors and the ECU.
    sens_driven = d.add(ZeroOrderHold(sample_time=0.01), name="wss_driven")
    sens_free = d.add(ZeroOrderHold(sample_time=0.01), name="wss_free")
    tcs = d.add(build_tcs(), name="TCS")
    d.connect(one, (remaining, 0))
    d.connect((tcs, 0), (remaining, 1))
    d.chain(remaining, engine)
    d.connect(engine, (wheel_net, 0))
    d.connect(reaction, (wheel_net, 1))
    d.chain(wheel_net, wheel_acc, wheel, wheel_speed)
    d.connect(wheel_speed, (tire_slip, 0))
    d.connect(car, (tire_slip, 1))
    d.connect(tire_slip, (tire, 0))
    d.connect(normal, (tire, 1))
    d.chain(tire, reaction)
    d.connect(tire, (net, 0))
    d.connect(drag, (net, 1))
    d.chain(net, accel, car)
    d.connect(car, drag)
    d.chain(car, kmh)
    d.chain(wheel_speed, sens_driven)
    d.chain(car, sens_free)
    d.connect(sens_driven, (tcs, 0))
    d.connect(sens_free, (tcs, 1))
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(tire_slip, (scope, 0))
    d.connect((tcs, 0), (scope, 1))
    d.connect(kmh, d.add(Outport(port=1), name="speed"))
    d.connect(tire_slip, d.add(Outport(port=2), name="slip"))
    d.connect((tcs, 0), d.add(Outport(port=3), name="torque_reduction"))
    positions = {"one": (0, 0), "torque_left": (120, 20), "wheel_torque": (240, 20), "wheel_net_torque": (360, 40),
                 "wheel_accel": (480, 40), "wheel_omega": (600, 40), "wheel_m_s": (720, 40), "tyre_slip": (860, 100),
                 "normal_force": (860, 200), "tyre_force": (1000, 140), "tyre_torque": (1000, 260),
                 "net_force": (1140, 160), "road_loads": (1140, 280), "accel": (1260, 160), "car_m_s": (1380, 160),
                 "speed_kmh": (1500, 160), "wss_driven": (860, -60), "wss_free": (1380, 300), "TCS": (360, -120),
                 "scope": (1000, -120), "speed": (1620, 160), "slip": (1140, 40), "torque_reduction": (600, -120)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = [
        TestCase(
            "TCS holds the slip on a wet road",
            "With traction control the slip stays near 10 % after the first moment",
            stop_time=6.0,
            checks=[Check("bounds", "slip", {"lower": 0.0, "upper": 0.2, "t_from": 0.5, "t_to": 6.0})],
        )
    ]
    return d


def time_to(res: SimResult, kmh: float) -> float:
    k = np.argmax(np.ravel(res["speed"]) >= kmh)
    return float(res.t[k]) if res["speed"][k] >= kmh else float("inf")


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "traction_control.nervus")
    for r in run_tests(d):
        print(r.summary())
    out = {}
    for mu in (1.0, 0.5, 0.2):
        for tcs in (0.0, 1.0):
            res = simulate(d, params={"mu_road": mu, "tcs_enable": tcs})
            out[f"mu{mu}_tcs{tcs:.0f}"] = res
            print(f"mu {mu}: TCS {'on ' if tcs else 'off'} 0-50 km/h in {time_to(res, 50):.2f} s, "
                  f"max slip {np.max(res['slip'][res.t > 0.5]):.0%}")  # fmt: skip
    return out


if __name__ == "__main__":
    main()
