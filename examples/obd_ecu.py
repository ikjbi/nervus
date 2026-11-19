"""A simulated engine ECU with on-board diagnostics that answers a real OBD-II tool.

The model has two diagnostic monitors, like an engine ECU:

* **P0302, cylinder 2 misfire**: from 20 s, cylinder 2 misfires. The raw test result comes from a misfire
  counter; the monitor only runs with a warm engine (coolant above 40 °C, the *enable* input), debounces the
  result, and needs two key cycles with a misfire to confirm the code and switch the MIL on (two-trip).
* **P0171, system too lean**: fails when the long-term fuel trim is above +20 %. The fuel trim here stays at
  +4 %, so this monitor passes: it shows as *ready* but sets no code.

A key cycle starts every 30 s (key off and on). The **OBD Responder** publishes engine speed, vehicle speed,
coolant temperature and engine load, plus both trouble codes, to a simulated ECU. When a tool clears the codes
(mode 04) the responder's *clear* output resets the monitors, and the readiness drops back to "not complete".

Run it in real time and connect any OBD program to the printed serial port::

    uv run python -m nervus.obd simulate examples/obd_ecu.nervus
    uv run python -m nervus.obd dtc --port /dev/ttys007            # in another terminal

Run with ``uv run python examples/obd_ecu.py`` to build the model and read it with the Nervus OBD client.
"""

from __future__ import annotations

from pathlib import Path

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    CompareToConstant,
    Constant,
    DiagnosticMonitor,
    Gain,
    Integrator,
    ObdResponder,
    Outport,
    Product,
    Pulse,
    Scope,
    Sine,
    Step,
    Sum,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.1  # the ECU's diagnostic task


