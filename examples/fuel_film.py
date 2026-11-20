"""Transient fuelling: wall wetting (x-tau), a switching lambda sensor, and fuel trims learned per load cell.

When the throttle opens, the air reaches the cylinders within a few combustions, but part of the injected fuel
lands on the intake port wall and evaporates only later: **wall wetting**. The classic model (Aquino, x-tau):

    dm_film/dt = X · q_inj - m_film / tau,       q_cyl = (1 - X) · q_inj + m_film / tau

So on a tip-in the engine runs lean for a moment (and rich on a tip-out). The ECU **compensates** with the same
model inverted: it estimates the film and injects what the cylinder needs plus what the wall will take.

* **Narrow-band (switching) sensor**: it only tells rich (about 0.8 V) or lean (about 0.1 V). The short-term
  trim jumps when the sensor switches and ramps in between: the classic *jump and ramp* controller, so lambda
  oscillates in a small limit cycle around 1, which the catalyst needs anyway.
* **Long-term trim per load cell**: the injectors deliver 8 % less fuel at low flow (an injector
  non-linearity). An **Adaptive Map** over the air flow learns the average short-term trim cell by cell, so the
  correction at idle does not disturb full load.

Run with ``uv run python examples/fuel_film.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    AdaptiveMap,
    CompareToConstant,
    Constant,
    DiscreteIntegrator,
    FromWorkspace,
    Gain,
    Inport,
    Integrator,
    Lookup1D,
    Outport,
    Product,
    PythonFunction,
    Scope,
    Subsystem,
    Sum,
    TransferFunction,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.01

LAMBDA = '''def f(t, air, fuel):
    """Lambda of the mixture in the cylinder (1 = stoichiometric, AFR 14.7)."""
    return air / (14.7 * max(fuel, 1e-6))
'''

SENSOR = '''def f(t, lam):
    """A narrow-band (zirconia) sensor: about 0.8 V rich, 0.1 V lean, switching steeply at lambda = 1."""
    return 0.45 + 0.37 * math.tanh((1.0 - lam) * 60.0)
'''

CONSTANTS = {
    "X_film": (0.3, "-", "Share of the injected fuel that lands on the wall"),
    "tau_film": (0.3, "s", "Evaporation time constant of the wall film"),
    "xtau_comp": (1.0, "-", "1: the ECU compensates the wall film, 0: off"),
    "stft_jump": (2.0, "%", "Short-term trim jump when the sensor switches"),
    "stft_ramp": (8.0, "%/s", "Short-term trim ramp between switches"),
    "ltft_rate": (0.6, "1/s", "Learning rate of the long-term trim"),
}


def build_ecu() -> Subsystem:
    """Base fuel from the air, x-tau compensation, jump-and-ramp STFT and the LTFT map (10 ms)."""
    s = Diagram("ecu")
    air = s.add(Inport(port=1), name="maf_g_s")
    o2 = s.add(Inport(port=2), name="o2_volts")
    base = s.add(Gain(gain=1 / 14.7), name="base_fuel")
    # Jump and ramp: +1 while lean (add fuel), -1 while rich.
    rich = s.add(CompareToConstant(operator=">", constant=0.45), name="rich")
    sign = s.add(Gain(gain=-2.0), name="minus_2_rich")
    direction = s.add(Sum(signs="++"), name="direction")  # 1 - 2·rich
    ramp = s.add(DiscreteIntegrator(gain="stft_ramp", upper=25.0, lower=-25.0, sample_time=TS), name="stft_ramp_part")
    jump = s.add(Gain(gain="stft_jump"), name="stft_jump_part")
    stft = s.add(Sum(signs="++"), name="stft_pct")
    ltft = s.add(AdaptiveMap(row_breakpoints=[4.0, 10.0, 25.0], column_breakpoints=[0.0, 1.0], rate="ltft_rate",
                             limit=25.0, sample_time=TS), name="ltft_pct")  # fmt: skip
    trims = s.add(Sum(signs="+++"), name="trim_pct")
    factor = s.add(Gain(gain=0.01), name="trim_fraction")
    corrected = s.add(Product(ops="**"), name="cylinder_fuel")  # base · (1 + trims)
    # Wall film compensation: q_inj = (q_cyl - comp·m_film/tau) / (1 - comp·X), with the film estimated.
    film = s.add(UnitDelay(initial=0.0, sample_time=TS), name="film_estimate")
    evap = s.add(Gain(gain="xtau_comp / tau_film"), name="evaporation")
    need = s.add(Sum(signs="+-"), name="minus_evaporation")
    inject = s.add(Gain(gain="1 / (1 - xtau_comp * X_film)"), name="injection")
    film_in = s.add(Gain(gain=f"X_film * {TS}"), name="to_film")
    film_out = s.add(Gain(gain=f"{TS} / tau_film"), name="from_film")
    film_next = s.add(Sum(signs="++-"), name="film_update")
    one = s.add(Constant(value=1.0), name="one")
    learn = s.add(Constant(value=1.0), name="learn")
    zero = s.add(Constant(value=0.0), name="y_cell")
    s.chain(air, base)
    s.chain(o2, rich, sign)
    s.connect(one, (direction, 0))
    s.connect(sign, (direction, 1))
    s.chain(direction, ramp)
    s.chain(direction, jump)
    s.connect(ramp, (stft, 0))
    s.connect(jump, (stft, 1))
    s.connect(air, (ltft, 0))
    s.connect(zero, (ltft, 1))
    s.connect(stft, (ltft, 2))
    s.connect(learn, (ltft, 3))
    s.connect(stft, (trims, 0))
    s.connect(ltft, (trims, 1))
    s.connect(s.add(Constant(value=100.0), name="hundred"), (trims, 2))  # factor = (100 + trims) / 100
    s.chain(trims, factor)
    s.connect(base, (corrected, 0))
    s.connect(factor, (corrected, 1))
    s.chain(film, evap)
    s.connect(corrected, (need, 0))
    s.connect(evap, (need, 1))
    s.chain(need, inject)
    s.chain(inject, film_in)
    s.chain(film, film_out)
    s.connect(film, (film_next, 0))
    s.connect(film_in, (film_next, 1))
    s.connect(film_out, (film_next, 2))
    s.connect(film_next, film)
    s.connect(inject, s.add(Outport(port=1), name="injection_g_s"))
    s.connect(stft, s.add(Outport(port=2), name="stft"))
    s.connect(ltft, s.add(Outport(port=3), name="ltft"))
    return Subsystem(system=s, sample_time=TS)


def build() -> Diagram:
    d = Diagram("fuel_film")
    d.settings.t_final = 40.0
    d.settings.solver = "rk4"
    d.settings.step = 0.005
    for name, (value, unit, desc) in CONSTANTS.items():
        d.workspace.add(Variable(name, value, desc, unit))
    # Air flow: idle, then repeated tip-ins and tip-outs, so both load cells are visited.
    pts = [(0, 5), (20, 5), (20.05, 20), (25, 20), (25.05, 5), (30, 5), (30.05, 20), (35, 20), (35.05, 5), (40, 5)]
    t, a = zip(*pts, strict=True)
    throttle_air = d.add(FromWorkspace(time=list(t), data=[[x] for x in a]), name="throttle_air")
    manifold = d.add(TransferFunction(numerator=[1.0], denominator=[0.05, 1.0]), name="manifold_filling")
    ecu = d.add(build_ecu(), name="ECU")
    maf = d.add(ZeroOrderHold(sample_time=TS), name="maf")
    injector_error = d.add(Lookup1D(breakpoints=[5.0, 20.0], table=[0.92, 1.0]), name="injector_error")
    delivered = d.add(Product(ops="**"), name="injected_fuel")
    film = d.add(Integrator(), name="wall_film_g")
    to_film = d.add(Gain(gain="X_film"), name="deposit")
    evap = d.add(Gain(gain="1 / tau_film"), name="evaporate")
    film_rate = d.add(Sum(signs="+-"), name="film_balance")
    direct = d.add(Gain(gain="1 - X_film"), name="direct_fuel")
    cyl_fuel = d.add(Sum(signs="++"), name="cylinder_fuel")
    lam = d.add(PythonFunction(code=LAMBDA, num_inputs=2), name="lambda_cyl")
    sensor_lag = d.add(TransferFunction(numerator=[1.0], denominator=[0.05, 1.0]), name="sensor_lag")
    o2 = d.add(PythonFunction(code=SENSOR, num_inputs=1), name="o2_sensor")
    o2_sample = d.add(ZeroOrderHold(sample_time=TS), name="o2_adc")
    d.chain(throttle_air, manifold, maf)
    d.connect(maf, (ecu, 0))
    d.connect(o2_sample, (ecu, 1))
    d.connect((ecu, 0), (delivered, 0))
    d.chain(manifold, injector_error)
    d.connect(injector_error, (delivered, 1))
    d.chain(delivered, to_film)
    d.connect(to_film, (film_rate, 0))
    d.connect(evap, (film_rate, 1))
    d.chain(film_rate, film, evap)
    d.chain(delivered, direct)
    d.connect(direct, (cyl_fuel, 0))
    d.connect(evap, (cyl_fuel, 1))
    d.connect(manifold, (lam, 0))
    d.connect(cyl_fuel, (lam, 1))
    d.chain(lam, sensor_lag, o2, o2_sample)
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(lam, (scope, 0))
    d.connect((ecu, 1), (scope, 1))
    d.connect((ecu, 2), (scope, 2))
    for k, (src, name) in enumerate(((lam, "lambda"), ((ecu, 1), "stft"), ((ecu, 2), "ltft"), (manifold, "air"))):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    _place(d)
    d.tests = [
        TestCase(
            "LTFT learns the idle injector error",
            "At idle the injectors deliver 8 % too little: the long-term trim learns about +8 %",
            stop_time=20.0,
            checks=[Check("bounds", "ltft", {"lower": 6.0, "upper": 10.0, "t_from": 18.0, "t_to": 20.0})],
        ),
        TestCase(
            "tip-in with film compensation",
            "With the x-tau compensation lambda stays within ±12 % on the tip-ins; the high-load cell learns ~0",
            stop_time=40.0,
            checks=[
                Check("bounds", "lambda", {"lower": 0.88, "upper": 1.12, "t_from": 19.0, "t_to": 40.0}),
                Check("bounds", "ltft", {"lower": -2.0, "upper": 2.0, "t_from": 24.5, "t_to": 25.0}),
            ],
        ),
    ]
    return d


def _place(d: Diagram) -> None:
    positions = {"throttle_air": (0, 0), "manifold_filling": (130, 0), "maf": (260, -60), "ECU": (380, -60),
                 "injector_error": (260, 80), "injected_fuel": (560, 0), "deposit": (680, 80),
                 "film_balance": (800, 80), "wall_film_g": (920, 80), "evaporate": (1040, 80),
                 "direct_fuel": (680, -40), "cylinder_fuel": (1160, 0), "lambda_cyl": (1280, 0),
                 "sensor_lag": (1280, 120), "o2_sensor": (1160, 200), "o2_adc": (1040, 200), "scope": (1400, -100),
                 "lambda": (1420, 0), "stft": (560, -140), "ltft": (560, -200), "air": (260, 160)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    for name in ("o2_sensor", "o2_adc"):
        d.block(name).meta["flipped"] = True


def lambda_excursion(res: SimResult, t0: float = 20.0, t1: float = 21.5) -> float:
    m = (res.t > t0) & (res.t < t1)
    return float(np.max(np.abs(np.ravel(res["lambda"])[m] - 1.0)))


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "fuel_film.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    off = simulate(d, params={"xtau_comp": 0.0})
    print(
        f"tip-in lambda excursion: {lambda_excursion(res):.1%} with compensation, {lambda_excursion(off):.1%} without"
    )
    return res


if __name__ == "__main__":
    main()
