"""A 40-tonne truck on a mountain road: heavy-duty diesel, 12-speed AMT and exhaust brake.

Trucks are different from cars: the engine (13 litres, 2600 N·m from 1000 rpm) is small for the mass, so on a
climb the gearbox must keep it in its narrow band of best torque, and on a descent the mass would run away
without help. Brakes would overheat on a long descent, so trucks have **auxiliary brakes**: here an **exhaust
brake** (a flap that closes the exhaust, so the engine works as a compressor), which brakes more the faster
the engine turns.

* **AMT (automated manual transmission)**, 12 gears, the TCU shifts by engine speed: up above 1500 rpm,
  down below 1050 rpm. Every shift interrupts the torque for 0.8 s (the clutch opens, the gearbox syncs).
* **Downhill speed control**: when the speed exceeds the set speed + 4 km/h, the ECU closes the exhaust flap
  (and the TCU holds a gear so the engine speed stays high, where the exhaust brake is strongest). On this
  6 % descent the exhaust brake alone holds the truck at 98 km/h, not at 84: 40 t need more braking power than
  an exhaust brake has, which is why trucks for mountain roads have a hydraulic retarder as well. Without the
  exhaust brake the truck would run away.
* **Cruise control**: a PI controller on the speed sets the fuel (the engine torque) up to full load.

The route: flat, then a 6 % climb for 2 km, then a 6 % descent.

Run with ``uv run python examples/truck.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Constant,
    DiscretePID,
    Gain,
    Integrator,
    Lookup1D,
    Outport,
    PythonFunction,
    Scope,
    StateChart,
    Sum,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.05

RATIOS = [14.9, 11.7, 9.0, 7.1, 5.6, 4.4, 3.4, 2.6, 2.0, 1.6, 1.3, 1.0]  # a 12-speed AMT

AMT_CHART = """
input rpm, brake_request
output gear = 12, shifting = 0
local target = 12
param up_rpm, down_rpm, hold_rpm, shift_time, n_gears

state driving
  entry: shifting = 0
state shifting_up
  entry: shifting = 1; target = gear + 1
state shifting_down
  entry: shifting = 1; target = gear - 1