def build() -> Diagram:
    d = Diagram("obd_ecu")
    d.settings.t_final = 90.0
    d.settings.solver = "rk4"
    d.settings.step = TS
    ws = d.workspace
    ws.add(Variable("coolant_tau", 25.0, "Warm-up time constant of the coolant", "s"))
    ws.add(Variable("misfire_limit", 0.5, "Misfire test threshold (fraction of a counting window)", "-"))
    ws.add(Variable("ltft_limit", 20.0, "Lean limit for the long-term fuel trim", "%"))

    # Engine signals.
    rpm = d.add(Sum(signs="++"), name="rpm")
    d.connect(d.add(Constant(value=1500.0), name="rpm_base"), (rpm, 0))
    d.connect(d.add(Sine(amplitude=700.0, frequency=0.3), name="rpm_drive"), (rpm, 1))
    speed = d.add(Gain(gain=0.03), name="speed")  # km/h, a fixed gear
    d.chain(rpm, speed)
    load = d.add(Sine(amplitude=15.0, frequency=0.3, bias=35.0), name="engine_load")
    # Coolant: first-order warm-up from 20 °C towards 90 °C.
    target = d.add(Constant(value=90.0), name="thermostat")
    warm_err = d.add(Sum(signs="+-"), name="warm_error")
    coolant = d.add(Integrator(initial=20.0), name="coolant_temp")
    d.connect(target, (warm_err, 0))
    d.connect(coolant, (warm_err, 1))
    d.chain(warm_err, d.add(Gain(gain="1 / coolant_tau"), name="warm_rate"), coolant)
    # Cylinder 2 misfires from 20 s: the raw test sees a misfire in most counting windows.
    misfire = d.add(Step(time=20.0, initial=0.0, final=1.0), name="cyl2_misfire")
    window = d.add(Pulse(period=0.4, duty=75.0, sample_time=TS), name="misfire_windows")
    raw = d.add(Product(ops="**"), name="misfire_rate")
    d.connect(misfire, (raw, 0))
    d.connect(window, (raw, 1))
    misfire_test = d.add(CompareToConstant(operator=">=", constant="misfire_limit"), name="misfire_test")
    d.chain(raw, misfire_test)
    warm = d.add(CompareToConstant(operator=">=", constant=40.0), name="engine_warm")
    d.chain(coolant, warm)
    ltft = d.add(Constant(value=4.0), name="ltft_pct")
    lean_test = d.add(CompareToConstant(operator=">=", constant="ltft_limit"), name="lean_test")
    d.chain(ltft, lean_test)
    key = d.add(Pulse(period=30.0, duty=1.0, delay=29.5, sample_time=TS), name="key_cycle")

    # Diagnostics.
    p0302 = d.add(
        DiagnosticMonitor(
            dtc="P0302", threshold=10.0, enable_input=True, cycle_input=True, clear_input=True, sample_time=TS
        ),
        name="P0302_monitor",
    )
    p0171 = d.add(
        DiagnosticMonitor(dtc="P0171", threshold=20.0, cycle_input=True, clear_input=True, sample_time=TS),
        name="P0171_monitor",
    )
    obd = d.add(
        ObdResponder(pids="rpm, speed, coolant_temp, engine_load", dtcs="P0302, P0171", sample_time=TS),
        name="obd",
    )
    d.connect(misfire_test, (p0302, 0))
    d.connect(warm, (p0302, 1))
    d.connect(key, (p0302, 2))
    d.connect(obd, (p0302, 3))
    d.connect(lean_test, (p0171, 0))
    d.connect(key, (p0171, 1))
    d.connect(obd, (p0171, 2))
    for k, src in enumerate((rpm, speed, coolant, load)):
        d.connect(src, (obd, k))
    d.connect((p0302, 4), (obd, 4))
    d.connect((p0171, 4), (obd, 5))
    outs = (("mil", p0302, 0), ("pending", p0302, 1), ("confirmed", p0302, 2), ("misfire_ready", p0302, 3),
            ("lean_ready", p0171, 3))  # fmt: skip
    for k, (name, blk, port) in enumerate(outs):
        d.connect((blk, port), d.add(Outport(port=k + 1), name=name))
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(coolant, (scope, 0))
    d.connect((p0302, 1), (scope, 1))
    d.connect((p0302, 0), (scope, 2))
    d.tests = [
        TestCase(
            "misfire: pending in the first cycle, MIL in the second",
            "Cylinder 2 misfires from 20 s: pending at once, confirmed with the MIL after the second key cycle",
            stop_time=45.0,
            checks=[
                Check("bounds", "mil", {"lower": 0.0, "upper": 0.0, "t_from": 0.0, "t_to": 29.0}),
                Check("bounds", "pending", {"lower": 1.0, "upper": 1.0, "t_from": 22.0, "t_to": 29.0}),
                Check("final_value", "mil", {"value": 1.0}),
                Check("final_value", "confirmed", {"value": 1.0}),
            ],
        ),
        TestCase(
            "lean monitor passes",
            "The fuel trim is normal: P0171 completes (ready) and sets nothing",
            stop_time=10.0,
            checks=[Check("final_value", "lean_ready", {"value": 1.0})],
        ),
    ]
    _place(d)
    return d


def _place(d: Diagram) -> None:
    positions = {
        "rpm_base": (0, 0), "rpm_drive": (0, 70), "rpm": (130, 30), "speed": (260, 80), "engine_load": (130, 150),
        "thermostat": (0, 240), "warm_error": (130, 250), "warm_rate": (240, 250), "coolant_temp": (350, 250),
        "engine_warm": (480, 330), "cyl2_misfire": (0, 420), "misfire_windows": (0, 500), "misfire_rate": (130, 450),
        "misfire_test": (260, 450), "ltft_pct": (0, 620), "lean_test": (130, 620), "key_cycle": (260, 540),
        "P0302_monitor": (640, 420), "P0171_monitor": (640, 620), "obd": (880, 200), "scope": (880, 40),
        "mil": (1060, 380), "pending": (1060, 440), "confirmed": (1060, 500), "misfire_ready": (1060, 560),
        "lean_ready": (1060, 640),
    }  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]


def main() -> SimResult:
    from nervus.obd import PIDS, Elm327, describe_dtc
    from nervus.obd_sim import ecu
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "obd_ecu.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    elm = Elm327(ecu())  # the Nervus OBD client, talking to the simulated ECU instead of a serial port
    elm.initialize()
    print("stored codes:", [f"{c} ({describe_dtc(c)})" for c in elm.trouble_codes("stored")])
    print("pending codes:", elm.trouble_codes("pending"))
    print(f"rpm {elm.read(PIDS['rpm']):.0f}")
    print("MIL on" if res["mil"][-1] else "MIL off", f"after {res.t[-1]:.0f} s")
    return res


if __name__ == "__main__":
    main()
