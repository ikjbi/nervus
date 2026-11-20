"""A coolant temperature sensor from the circuit to the ECU software, with its fault diagnosis.

**Hardware.** The sensor is an NTC thermistor (2 kΩ at 25 °C, β = 3600 K) in the engine, wired to the ECU. On the
ECU's circuit board a 2.49 kΩ pull-up resistor from the 5 V sensor supply forms a voltage divider with it, and an
RC filter (10 kΩ, 100 nF) protects the 12-bit ADC input:

    V_sig = 5 V · R_ntc / (R_ntc + R_pull)

**Software** (every 100 ms): ADC counts → temperature with a lookup table (the inverse of the divider, computed here
from the circuit as a supplier data sheet would give it), and two **range checks**: a voltage below 0.1 V means a
short to ground (code **P0117**, "circuit low"), above 4.9 V an open circuit (**P0118**, "circuit high"). While a code
is pending the ECU uses a substitute value of 80 °C instead of the measurement (limp home: the fan runs, the
engine is fuelled as if warm).

**Scenario**: the engine warms up from −10 °C to 95 °C in 5 minutes. With ``fault`` = 1 the harness breaks (open
circuit) at ``fault_time``; with ``fault`` = 2 the signal wire is shorted to ground.

Run with ``uv run python examples/ntc_sensor.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Capacitor,
    CompareToConstant,
    Constant,
    DataTypeConversion,
    Demux,
    DiagnosticMonitor,
    ElectricalReference,
    FromWorkspace,
    Gain,
    LogicalOperator,
    Lookup1D,
    Outport,
    PythonFunction,
    Resistor,
    Scope,
    Switch,
    Thermistor,
    VariableResistor,
    VoltageSensor,
    VoltageSource,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.1  # coolant temperature changes slowly: a 100 ms task is usual
R25, BETA, R_PULL, V_REF = 2000.0, 3600.0, 2490.0, 5.0

FAULTS = '''def f(t, temp):
    """Harness resistance [Ω] and resistance of the signal wire to ground [Ω] (fault injection)."""
    fault, at = p[0], p[1]
    broken = t >= at
    open_ = 1e8 if (fault == 1 and broken) else 0.5
    short = 0.05 if (fault == 2 and broken) else 1e9
    return [open_, short]
'''


def r_ntc(temp_c: float | np.ndarray) -> float | np.ndarray:
    return R25 * np.exp(BETA * (1.0 / (np.asarray(temp_c) + 273.15) - 1.0 / 298.15))


def v_sig(temp_c: float | np.ndarray, r_pull: float = R_PULL) -> float | np.ndarray:
    r = r_ntc(temp_c)
    return V_REF * r / (r + r_pull)


def table(r_pull: float = R_PULL) -> tuple[list[float], list[float]]:
    """The ECU's conversion table: ADC counts (rising) → °C, 23 points from 150 °C down to −40 °C."""
    temps = np.linspace(150.0, -40.0, 23)
    counts = v_sig(temps, r_pull) / V_REF * 4095.0
    return [float(c) for c in counts], [float(t) for t in temps]


