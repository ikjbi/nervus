"""Engine operating modes: the state machine at the heart of every engine ECU.

An engine ECU does very different things depending on what the engine is doing. This example models the mode
logic with a State Chart running every 10 ms:

* **off**: key off, no fuel, no ignition.
* **crank**: key on, starter running, fuel on (cranking enrichment). If the engine has not started within
  3 s, the ECU stops cranking to protect the starter (**crank_fail**) until the key is turned off.
* **idle**: the engine runs on its own (> 600 rpm), pedal released: the idle speed controller holds the speed.
* **run**: pedal pressed: torque follows the driver.
* **stalled**: the engine stopped while the key is on: no fuel, and no automatic restart; the driver turns the
  key off and on again.
* **fuel_cut**: overrun fuel cut-off. Coasting with the pedal released above 1500 rpm needs no fuel at all, so the
  injectors are switched off. Fuel comes back when the driver presses the pedal, or when the speed drops below
  1100 rpm, early enough that the engine does not stall.

The thresholds are calibration parameters (``param`` in the chart, variables in the model workspace), so they
can be tuned like any other calibration. The test cases drive the inputs (key, engine speed, pedal) with
scenarios and check the modes and the outputs. The chart can be generated as C code for the ECU.

Run with ``uv run python examples/engine_modes.py``.
"""

from __future__ import annotations

from pathlib import Path

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import Inport, Outport, StateChart, ZeroOrderHold
from nervus.core import Check, Signal, TestCase, Variable

HERE = Path(__file__).parent

MODES = {"off": 0, "crank": 1, "crank_fail": 2, "idle": 3, "run": 4, "fuel_cut": 5, "stalled": 6}

CHART = """
input key, rpm, pedal
output fuel = 0, starter = 0, idle_ctrl = 0
param rpm_started, rpm_stalled, crank_limit, pedal_on, pedal_off, rpm_cut_on, rpm_cut_off, rpm_idle_max

state off
  entry: fuel = 0; starter = 0; idle_ctrl = 0

state crank
  entry: starter = 1; fuel = 1

state crank_fail
  entry: starter = 0; fuel = 0

state idle
  entry: starter = 0; fuel = 1; idle_ctrl = 1

state run
  entry: fuel = 1; idle_ctrl = 0

state fuel_cut
  entry: fuel = 0; idle_ctrl = 0

state stalled
  entry: fuel = 0; idle_ctrl = 0

transition off -> crank: key > 0.5
transition crank -> idle: rpm > rpm_started
transition crank -> crank_fail: after(crank_limit)
transition crank -> off: key < 0.5
transition crank_fail -> off: key < 0.5
transition idle -> off: key < 0.5
transition idle -> stalled: rpm < rpm_stalled
transition idle -> run: pedal > pedal_on
transition run -> off: key < 0.5
transition run -> stalled: rpm < rpm_stalled
transition run -> fuel_cut: pedal < pedal_off and rpm > rpm_cut_on
transition run -> idle: pedal < pedal_off and rpm < rpm_idle_max
transition fuel_cut -> off: key < 0.5
transition fuel_cut -> run: pedal > pedal_on
transition fuel_cut -> idle: rpm < rpm_cut_off
transition stalled -> off: key < 0.5
"""

CONSTANTS = {
    "rpm_started": (600.0, "rpm", "The engine runs on its own above this speed"),
    "rpm_stalled": (300.0, "rpm", "Below this speed the engine has stalled"),
    "crank_limit": (300, "samples", "Longest crank before giving up: 300 × 10 ms = 3 s (starter protection)"),
    "pedal_on": (2.0, "%", "The pedal counts as pressed above this"),
    "pedal_off": (1.0, "%", "The pedal counts as released below this"),
    "rpm_cut_on": (1500.0, "rpm", "Fuel cut-off when coasting above this speed"),
    "rpm_cut_off": (1100.0, "rpm", "Fuel comes back below this speed (before the engine could stall)"),
    "rpm_idle_max": (1200.0, "rpm", "Pedal released below this speed: idle control"),
}


def build() -> Diagram:
    d = Diagram("engine_modes")
    d.settings.t_final = 10.0
    d.settings.solver = "rk4"
    d.settings.step = 0.01
    for name, (value, unit, desc) in CONSTANTS.items():  # the chart's thresholds: calibration parameters
        d.workspace.add(Variable(name, value, desc, unit))
    key, rpm, pedal = (d.add(Inport(port=k + 1), name=n) for k, n in enumerate(("key", "rpm", "pedal")))
    chart = d.add(StateChart(definition=CHART, sample_time=0.01), name="modes")
    for k, src in enumerate((key, rpm, pedal)):
        z = d.add(ZeroOrderHold(sample_time=0.01), name=f"{src.name}_10ms")
        d.chain(src, z)
        d.connect(z, (chart, k))
    for k, name in enumerate(("fuel", "starter", "idle_ctrl", "mode")):
        d.connect((chart, k), d.add(Outport(port=k + 1), name=name))
    _place(d)
    d.tests = tests()
    return d


