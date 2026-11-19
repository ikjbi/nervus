"""Gear-shift logic of an automatic transmission, with a car to drive it.

An automatic gearbox is controlled by its own ECU, the TCU (transmission control unit). Its core is the
**shift schedule**: two maps over (gear, pedal position) that give the vehicle speed at which to shift up and
the speed at which to shift down. A State Chart with one state per gear compares the vehicle speed with the
two thresholds:

* **Upshift** when the speed rises above the upshift speed of the current gear. With more pedal the
  thresholds are higher, so the engine revs further before the next gear (more power when the driver asks
  for it, lower engine speed and fuel consumption when cruising).
* **Downshift** when the speed falls below the downshift speed. Pressing the pedal fully raises the
  downshift speed, so the gearbox drops a gear for acceleration (**kickdown**).
* **Hysteresis**: the downshift speed of a gear is always below the upshift speed of the gear below, and the
  chart stays at least ``min_gear_time`` in a gear, so the gearbox does not hunt between two gears.
* While a shift is in progress (``shift_time``) the engine torque is cut, like a real gearbox does to
  synchronise the speeds.

The car (continuous time) has an engine with a full-load torque curve, the gear ratios and final drive,
rolling resistance, aerodynamic drag and road grade:

    m dv/dt = T_engine * i_gear * i_final * eta / r_wheel - F_aero - F_roll - m g sin(grade)

The engine speed follows from the vehicle speed and the overall ratio (the clutch is locked; below idle speed
the clutch slips). The TCU is an atomic subsystem with a 10 ms sample time, so it can be generated as C code.

Run with ``uv run python examples/gear_shift.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Constant,
    FromWorkspace,
    Gain,
    Inport,
    Integrator,
    Lookup1D,
    Lookup2D,
    MinMax,
    Outport,
    Product,
    PythonFunction,
    Scope,
    StateChart,
    Subsystem,
    Sum,
    UnitDelay,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent

GEARS = [1.0, 2.0, 3.0, 4.0, 5.0]
PEDAL_AXIS = [0.0, 50.0, 100.0]
#                   pedal 0 %, 50 %, 100 %      vehicle speed [km/h]
UPSHIFT = [
    [15.0, 25.0, 40.0],  # 1 -> 2
    [30.0, 45.0, 70.0],  # 2 -> 3
    [45.0, 65.0, 100.0],  # 3 -> 4
    [60.0, 85.0, 130.0],  # 4 -> 5
    [999.0, 999.0, 999.0],  # 5: no higher gear
]
DOWNSHIFT = [
    [-1.0, -1.0, -1.0],  # 1: no lower gear
    [10.0, 15.0, 30.0],  # 2 -> 1
    [22.0, 32.0, 55.0],  # 3 -> 2
    [35.0, 50.0, 85.0],  # 4 -> 3
    [50.0, 68.0, 110.0],  # 5 -> 4
]

CHART = """
input speed, up_speed, down_speed
output gear = 1, shifting = 0
param min_gear_time, shift_time

state g1
  entry: gear = 1; shifting = 0
state g2
  entry: gear = 2; shifting = 1
  during: shifting = 1 if t_in_state < shift_time else 0
state g3
  entry: gear = 3; shifting = 1
  during: shifting = 1 if t_in_state < shift_time else 0
state g4
  entry: gear = 4; shifting = 1
  during: shifting = 1 if t_in_state < shift_time else 0
state g5
  entry: gear = 5; shifting = 1
  during: shifting = 1 if t_in_state < shift_time else 0

