"""Closed-loop lambda (air-fuel ratio) control with short- and long-term fuel trims.

A petrol engine's catalyst only works well at the stoichiometric air-fuel ratio (lambda = 1, AFR 14.7). The ECU
measures the air going into the engine (MAF sensor), injects the matching fuel, and corrects the amount with the
oxygen (lambda) sensor in the exhaust:

* **base fuel**: ``m_fuel = m_air / 14.7`` from the measured air charge
* **short-term fuel trim (STFT)**: a fast PI controller on the lambda error, limited to ±25 %
* **long-term fuel trim (LTFT)**: slowly learns the average STFT, so the STFT returns to 0 and has its full range
  available again. ECUs store the LTFT; a large LTFT points to a fault such as a vacuum leak or a clogged injector.

The plant has the effects that make lambda control hard: injector dead time, the transport delay of the exhaust
gas to the sensor (``n_exh`` × 10 ms) and the sensor's own response time. At t = 12 s an **unmetered air leak**
(``leak`` = 6 %) appears: air that the MAF sensor does not see. The engine runs lean, the STFT reacts within a
second, and over the next ~20 s the LTFT takes over.

The STFT and LTFT outputs are the same numbers you can read from your own car over OBD-II
(``python -m nervus.obd record --pids stft_b1,ltft_b1,...``, see docs/obd.md).

Run with ``uv run python examples/lambda_control.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Bias,
    Constant,
    DiscreteIntegrator,
    DiscretePID,
    Gain,
    Inport,
    IntegerDelay,
    Outport,
    Product,
    Scope,
    Step,
    Subsystem,
    Sum,
    TransferFunction,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
AFR_STOICH = 14.7


def _place(d: Diagram, positions: dict[str, tuple[int, int]]) -> None:
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]


def build_ecu() -> Subsystem:
    """The fuel task: base fuel from the air charge, corrected by the short- and long-term trims."""
    d = Diagram("fuel_control")
    air = d.add(Inport(port=1), name="air_charge_mg")
    lam = d.add(Inport(port=2), name="lambda_meas")
    base = d.add(Gain(gain=f"1 / {AFR_STOICH}"), name="base_fuel")
    err = d.add(Bias(bias=-1.0), name="lambda_error")  # > 0: lean, needs more fuel
    stft = d.add(
        DiscretePID(P="Kp_stft", I="Ki_stft", upper=0.25, lower=-0.25, anti_windup="clamping", sample_time=-1),
        name="stft",
    )
    ltft = d.add(DiscreteIntegrator(gain="K_ltft", upper=0.25, lower=-0.25, sample_time=-1), name="ltft")
    trims = d.add(Sum(signs="++"), name="total_trim")
    factor = d.add(Bias(bias=1.0), name="correction")
    fuel = d.add(Product(ops="**"), name="fuel_cmd_mg")
    t_inj = d.add(Gain(gain="1 / q_inj"), name="to_ms")
    dead = d.add(Bias(bias="t_dead"), name="dead_time")
    out = d.add(Outport(port=1), name="t_inj_ms")
    stft_pct = d.add(Gain(gain=100.0), name="stft_pct")
    ltft_pct = d.add(Gain(gain=100.0), name="ltft_pct")
    d.chain(air, base)
    d.chain(lam, err, stft, ltft)
    d.connect(stft, trims.in_port(0))
    d.connect(ltft, trims.in_port(1))
    d.chain(trims, factor)
    d.connect(base, fuel.in_port(0))
    d.connect(factor, fuel.in_port(1))
    d.chain(fuel, t_inj, dead, out)
    d.chain(stft, stft_pct, d.add(Outport(port=2), name="stft_out"))
    d.chain(ltft, ltft_pct, d.add(Outport(port=3), name="ltft_out"))
    _place(
        d,
        {
            "air_charge_mg": (0, 0),
            "base_fuel": (160, 0),
            "lambda_meas": (0, 200),
            "lambda_error": (160, 200),
            "stft": (320, 200),
            "ltft": (480, 300),
            "total_trim": (640, 200),
            "correction": (800, 200),
            "fuel_cmd_mg": (960, 20),
            "to_ms": (1120, 20),
            "dead_time": (1280, 20),
            "t_inj_ms": (1440, 20),
            "stft_pct": (480, 420),
            "stft_out": (640, 420),
            "ltft_pct": (640, 520),
            "ltft_out": (800, 520),
        },
    )
    return Subsystem(system=d, sample_time="Ts")


def build() -> Diagram:
    d = Diagram("lambda_control")
    d.settings.t_final = 40.0
    d.settings.solver = "rk4"
    d.settings.step = 0.005
    ws = d.workspace
    ws.add(Variable("Ts", 0.01, "Fuel task period", "s"))
    ws.add(Variable("Kp_stft", 0.1, "STFT proportional gain", "1/λ"))
    ws.add(Variable("Ki_stft", 1.0, "STFT integral gain", "1/(λ·s)"))
    ws.add(Variable("K_ltft", 0.1, "LTFT learning rate", "1/s"))
    ws.add(Variable("q_inj", 4.0, "Injector flow (nominal)", "mg/ms"))
    ws.add(Variable("t_dead", 0.4, "Injector dead time", "ms"))
    ws.add(Variable("injector_error", 0.0, "Actual injector flow error (e.g. -0.05 = clogged)", "-"))
    ws.add(Variable("leak", 0.06, "Unmetered air from t = 12 s (vacuum leak)", "-"))
    ws.add(Variable("n_exh", 8, "Exhaust transport delay to the sensor", "samples of 10 ms"))
    ws.add(Variable("tau_sensor", 0.1, "Lambda sensor time constant", "s"))

    load = d.add(Constant(value=250.0), name="part_load")
    tip_in = d.add(Step(time=4.0, final=150.0), name="tip_in")
    tip_out = d.add(Step(time=8.0, final=-150.0), name="tip_out")
    air = d.add(Sum(signs="+++"), name="air_charge_mg")
    leak = d.add(Step(time=12.0, initial=1.0, final="1 + leak"), name="air_leak")
    true_air = d.add(Product(ops="**"), name="actual_air_mg")
    ecu = d.add(build_ecu(), name="ECU")
    inj = d.add(Bias(bias="-t_dead"), name="injector_open_ms")
    flow = d.add(Gain(gain="q_inj * (1 + injector_error)"), name="fuel_mg")
    ratio = d.add(Product(ops="*/"), name="air_fuel_ratio")
    lam = d.add(Gain(gain=f"1 / {AFR_STOICH}"), name="lambda_cyl")
    sample = d.add(ZeroOrderHold(sample_time=0.01), name="exhaust_sample")
    delay = d.add(IntegerDelay(delay="n_exh", initial=1.0, sample_time=0.01), name="exhaust_delay")
    # The sensor lag acts on the deviation from lambda = 1, so it starts settled at lambda = 1.
    dev = d.add(Bias(bias=-1.0), name="deviation")
    sensor_lag = d.add(TransferFunction(numerator=[1.0], denominator="[tau_sensor, 1]"), name="sensor_lag")
    sensor = d.add(Bias(bias=1.0), name="lambda_sensor")
    d.connect(load, air.in_port(0))
    d.connect(tip_in, air.in_port(1))
    d.connect(tip_out, air.in_port(2))
    d.connect(air, true_air.in_port(0))
    d.connect(leak, true_air.in_port(1))
    d.connect(air, ecu.in_port(0))  # the MAF sensor measures the air before the leak
    d.connect(sensor, ecu.in_port(1))
    d.chain(ecu, inj, flow)
    d.connect(true_air, ratio.in_port(0))
    d.connect(flow, ratio.in_port(1))
    d.chain(ratio, lam, sample, delay, dev, sensor_lag, sensor)
    d.connect(lam, d.add(Scope(), name="lambda"))
    d.connect(ecu.out_port(1), d.add(Scope(), name="STFT"))
    d.connect(ecu.out_port(2), d.add(Scope(), name="LTFT"))
    _place(
        d,
        {
            "part_load": (0, 0),
            "tip_in": (0, 90),
            "tip_out": (0, 180),
            "air_charge_mg": (160, 90),
            "air_leak": (160, 220),
            "actual_air_mg": (320, 150),
            "ECU": (620, 380),
            "injector_open_ms": (920, 380),
            "fuel_mg": (1080, 380),
            "air_fuel_ratio": (1240, 200),
            "lambda_cyl": (1400, 200),
            "lambda": (1560, 120),
            # The exhaust path runs back from the cylinders to the ECU, right to left (flipped blocks).
            "exhaust_sample": (1400, 600),
            "exhaust_delay": (1240, 600),
            "deviation": (1080, 600),
            "sensor_lag": (920, 600),
            "lambda_sensor": (760, 600),
            "STFT": (920, 470),
            "LTFT": (1080, 470),
        },
    )
    for name in ("exhaust_sample", "exhaust_delay", "deviation", "sensor_lag", "lambda_sensor"):
        d.block(name).meta["flipped"] = True
    d.tests = [
        TestCase(
            "vacuum leak learned by the LTFT",
            "6 % unmetered air at 12 s: after 25 s the LTFT has learned it and the STFT is back near 0",
            checks=[
                Check("bounds", "lambda_cyl", {"lower": 0.97, "upper": 1.03, "t_from": 15.0}),
                Check("final_value", "ECU/ltft_pct", {"value": 6.0, "tolerance": 0.6}),
                Check("final_value", "ECU/stft_pct", {"value": 0.0, "tolerance": 1.0}),
            ],
        ),
        TestCase(
            "clogged injector",
            "Injectors deliver 5 % less fuel: the LTFT learns about +5 %",
            parameters={"leak": 0.0, "injector_error": -0.05},
            checks=[Check("final_value", "ECU/ltft_pct", {"value": 5.3, "tolerance": 0.6})],
        ),
        TestCase(
            "tip-in and tip-out stay close to lambda 1",
            "The air charge changes by 60 %; the base fuel follows the measured air, so lambda stays at 1 "
            "(this simple plant has no fuel film on the intake walls, which causes lean spikes in real engines)",
            checks=[Check("bounds", "lambda_cyl", {"lower": 0.99, "upper": 1.01, "t_to": 11.9})],
        ),
    ]
    return d


def main() -> SimResult:
    d = build()
    save(d, HERE / "lambda_control.nervus")
    res = simulate(d)
    t = res.t
    for when in (11.9, 13.0, 20.0, 40.0):
        k = int(np.argmin(abs(t - when)))
        print(
            f"t = {when:4.1f} s: lambda {res['lambda_cyl'][k]:.3f}, STFT {res['ECU/stft_pct'][k]:+5.1f} %, "
            f"LTFT {res['ECU/ltft_pct'][k]:+5.1f} %"
        )
    from nervus.testing import run_tests

    for r in run_tests(d):
        print(r.summary())
    return res


if __name__ == "__main__":
    main()