transition driving -> shifting_down: rpm < down_rpm and gear > 1 and after(10)
transition driving -> shifting_down: brake_request > 0.5 and rpm < hold_rpm and gear > 1 and after(10)
transition driving -> shifting_up: rpm > up_rpm and gear < n_gears and brake_request < 0.5 and after(10)
transition shifting_up -> driving: t_in_state >= shift_time / gear = target
transition shifting_down -> driving: t_in_state >= shift_time / gear = target
"""

ENGINE = '''def f(t, rpm, fuel, flap):
    """Engine torque at the flywheel [N·m]: fuel (0..1) times the full-load curve, minus friction and the exhaust
    brake (flap 0..1), whose braking torque grows with the engine speed."""
    full = np.interp(rpm, [600, 1000, 1400, 1800, 2100], [1400, 2600, 2600, 2000, 0])
    friction = 80 + 0.06 * rpm
    exhaust = flap * np.interp(rpm, [600, 1200, 2300], [0, 900, 2000])
    return fuel * full - friction - exhaust
'''

ROUTE = '''def f(t, s):
    """Road grade [%] along the route [m]: flat, a 2 km climb of 6 %, then a descent of 6 %."""
    if s < 500:
        return 0.0
    if s < 2500:
        return 6.0
    return -6.0
'''

ROAD = '''def f(t, v, grade):
    """Road loads [N] for a 40 t truck: drag (cdA 5.5 m²), rolling resistance 0.006, grade."""
    a = math.atan(grade / 100)
    return 0.5 * 1.2 * 5.5 * v * abs(v) + 40000 * 9.81 * (0.006 * math.cos(a) * min(1.0, v / 0.5) + math.sin(a))
'''

CONSTANTS = {
    "set_speed": (80.0, "km/h", "Cruise control set speed"),
    "brake_margin": (4.0, "km/h", "The exhaust brake closes above set speed + this"),
    "up_rpm": (1500.0, "rpm", "Upshift above this engine speed"),
    "down_rpm": (1050.0, "rpm", "Downshift below this engine speed"),
    "hold_rpm": (2000.0, "rpm", "While braking, downshift below this (for more exhaust brake)"),
    "shift_time": (0.8, "s", "Torque interruption of a shift"),
    "n_gears": (12, "-", "Number of gears"),
    "exhaust_brake": (1.0, "-", "1: the exhaust brake is fitted, 0: not"),
}


def build() -> Diagram:
    d = Diagram("truck")
    d.settings.t_final = 420.0
    d.settings.solver = "rk4"
    d.settings.step = TS
    ws = d.workspace
    for name, (value, unit, desc) in CONSTANTS.items():
        ws.add(Variable(name, value, desc, unit))
    ws.add(Variable("gear_ratios", RATIOS, "AMT ratios, gear 1..12", "-"))
    # Vehicle.
    v = d.add(Integrator(initial=80 / 3.6, lower=0.0), name="v_m_s")
    pos = d.add(Integrator(), name="position_m")
    route = d.add(PythonFunction(code=ROUTE, num_inputs=1), name="route_grade")
    loads = d.add(PythonFunction(code=ROAD, num_inputs=2), name="road_loads")
    gear = d.add(UnitDelay(initial=12.0, sample_time=TS), name="gear_engaged")
    ratio = d.add(Lookup1D(breakpoints=[float(k) for k in range(1, 13)], table="gear_ratios", interpolation="nearest"),
                  name="gear_ratio")  # fmt: skip
    overall = d.add(Gain(gain=3.4), name="axle_ratio")  # final drive
    rpm = d.add(PythonFunction(code="def f(t, v, i):\n    return max(600.0, v / 0.5 * i * 60 / (2 * math.pi))\n",
                               num_inputs=2), name="engine_rpm")  # fmt: skip
    engine = d.add(PythonFunction(code=ENGINE, num_inputs=3), name="engine_torque")
    interrupt = d.add(PythonFunction(code="def f(t, tq, shifting):\n    return 0.0 if shifting > 0.5 else tq\n",
                                     num_inputs=2), name="clutch")  # fmt: skip
    wheel_force = d.add(PythonFunction(code="def f(t, tq, i):\n    return tq * i * 0.95 / 0.5\n", num_inputs=2),
                        name="tractive_force")  # fmt: skip
    net = d.add(Sum(signs="+-"), name="net_force")
    accel = d.add(Gain(gain=1 / 40000), name="accel")
    kmh = d.add(Gain(gain=3.6), name="speed_kmh")
    # ECUs (50 ms): engine (cruise + exhaust brake) and TCU (AMT).
    speed_s = d.add(ZeroOrderHold(sample_time=TS), name="speed_sensor")
    rpm_s = d.add(ZeroOrderHold(sample_time=TS), name="rpm_sensor")
    err = d.add(Sum(signs="+-"), name="speed_error")
    cruise = d.add(DiscretePID(P=0.15, I=0.02, upper=1.0, lower=0.0, anti_windup="clamping", sample_time=TS),
                   name="cruise_control")  # fmt: skip
    set_v = d.add(Constant(value="set_speed"), name="set_speed_kmh")
    brake_on = d.add(PythonFunction(code="def f(t, v, vset, fitted):\n    return 1.0 if fitted > 0.5 and v > vset + p[0] else 0.0\n",
                                    num_inputs=3, parameters="[brake_margin]"), name="exhaust_brake_request")  # fmt: skip
    fitted = d.add(Constant(value="exhaust_brake"), name="brake_fitted")
    amt = d.add(StateChart(definition=AMT_CHART, sample_time=TS), name="amt_tcu")
    # Wiring.
    d.chain(v, pos, route)
    d.connect(v, (loads, 0))
    d.connect(route, (loads, 1))
    d.chain(gear, ratio, overall)
    d.connect(v, (rpm, 0))
    d.connect(overall, (rpm, 1))
    d.connect(rpm, (engine, 0))
    d.connect(cruise, (engine, 1))
    d.connect(brake_on, (engine, 2))
    d.connect(engine, (interrupt, 0))
    d.connect((amt, 1), (interrupt, 1))
    d.connect(interrupt, (wheel_force, 0))
    d.connect(overall, (wheel_force, 1))
    d.connect(wheel_force, (net, 0))
    d.connect(loads, (net, 1))
    d.chain(net, accel, v)
    d.chain(v, kmh, speed_s)
    d.chain(rpm, rpm_s)
    d.connect(set_v, (err, 0))
    d.connect(speed_s, (err, 1))
    d.chain(err, cruise)
    d.connect(speed_s, (brake_on, 0))
    d.connect(set_v, (brake_on, 1))
    d.connect(fitted, (brake_on, 2))
    d.connect(rpm_s, (amt, 0))
    d.connect(brake_on, (amt, 1))
    d.connect((amt, 0), gear)
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(kmh, (scope, 0))
    d.connect(rpm, (scope, 1))
    d.connect((amt, 0), (scope, 2))
    for k, (src, name) in enumerate(((kmh, "speed"), (rpm, "rpm"), ((amt, 0), "gear"), (brake_on, "exhaust_brake_on"),
                                     (route, "grade"))):  # fmt: skip
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    for k, b in enumerate(d.blocks):
        b.meta["position"] = [float(160 * (k % 6)), float(110 * (k // 6))]
    d.tests = [
        TestCase(
            "the climb: AMT keeps the engine in its torque band",
            "On the 6 % climb the truck slows; the gearbox downshifts and the engine stays between 1000 and 1700 rpm",
            stop_time=110.0,
            checks=[Check("bounds", "rpm", {"lower": 950.0, "upper": 1750.0, "t_from": 40.0, "t_to": 110.0})],
        ),
        TestCase(
            "the descent: the exhaust brake limits the speed",
            "On the 6 % descent the exhaust brake (with the engine high in 11th gear) holds the truck below 100 km/h",
            stop_time=420.0,
            checks=[Check("bounds", "speed", {"lower": 30.0, "upper": 100.0, "t_from": 190.0, "t_to": 420.0})],
        ),
    ]
    return d


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "truck.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    no_brake = simulate(d, params={"exhaust_brake": 0.0})
    down = res.t > 190
    print(f"climb: lowest speed {np.min(res['speed'][res.t < 140]):.0f} km/h, lowest gear {np.min(res['gear']):.0f}")
    print(f"descent: max speed {np.max(res['speed'][down]):.0f} km/h with the exhaust brake, "
          f"{np.max(no_brake['speed'][down]):.0f} km/h without")  # fmt: skip
    return res


if __name__ == "__main__":
    main()