transition g1 -> g2: speed > up_speed and after(min_gear_time)
transition g2 -> g3: speed > up_speed and after(min_gear_time)
transition g2 -> g1: speed < down_speed and after(min_gear_time)
transition g3 -> g4: speed > up_speed and after(min_gear_time)
transition g3 -> g2: speed < down_speed and after(min_gear_time)
transition g4 -> g5: speed > up_speed and after(min_gear_time)
transition g4 -> g3: speed < down_speed and after(min_gear_time)
transition g5 -> g4: speed < down_speed and after(min_gear_time)
"""

ROAD_LOADS = '''def f(t, v, grade):
    """Road loads [N] at speed v [m/s] on a grade [%]. p = [m kg, c_d*A m2, c_rr]"""
    m, cda, crr = p[0], p[1], p[2]
    slope = np.arctan(grade / 100.0)
    roll = m * 9.81 * crr * np.cos(slope) * min(1.0, v / 0.1)  # no rolling resistance at standstill
    return 0.5 * 1.2 * cda * v * v + roll + m * 9.81 * np.sin(slope)
'''

CONSTANTS = {
    "mass": (1500.0, "kg", "Vehicle mass"),
    "r_wheel": (0.31, "m", "Dynamic wheel radius"),
    "i_final": (3.9, "-", "Final drive ratio"),
    "eta_driveline": (0.92, "-", "Driveline efficiency"),
    "idle_rpm": (800.0, "rpm", "Engine idle speed (the clutch slips below it)"),
    "min_gear_time": (100, "samples", "Shortest time in a gear: 100 × 10 ms = 1 s (no hunting)"),
    "shift_time": (0.3, "s", "Torque cut while a shift is in progress"),
}

# Pedal [%] over time: full-throttle launch, light cruise, kickdown, then a steady pedal up a hill.
PEDAL = [(0, 0), (0.5, 0), (0.6, 100), (9, 100), (9.5, 20), (22, 20), (22.2, 100), (26, 100), (26.5, 60), (45, 60)]
GRADE = [(0, 0), (28, 0), (30, 10), (45, 10)]  # road grade [%]: a 10 % hill from 30 s


def build_tcu() -> Subsystem:
    """The transmission control unit: shift maps and the gear state chart, every 10 ms."""
    s = Diagram("tcu")
    speed = s.add(Inport(port=1), name="speed")
    pedal = s.add(Inport(port=2), name="pedal")
    chart = s.add(StateChart(definition=CHART), name="shift_logic")
    last = s.add(UnitDelay(initial=1.0), name="last_gear")  # the maps are read for the current gear
    up = s.add(Lookup2D(row_breakpoints=GEARS, column_breakpoints=PEDAL_AXIS, table="upshift_map"), name="up_map")
    down = s.add(Lookup2D(row_breakpoints=GEARS, column_breakpoints=PEDAL_AXIS, table="downshift_map"), name="down_map")
    for m in (up, down):
        s.connect(last, (m, 0))
        s.connect(pedal, (m, 1))
    s.connect(speed, (chart, 0))
    s.connect(up, (chart, 1))
    s.connect(down, (chart, 2))
    s.connect((chart, 0), last)
    s.connect((chart, 0), s.add(Outport(port=1), name="gear"))
    s.connect((chart, 1), s.add(Outport(port=2), name="shifting"))
    for name, pos in {
        "speed": (0, 0),
        "pedal": (0, 160),
        "last_gear": (120, 260),
        "up_map": (150, 80),
        "down_map": (150, 180),
        "shift_logic": (340, 60),
        "gear": (560, 40),
        "shifting": (560, 140),
    }.items():
        s.block(name).meta["position"] = [float(pos[0]), float(pos[1])]
    return Subsystem(system=s, sample_time=0.01)


def _place(d: Diagram, positions: dict[str, tuple[int, int]]) -> None:
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]


def build_gearbox() -> Subsystem:
    """Gear ratio and engine speed from the vehicle speed (locked clutch; it slips below idle speed)."""
    s = Diagram("gearbox")
    gear = s.add(Inport(port=1), name="gear")
    v = s.add(Inport(port=2), name="v")
    ratio = s.add(Lookup1D(breakpoints=GEARS, table="gear_ratios", interpolation="nearest"), name="gear_ratio")
    overall = s.add(Gain(gain="i_final"), name="overall_ratio")
    wheel = s.add(Gain(gain="1 / r_wheel"), name="wheel_speed")  # rad/s
    eng = s.add(Product(ops="**"), name="engine_rad_s")
    to_rpm = s.add(Gain(gain=60 / (2 * np.pi)), name="to_rpm")
    rpm = s.add(MinMax(function="max"), name="clutch_slip")
    idle = s.add(Constant(value="idle_rpm"), name="idle")
    s.chain(gear, ratio, overall)
    s.chain(v, wheel)
    s.connect(wheel, (eng, 0))
    s.connect(overall, (eng, 1))
    s.chain(eng, to_rpm)
    s.connect(to_rpm, (rpm, 0))
    s.connect(idle, (rpm, 1))
    s.connect(overall, s.add(Outport(port=1), name="ratio"))
    s.connect(rpm, s.add(Outport(port=2), name="rpm"))
    _place(s, {"gear": (0, 0), "gear_ratio": (120, 0), "overall_ratio": (240, 0), "v": (0, 110),
               "wheel_speed": (240, 110), "engine_rad_s": (370, 60), "to_rpm": (490, 60), "idle": (490, 150),
               "clutch_slip": (610, 80), "ratio": (730, 0), "rpm": (730, 80)})  # fmt: skip
    return Subsystem(system=s)


def build_engine() -> Subsystem:
    """Engine torque: pedal × full-load torque − friction, cut to zero while the gearbox shifts."""
    s = Diagram("engine")
    rpm = s.add(Inport(port=1), name="rpm")
    pedal = s.add(Inport(port=2), name="pedal")
    shifting = s.add(Inport(port=3), name="shifting")
    full_load = s.add(Lookup1D(breakpoints="torque_rpm", table="torque_max"), name="full_load")
    friction = s.add(Lookup1D(breakpoints="friction_rpm", table="torque_friction"), name="friction")
    pedal_frac = s.add(Gain(gain=0.01), name="pedal_fraction")
    drive = s.add(Product(ops="**"), name="driver_torque")
    net = s.add(Sum(signs="+-"), name="minus_friction")  # engine braking when the pedal is released
    one = s.add(Constant(value=1.0), name="one")
    cut = s.add(Sum(signs="+-"), name="torque_cut")  # 1 - shifting
    torque = s.add(Product(ops="**"), name="engine_torque")
    s.chain(rpm, full_load)
    s.chain(rpm, friction)
    s.chain(pedal, pedal_frac)
    s.connect(pedal_frac, (drive, 0))
    s.connect(full_load, (drive, 1))
    s.connect(drive, (net, 0))
    s.connect(friction, (net, 1))
    s.connect(one, (cut, 0))
    s.connect(shifting, (cut, 1))
    s.connect(net, (torque, 0))
    s.connect(cut, (torque, 1))
    s.connect(torque, s.add(Outport(port=1), name="torque"))
    _place(s, {"rpm": (0, 60), "full_load": (130, 0), "friction": (130, 100), "pedal": (0, 190),
               "pedal_fraction": (130, 190), "driver_torque": (260, 30), "minus_friction": (380, 70),
               "one": (0, 280), "shifting": (0, 350), "torque_cut": (260, 300), "engine_torque": (500, 120),
               "torque": (620, 120)})  # fmt: skip
    return Subsystem(system=s)


def build_body() -> Subsystem:
    """Longitudinal dynamics: wheel force from the engine torque, minus the road loads."""
    s = Diagram("body")
    torque = s.add(Inport(port=1), name="torque")
    ratio = s.add(Inport(port=2), name="ratio")
    grade = s.add(Inport(port=3), name="grade")
    wheel_torque = s.add(Product(ops="**"), name="wheel_torque")
    force = s.add(Gain(gain="eta_driveline / r_wheel"), name="tractive_force")
    loads = s.add(PythonFunction(code=ROAD_LOADS, num_inputs=2, parameters="[mass, cd_area, c_rr]"), name="road_loads")
    net = s.add(Sum(signs="+-"), name="net_force")
    accel = s.add(Gain(gain="1 / mass"), name="accel")
    v = s.add(Integrator(lower=0.0), name="v")  # m/s
    s.connect(torque, (wheel_torque, 0))
    s.connect(ratio, (wheel_torque, 1))
    s.chain(wheel_torque, force)
    s.connect(force, (net, 0))
    s.connect(loads, (net, 1))
    s.chain(net, accel, v)
    s.connect(v, (loads, 0))
    s.connect(grade, (loads, 1))
    s.connect(v, s.add(Outport(port=1), name="v_out"))
    _place(s, {"torque": (0, 0), "ratio": (0, 80), "wheel_torque": (130, 30), "tractive_force": (250, 30),
               "grade": (0, 220), "road_loads": (250, 170), "net_force": (380, 50), "accel": (490, 50),
               "v": (600, 50), "v_out": (720, 50)})  # fmt: skip
    return Subsystem(system=s)


def build_vehicle() -> Subsystem:
    """The car: gearbox, engine and body."""
    s = Diagram("car")
    gear = s.add(Inport(port=1), name="gear")
    shifting = s.add(Inport(port=2), name="shifting")
    pedal = s.add(Inport(port=3), name="pedal")
    grade = s.add(Inport(port=4), name="grade")
    gearbox = s.add(build_gearbox(), name="gearbox")
    engine = s.add(build_engine(), name="engine")
    body = s.add(build_body(), name="body")
    kmh = s.add(Gain(gain=3.6), name="kmh")
    s.connect(gear, (gearbox, 0))
    s.connect(body, (gearbox, 1))
    s.connect((gearbox, 1), (engine, 0))
    s.connect(pedal, (engine, 1))
    s.connect(shifting, (engine, 2))
    s.connect(engine, (body, 0))
    s.connect((gearbox, 0), (body, 1))
    s.connect(grade, (body, 2))
    s.chain(body, kmh)
    s.connect(kmh, s.add(Outport(port=1), name="speed_kmh"))
    s.connect((gearbox, 1), s.add(Outport(port=2), name="engine_rpm"))
    s.connect(engine, s.add(Outport(port=3), name="torque"))
    _place(s, {"gear": (0, 0), "gearbox": (150, 10), "pedal": (0, 200), "shifting": (0, 280),
               "engine": (330, 190), "grade": (400, 100), "body": (560, 60), "kmh": (740, 60),
               "speed_kmh": (870, 60), "engine_rpm": (870, -40), "torque": (870, 200)})  # fmt: skip
    return Subsystem(system=s)


def build() -> Diagram:
    d = Diagram("gear_shift")
    d.settings.t_final = 45.0
    d.settings.solver = "rk4"
    d.settings.step = 0.01
    ws = d.workspace
    for name, (value, unit, desc) in CONSTANTS.items():
        ws.add(Variable(name, value, desc, unit))
    ws.add(Variable("gear_ratios", [3.5, 2.1, 1.4, 1.0, 0.8], "Gearbox ratio per gear", "-"))
    ws.add(Variable("torque_rpm", [800.0, 1500.0, 3000.0, 4500.0, 6000.0, 6500.0], "Full-load curve speeds", "rpm"))
    ws.add(Variable("torque_max", [110.0, 170.0, 200.0, 190.0, 150.0, 0.0], "Full-load torque", "Nm"))
    ws.add(Variable("friction_rpm", [800.0, 6000.0], "Friction torque speeds", "rpm"))
    ws.add(Variable("torque_friction", [8.0, 30.0], "Engine friction (engine braking) torque", "Nm"))
    ws.add(Variable("cd_area", 0.65, "Drag coefficient × frontal area", "m2"))
    ws.add(Variable("c_rr", 0.012, "Rolling resistance coefficient", "-"))
    ws.add(Variable("upshift_map", UPSHIFT, "Upshift speed per gear (rows) and pedal 0/50/100 % (columns)", "km/h"))
    ws.add(Variable("downshift_map", DOWNSHIFT, "Downshift speed per gear and pedal", "km/h"))

    t, p = zip(*PEDAL, strict=True)
    pedal = d.add(FromWorkspace(time=list(t), data=[[x] for x in p]), name="pedal")
    tg, g = zip(*GRADE, strict=True)
    grade = d.add(FromWorkspace(time=list(tg), data=[[x] for x in g]), name="grade")
    tcu = d.add(build_tcu(), name="tcu")
    car = d.add(build_vehicle(), name="car")
    d.connect((car, 0), (tcu, 0))
    d.connect(pedal, (tcu, 1))
    d.connect((tcu, 0), (car, 0))
    d.connect((tcu, 1), (car, 1))
    d.connect(pedal, (car, 2))
    d.connect(grade, (car, 3))
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect((car, 0), (scope, 0))
    d.connect((car, 1), (scope, 1))
    d.connect((tcu, 0), (scope, 2))
    for k, name in enumerate(("speed", "rpm", "gear")):
        out = d.add(Outport(port=k + 1), name=name)
        d.connect((car, 0) if k == 0 else (car, 1) if k == 1 else (tcu, 0), out)
    for name, pos in {
        "pedal": (0, 120),
        "grade": (0, 220),
        "tcu": (180, 40),
        "car": (400, 120),
        "scope": (640, 0),
        "speed": (640, 100),
        "rpm": (640, 170),
        "gear": (640, 240),
    }.items():
        d.block(name).meta["position"] = [float(pos[0]), float(pos[1])]
    d.tests = tests()
    return d


def tests() -> list[TestCase]:
    return [
        TestCase(
            "full-throttle launch shifts late",
            "With the pedal at 100 % the engine revs high before each upshift: 1 -> 2 at 40 km/h, 2 -> 3 at 70",
            stop_time=9.0,
            checks=[
                Check("bounds", "gear", {"lower": 1.0, "upper": 1.0, "t_from": 0.0, "t_to": 3.4}),
                Check("bounds", "speed", {"lower": 38.0, "upper": 200.0, "t_from": 3.5, "t_to": 9.0}),
                Check("bounds", "rpm", {"lower": 800.0, "upper": 6000.0}),
                Check("final_value", "gear", {"value": 3.0}),
            ],
        ),
        TestCase(
            "light pedal cruises in top gear",
            "At 20 % pedal the thresholds are low: the gearbox shifts up to 5th and the engine speed drops",
            stop_time=20.0,
            checks=[
                Check("final_value", "gear", {"value": 5.0}),
                Check("bounds", "rpm", {"lower": 1500.0, "upper": 2500.0, "t_from": 12.0, "t_to": 20.0}),
            ],
        ),
        TestCase(
            "kickdown",
            "Pressing the pedal fully at cruising speed drops two gears (one per second) for acceleration",
            stop_time=25.0,
            checks=[
                Check("bounds", "gear", {"lower": 4.0, "upper": 4.0, "t_from": 22.2, "t_to": 23.0}),
                Check("bounds", "gear", {"lower": 3.0, "upper": 3.0, "t_from": 23.2, "t_to": 25.0}),
            ],
        ),
        TestCase(
            "downshift on a hill",
            "A 10 % hill at a steady 60 % pedal: the car slows and the gearbox drops to 4th",
            stop_time=45.0,
            checks=[
                Check("bounds", "gear", {"lower": 5.0, "upper": 5.0, "t_from": 28.0, "t_to": 37.0}),
                Check("final_value", "gear", {"value": 4.0}),
            ],
        ),
    ]


def shifts(res: SimResult) -> list[tuple[float, int, int]]:
    """(time, from gear, to gear) of every shift in a result."""
    g = np.ravel(res["gear"]).astype(int)
    k = np.flatnonzero(np.diff(g)) + 1
    return [(float(res.t[i]), int(g[i - 1]), int(g[i])) for i in k]


def main() -> SimResult:
    d = build()
    save(d, HERE / "gear_shift.nervus")
    res = simulate(d)
    for t, a, b in shifts(res):
        print(f"t = {t:5.2f} s: {a} -> {b} at {np.interp(t, res.t, np.ravel(res['speed'])):5.1f} km/h")
    from nervus.testing import run_tests

    for r in run_tests(d):
        print(r.summary())
    return res


if __name__ == "__main__":
    main()