def build() -> Diagram:
    d = Diagram("ntc_sensor")
    d.settings.t_final = 300.0
    d.settings.solver = "BDF"  # the 1 ms input filter is stiff next to the 100 ms task
    d.settings.max_step = TS
    ws = d.workspace
    counts, temps = table()
    for name, value, unit, desc in (
        ("R_pull", R_PULL, "Ω", "Pull-up resistor on the ECU board"),
        ("R_filter", 10e3, "Ω", "Input filter resistor"),
        ("C_filter", 100e-9, "F", "Input filter capacitor (with R_filter: τ = 1 ms)"),
        ("adc_counts_axis", counts, "counts", "Conversion table: ADC counts (rising)"),
        ("adc_temp_table", temps, "°C", "Conversion table: temperature at each count value"),
        ("V_low", 0.1, "V", "Below this: short to ground (P0117)"),
        ("V_high", 4.9, "V", "Above this: open circuit (P0118)"),
        ("T_substitute", 80.0, "°C", "Substitute temperature while a code is pending"),
        ("fault", 0.0, "-", "Fault injection: 0 none, 1 open circuit, 2 short to ground"),
        ("fault_time", 200.0, "s", "When the fault happens"),
    ):  # fmt: skip
        ws.add(Variable(name, value, desc, unit))
    # ---- engine and harness
    t_true = d.add(FromWorkspace(time=[0, 300], data=[[-10.0], [95.0]]), name="coolant_temp")
    faults = d.add(PythonFunction(code=FAULTS, num_inputs=1, output_width=2, parameters="[fault, fault_time]"),
                   name="fault_injection")  # fmt: skip
    split = d.add(Demux(num_outputs=2), name="fault_split")
    d.connect(t_true, faults)
    d.connect(faults, split)
    # ---- circuit
    gnd = d.add(ElectricalReference(), name="gnd")
    vref = d.add(VoltageSource(V=V_REF), name="sensor_supply_5V")
    pull = d.add(Resistor(R="R_pull"), name="R_pull")
    ntc = d.add(Thermistor(R25=R25, beta=BETA), name="ntc")
    harness = d.add(VariableResistor(R_min=1e-3), name="harness")
    short = d.add(VariableResistor(R_min=1e-3), name="short_to_ground")
    rf = d.add(Resistor(R="R_filter"), name="R_filter")
    cf = d.add(Capacitor(C="C_filter"), name="C_filter")
    adc_in = d.add(VoltageSensor(), name="adc_pin")
    links = (((vref, "p"), (pull, "p")), ((vref, "n"), (gnd, "p")), ((pull, "n"), (ntc, "p")), ((ntc, "n"), (harness, "p")),
             ((harness, "n"), (gnd, "p")), ((pull, "n"), (short, "p")), ((short, "n"), (gnd, "p")),
             ((pull, "n"), (rf, "p")), ((rf, "n"), (cf, "p")), ((cf, "n"), (gnd, "p")), ((rf, "n"), (adc_in, "p")),
             ((adc_in, "n"), (gnd, "p")))  # fmt: skip
    for a, b in links:
        d.link(a, b)
    d.connect(t_true, ntc)
    d.connect((split, 0), harness)
    d.connect((split, 1), short)
    # ---- ECU: ADC and conversion
    sample = d.add(ZeroOrderHold(sample_time=TS), name="adc_sample")
    to_counts = d.add(Gain(gain=4095.0 / V_REF), name="volts_to_counts")
    adc = d.add(DataTypeConversion(output_type="uint16", rounding="floor"), name="adc_counts")
    to_double = d.add(DataTypeConversion(output_type="double"), name="counts")
    conv = d.add(Lookup1D(breakpoints="adc_counts_axis", table="adc_temp_table"), name="temp_measured")
    volts = d.add(Gain(gain=V_REF / 4095.0), name="adc_volts")
    d.chain(adc_in, sample, to_counts, adc, to_double, conv)
    d.connect(to_double, volts)
    # ---- ECU: range checks, codes and substitute value
    low = d.add(CompareToConstant(operator="<", constant="V_low"), name="below_range")
    high = d.add(CompareToConstant(operator=">", constant="V_high"), name="above_range")
    d.connect(volts, low)
    d.connect(volts, high)
    p0117 = d.add(DiagnosticMonitor(dtc="P0117", threshold=5.0, confirm_cycles=1, sample_time=TS), name="P0117")
    p0118 = d.add(DiagnosticMonitor(dtc="P0118", threshold=5.0, confirm_cycles=1, sample_time=TS), name="P0118")
    d.connect(low, p0117)
    d.connect(high, p0118)
    any_code = d.add(LogicalOperator(operator="OR", num_inputs=2), name="sensor_failed")
    d.connect((p0117, 1), (any_code, 0))
    d.connect((p0118, 1), (any_code, 1))
    subst = d.add(Constant(value="T_substitute"), name="substitute")
    used = d.add(Switch(criterion="u1 != 0"), name="temp_used")
    d.connect(subst, (used, 0))
    d.connect(any_code, (used, 1))
    d.connect(conv, (used, 2))
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(t_true, (scope, 0))
    d.connect(conv, (scope, 1))
    d.connect(used, (scope, 2))
    outs = ((t_true, "true_temp"), (conv, "measured_temp"), (used, "ecu_temp"), (volts, "signal_volts"),
            ((p0117, 1), "P0117_pending"), ((p0118, 1), "P0118_pending"), ((p0118, 0), "mil"))  # fmt: skip
    for k, (src, name) in enumerate(outs):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    positions = {"coolant_temp": (0, 0), "fault_injection": (0, 300), "fault_split": (150, 300),
                 "sensor_supply_5V": (150, 80), "gnd": (150, 220), "R_pull": (300, 20), "ntc": (300, 120),
                 "harness": (300, 230), "short_to_ground": (450, 230), "R_filter": (450, 20), "C_filter": (600, 120),
                 "adc_pin": (600, 20), "adc_sample": (750, 20), "volts_to_counts": (880, 20), "adc_counts": (1010, 20),
                 "counts": (1140, 20), "temp_measured": (1270, 20), "adc_volts": (1140, 120),
                 "below_range": (1270, 120), "above_range": (1270, 200), "P0117": (1400, 120), "P0118": (1400, 220),
                 "sensor_failed": (1530, 160), "substitute": (1530, 60), "temp_used": (1660, 40), "scope": (1660, -80),
                 "true_temp": (1790, -40), "measured_temp": (1790, 20), "ecu_temp": (1790, 80),
                 "signal_volts": (1790, 140), "P0117_pending": (1790, 200), "P0118_pending": (1790, 260),
                 "mil": (1790, 320)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = [
        TestCase(
            "accurate from -10 to 95 °C",
            "The ECU reads the coolant temperature within 0.5 °C over the warm-up (after the filter settles)",
            stop_time=300.0,
            checks=[
                Check("bounds", "ecu_temp", {"lower": -11.0, "upper": 96.0, "t_from": 0.2}),
                Check("bounds", "P0118_pending", {"upper": 0.0}),
                Check("bounds", "P0117_pending", {"upper": 0.0}),
            ],
        ),
        TestCase(
            "open circuit: P0118 and the substitute value",
            "The harness breaks at 200 s: within 0.7 s the code is pending and the ECU uses 80 °C",
            stop_time=210.0,
            parameters={"fault": 1.0},
            checks=[
                Check("bounds", "P0118_pending", {"lower": 1.0, "t_from": 200.7}),
                Check("bounds", "ecu_temp", {"lower": 80.0, "upper": 80.0, "t_from": 200.7}),
            ],
        ),
        TestCase(
            "short to ground: P0117",
            "The signal wire is shorted to ground at 200 s: P0117 within 0.7 s",
            stop_time=210.0,
            parameters={"fault": 2.0},
            checks=[Check("bounds", "P0117_pending", {"lower": 1.0, "t_from": 200.7})],
        ),
    ]
    return d


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "ntc_sensor.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    err = np.ravel(res["measured_temp"]) - np.ravel(res["true_temp"])
    late = res.t > 1.0
    print(f"largest reading error: {np.max(np.abs(err[late])):.2f} °C")
    for temp in (-30, 20, 90, 120):
        dv = abs(float(v_sig(temp + 0.5)) - float(v_sig(temp - 0.5)))
        print(f"at {temp:4d} °C: {float(r_ntc(temp)):8.0f} Ω, {float(v_sig(temp)):.2f} V, "
              f"{1 / (dv / V_REF * 4095):.3f} °C per ADC count")  # fmt: skip
    return res


if __name__ == "__main__":
    main()