def _place(d: Diagram) -> None:
    for k, name in enumerate(("key", "rpm", "pedal")):
        d.block(name).meta["position"] = [0.0, 100.0 * k]
        d.block(f"{name}_10ms").meta["position"] = [150.0, 100.0 * k]
    d.block("modes").meta["position"] = [330.0, 70.0]
    for k, name in enumerate(("fuel", "starter", "idle_ctrl", "mode")):
        d.block(name).meta["position"] = [560.0, 70.0 * k]


def _sig(*points: tuple[float, float]) -> Signal:
    return Signal([p[0] for p in points], [[p[1]] for p in points], "linear")


def tests() -> list[TestCase]:
    crank_fail, idle, run, stalled = (MODES[k] for k in ("crank_fail", "idle", "run", "stalled"))
    start = _sig((0, 0), (0.5, 0), (0.6, 250), (1.5, 250), (2.0, 850), (10, 850))  # cranks, starts at ~1.9 s
    return [
        TestCase(
            "normal start",
            "Key on at 0.5 s: crank with the starter, then idle once the engine runs on its own",
            inputs={"key": _sig((0, 0), (0.49, 0), (0.5, 1), (10, 1)), "rpm": start, "pedal": _sig((0, 0), (10, 0))},
            stop_time=4.0,
            checks=[
                Check("final_value", "mode", {"value": idle}),
                Check(
                    "bounds", "starter", {"lower": 1.0, "upper": 1.0, "t_from": 0.6, "t_to": 1.7}
                ),  # 600 rpm at 1.79 s
                Check("final_value", "starter", {"value": 0.0}),
                Check("final_value", "idle_ctrl", {"value": 1.0}),
            ],
        ),
        TestCase(
            "failed start protects the starter",
            "The engine does not start: after 3 s of cranking the starter is switched off",
            inputs={"key": _sig((0, 1), (10, 1)), "rpm": _sig((0, 250), (10, 250)), "pedal": _sig((0, 0), (10, 0))},
            stop_time=5.0,
            checks=[
                Check("final_value", "mode", {"value": crank_fail}),
                Check("final_value", "starter", {"value": 0.0}),
                Check("bounds", "starter", {"lower": 1.0, "upper": 1.0, "t_from": 0.1, "t_to": 2.9}),
            ],
        ),
        TestCase(
            "overrun fuel cut-off",
            "Driving at 3000 rpm, then pedal released: no fuel while coasting, fuel back before stalling",
            inputs={
                "key": _sig((0, 1), (10, 1)),
                "rpm": _sig((0, 250), (0.3, 900), (1.0, 3000), (4.0, 3000), (8.0, 900), (10, 850)),
                "pedal": _sig((0, 0), (0.5, 0), (0.6, 30), (3.9, 30), (4.0, 0), (10, 0)),
            },
            stop_time=10.0,
            checks=[
                Check("bounds", "mode", {"lower": run, "upper": run, "t_from": 1.0, "t_to": 3.9}),
                Check("bounds", "fuel", {"lower": 0.0, "upper": 0.0, "t_from": 4.1, "t_to": 6.5}),
                Check("final_value", "mode", {"value": idle}),
                Check("final_value", "fuel", {"value": 1.0}),
            ],
        ),
        TestCase(
            "stall: no fuel and no automatic restart",
            "The engine stalls at idle with the key on: fuel off, and it waits for the driver to turn the key",
            inputs={
                "key": _sig((0, 1), (10, 1)),
                "rpm": _sig((0, 250), (0.3, 800), (2.0, 800), (2.5, 100), (10, 0)),
                "pedal": _sig((0, 0), (10, 0)),
            },
            stop_time=4.0,
            checks=[
                Check("final_value", "fuel", {"value": 0.0}),
                Check("final_value", "starter", {"value": 0.0}),
                Check("final_value", "mode", {"value": stalled}),
            ],
        ),
    ]


def main() -> SimResult:
    d = build()
    save(d, HERE / "engine_modes.nervus")
    from nervus.testing import run_tests

    for r in run_tests(d):
        print(r.summary())
    case = d.tests[2]
    res = simulate(d, case.stop_time, inputs=case.inputs)
    print(f"modes during the fuel cut-off scenario: {sorted(set(res['mode'].ravel().astype(int)))}")
    return res


if __name__ == "__main__":
    main()
