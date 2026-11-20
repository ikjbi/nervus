"""Ignition timing from a speed/load map, and knock control.

The spark has to fire before top dead centre so the pressure peaks just after it: the **advance** (degrees of
crank angle before TDC). Too little wastes work; the best torque comes at **MBT** (minimum advance for best
torque). But at high load the end of the charge can ignite by itself before the flame reaches it: **knock**,
a pressure wave that damages pistons. The advance where knock starts (the **knock limit**) is lower with
low-octane fuel, hot intake air and high load.

* **ECU (10 ms task)**: the base advance from a map over engine speed and load (calibration data). A knock
  sensor (an accelerometer on the block) reports knock; each knock event **retards** the spark by 3°, then the
  retard recovers by 1° per second, so the engine runs just at the knock limit. This becomes C code.
* **Engine (plant)**: the knock limit and MBT from maps; knock intensity grows with the advance beyond the
  limit (with cycle-to-cycle scatter, a Sensor Model with noise); the torque falls off quadratically away
  from MBT.

The scenario: full load at 2500 rpm; at 4 s the car gets a tank of low-octane fuel (the knock limit drops by
6°).

Run with ``uv run python examples/ignition_knock.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    CompareToConstant,
    Constant,
    Gain,
    Inport,
    Lookup2D,
    Outport,
    PythonFunction,
    Saturation,
    Scope,
    SensorModel,
    Step,
    Subsystem,
    Sum,
    UnitDelay,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.01

RPM_AXIS = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0]
LOAD_AXIS = [20.0, 50.0, 80.0, 100.0]
# Base advance [° before TDC]: more at high speed (less time to burn), less at high load (knock).
ADVANCE_MAP = [
    [24.0, 18.0, 12.0, 9.0],
    [32.0, 25.0, 17.0, 13.0],
    [38.0, 30.0, 21.0, 17.0],
    [40.0, 33.0, 24.0, 20.0],
    [41.0, 35.0, 26.0, 22.0],
    [42.0, 36.0, 27.0, 23.0],
]
# Knock limit with the reference fuel (95 RON) [°]: the calibration keeps 2-3° of margin to it.
KNOCK_LIMIT_MAP = [[a + 3.0 for a in row] for row in ADVANCE_MAP]
# MBT [°]: at full load the knock limit is below MBT, so the engine is knock limited.
MBT_MAP = [[a + 5.0 + 3.0 * (load / 100.0) for a, load in zip(row, LOAD_AXIS, strict=True)] for row in ADVANCE_MAP]

KNOCK = '''def f(t, advance, knock_limit):
    """Knock intensity [-]: 0 below the knock limit, then growing quickly with the advance beyond it."""
    over = advance - knock_limit
    return 0.0 if over <= 0 else over * over
'''

TORQUE = '''def f(t, advance, mbt):
    """Torque efficiency of the spark timing: 1 at MBT, falling off quadratically (1 % at 3°, 4 % at 6°)."""
    return 1.0 - 0.0011 * (advance - mbt) ** 2
'''

CONSTANTS = {
    "knock_step": (3.0, "°", "Retard per detected knock event"),
    "knock_recover": (1.0, "°/s", "How fast the retard is taken back"),
    "max_retard": (12.0, "°", "Largest retard"),
    "knock_threshold": (0.5, "-", "Knock sensor intensity that counts as knock"),
}


def build_ecu() -> Subsystem:
    """Spark advance = base map − knock retard; the retard steps up on knock and recovers slowly. 10 ms."""
    s = Diagram("ecu")
    rpm = s.add(Inport(port=1), name="rpm")
    load = s.add(Inport(port=2), name="load_pct")
    knock_sig = s.add(Inport(port=3), name="knock_sensor")
    base = s.add(Lookup2D(row_breakpoints="rpm_axis", column_breakpoints="load_axis", table="advance_map"),
                 name="base_advance")  # fmt: skip
    detected = s.add(CompareToConstant(operator=">", constant="knock_threshold"), name="knock_detected")
    step = s.add(Gain(gain="knock_step"), name="retard_step")
    recover = s.add(Constant(value=f"knock_recover * {TS}"), name="recover_per_sample")
    new = s.add(Sum(signs="++-"), name="retard_update")
    limit = s.add(Saturation(upper="max_retard", lower=0.0), name="retard_limits")
    memory = s.add(UnitDelay(initial=0.0, sample_time=TS), name="retard")
    advance = s.add(Sum(signs="+-"), name="spark_advance")
    s.connect(rpm, (base, 0))
    s.connect(load, (base, 1))
    s.chain(knock_sig, detected, step)
    s.connect(memory, (new, 0))
    s.connect(step, (new, 1))
    s.connect(recover, (new, 2))
    s.chain(new, limit, memory)
    s.connect(base, (advance, 0))
    s.connect(memory, (advance, 1))
    s.connect(advance, s.add(Outport(port=1), name="advance"))
    s.connect(memory, s.add(Outport(port=2), name="knock_retard"))
    positions = {"rpm": (0, 0), "load_pct": (0, 80), "base_advance": (140, 30), "knock_sensor": (0, 200),
                 "knock_detected": (140, 200), "retard_step": (270, 200), "recover_per_sample": (270, 290),
                 "retard_update": (400, 220), "retard_limits": (520, 220), "retard": (640, 220),
                 "spark_advance": (520, 60), "advance": (660, 60), "knock_retard": (780, 220)}  # fmt: skip
    for name, (x, y) in positions.items():
        s.block(name).meta["position"] = [float(x), float(y)]
    return Subsystem(system=s, sample_time=TS)


def build() -> Diagram:
    d = Diagram("ignition_knock")
    d.settings.t_final = 12.0
    d.settings.solver = "rk4"
    d.settings.step = TS
    ws = d.workspace
    ws.add(Variable("rpm_axis", RPM_AXIS, "Speed axis of the ignition maps", "rpm"))
    ws.add(Variable("load_axis", LOAD_AXIS, "Load axis of the ignition maps", "%"))
    ws.add(Variable("advance_map", ADVANCE_MAP, "Base spark advance", "°"))
    ws.add(Variable("knock_limit_map", KNOCK_LIMIT_MAP, "Knock-limited advance with 95 RON fuel (engine)", "°"))
    ws.add(Variable("mbt_map", MBT_MAP, "Advance for best torque (engine)", "°"))
    for name, (value, unit, desc) in CONSTANTS.items():
        ws.add(Variable(name, value, desc, unit))
    rpm = d.add(Constant(value=2500.0), name="engine_rpm")
    load = d.add(Constant(value=100.0), name="load")
    fuel = d.add(Step(time=4.0, initial=0.0, final=-6.0), name="low_octane_fuel")  # knock limit -6°
    ecu = d.add(build_ecu(), name="ECU")
    limit = d.add(Lookup2D(row_breakpoints="rpm_axis", column_breakpoints="load_axis", table="knock_limit_map"),
                  name="knock_limit_95")  # fmt: skip
    limit_now = d.add(Sum(signs="++"), name="knock_limit")
    mbt = d.add(Lookup2D(row_breakpoints="rpm_axis", column_breakpoints="load_axis", table="mbt_map"), name="mbt")
    intensity = d.add(PythonFunction(code=KNOCK, num_inputs=2), name="knock_intensity")
    sensor = d.add(SensorModel(noise=0.1, y_min=0.0, sample_time=TS, seed=7), name="knock_sensor")
    efficiency = d.add(PythonFunction(code=TORQUE, num_inputs=2), name="spark_efficiency")
    for m in (limit, mbt):
        d.connect(rpm, (m, 0))
        d.connect(load, (m, 1))
    d.connect(limit, (limit_now, 0))
    d.connect(fuel, (limit_now, 1))
    d.connect(rpm, (ecu, 0))
    d.connect(load, (ecu, 1))
    d.connect(sensor, (ecu, 2))
    d.connect((ecu, 0), (intensity, 0))
    d.connect(limit_now, (intensity, 1))
    d.chain(intensity, sensor)
    d.connect((ecu, 0), (efficiency, 0))
    d.connect(mbt, (efficiency, 1))
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect((ecu, 0), (scope, 0))
    d.connect(limit_now, (scope, 1))
    d.connect((ecu, 1), (scope, 2))
    for k, (src, name) in enumerate((((ecu, 0), "advance"), ((ecu, 1), "retard"), ((efficiency, 0), "torque_factor"),
                                     ((limit_now, 0), "knock_limit_deg"))):  # fmt: skip
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    positions = {"engine_rpm": (0, 0), "load": (0, 80), "low_octane_fuel": (0, 300), "ECU": (200, 20),
                 "knock_limit_95": (200, 220), "knock_limit": (360, 260), "mbt": (200, 380),
                 "knock_intensity": (520, 200), "knock_sensor": (660, 200), "spark_efficiency": (520, 360),
                 "scope": (660, -60), "advance": (820, 20), "retard": (820, 90), "torque_factor": (820, 360),
                 "knock_limit_deg": (520, 290)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = [
        TestCase(
            "no knock with good fuel",
            "With 95 RON the calibration keeps 3° from the knock limit: no retard",
            stop_time=4.0,
            checks=[Check("bounds", "retard", {"lower": 0.0, "upper": 0.0})],
        ),
        TestCase(
            "low-octane fuel: knock control finds the limit",
            "The knock limit drops 6°; the ECU retards until the engine runs just at the new limit",
            stop_time=12.0,
            checks=[
                Check("bounds", "retard", {"lower": 2.0, "upper": 9.0, "t_from": 8.0, "t_to": 12.0}),
                Check("bounds", "torque_factor", {"lower": 0.7, "upper": 0.9, "t_from": 8.0, "t_to": 12.0}),
            ],
        ),
    ]
    return d


def main() -> SimResult:
    from nervus.codegen import generate_c
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "ignition_knock.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    late = res.t > 8
    print(f"after the fuel change: retard {np.mean(res['retard'][late]):.1f}°, advance {np.mean(res['advance'][late]):.1f}° "
          f"(knock limit {res['knock_limit_deg'][-1]:.1f}°), torque {100 * np.mean(res['torque_factor'][late]):.1f} %")  # fmt: skip
    code = generate_c(d.block("ECU"))
    print("ECU C code:", ", ".join(code.files))
    return res


if __name__ == "__main__":
    main()
