"""The injector driver: a low-side power stage on the ECU board, and why injection timing depends on it.

A port fuel injector (12 Ω, 10 mH, pull-in 0.6 A, drop-out 0.3 A, 3.5 g/s) is switched to ground by a transistor on
the ECU board (the **low-side switch**, 0.1 Ω when on); its other end is on the battery. The ECU commands a 3 ms
injection pulse. Two effects decide how much fuel is actually injected:

* **Opening delay**: the coil current rises with τ = L/R = 0.83 ms towards V_bat/R; the needle only lifts when it
  passes the pull-in current. With a lower battery voltage this takes longer, so ECUs add a battery-voltage dependent
  **dead time** to every pulse.
* **Closing delay**: when the transistor switches off, the coil keeps driving its current. With a **freewheeling
  diode** across the coil the current decays slowly (τ again) and the injector closes late; without it the voltage
  at the transistor rises until its avalanche **clamp** (60 V) conducts, and the current, and the injector, stop
  fast.

Set ``V_bat`` (9 to 15 V) and ``freewheel`` (1: freewheeling diode fitted, 0: clamp only).

Run with ``uv run python examples/injector_driver.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Constant,
    CurrentSensor,
    Diode,
    ElectricalReference,
    ElectricalSwitch,
    FromWorkspace,
    FuelInjector,
    Integrator,
    Outport,
    Scope,
    VariableResistor,
    VoltageSensor,
    VoltageSource,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
PULSE = (1e-3, 4e-3)  # the ECU's injection command: 3 ms


def build() -> Diagram:
    d = Diagram("injector_driver")
    d.settings.t_final = 8e-3
    d.settings.solver = "BDF"  # stiff: the coil against a switched-off transistor
    d.settings.max_step = 1e-5
    ws = d.workspace
    ws.add(Variable("V_bat", 14.0, "Battery voltage", "V"))
    ws.add(Variable("freewheel", 0.0, "1: freewheeling diode across the coil, 0: transistor clamp only", "-"))
    gnd = d.add(ElectricalReference(), name="gnd")
    bat = d.add(VoltageSource(V="V_bat"), name="battery")
    inj = d.add(FuelInjector(R=12.0, L=0.01, I_pull=0.6, I_drop=0.3), name="injector")
    i_coil = d.add(CurrentSensor(), name="coil_current")
    switch = d.add(ElectricalSwitch(R_on=0.1, G_off=1e-7), name="low_side_switch")
    clamp = d.add(Diode(Vf=0.7), name="clamp_diode")  # the transistor's avalanche clamp: conducts above 60 V
    clamp_v = d.add(VoltageSource(V=59.3), name="clamp_60V")
    diode = d.add(Diode(Vf=0.7), name="freewheel_diode")
    fitted = d.add(VariableResistor(R_min=1e-3), name="freewheel_fitted")
    drain = d.add(VoltageSensor(), name="v_drain")
    for a, b in (((bat, "n"), (gnd, "p")), ((bat, "p"), (inj, "p")), ((inj, "n"), (i_coil, "p")),
                 ((i_coil, "n"), (switch, "p")), ((switch, "n"), (gnd, "p")),
                 ((clamp, "p"), (switch, "p")), ((clamp, "n"), (clamp_v, "p")), ((clamp_v, "n"), (gnd, "p")),
                 ((diode, "p"), (switch, "p")), ((diode, "n"), (fitted, "p")), ((fitted, "n"), (bat, "p")),
                 ((drain, "p"), (switch, "p")), ((drain, "n"), (gnd, "p"))):  # fmt: skip
        d.link(a, b)
    cmd = d.add(FromWorkspace(time=[0, PULSE[0], PULSE[0] + 1e-9, PULSE[1], PULSE[1] + 1e-9, 1],
                              data=[[0], [0], [1], [1], [0], [0]], interpolation="hold"), name="injection_command")  # fmt: skip
    d.connect(cmd, switch)
    r_fit = d.add(Constant(value="0.01 + (1 - freewheel) * 1e6"), name="diode_fitted")
    d.connect(r_fit, fitted)
    fuel = d.add(Integrator(), name="fuel_mg")  # g/s integrated over seconds → g; shown in mg
    d.connect((inj, 1), fuel)
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(cmd, (scope, 0))
    d.connect(i_coil, (scope, 1))
    d.connect((inj, 0), (scope, 2))
    outs = ((cmd, "command"), (i_coil, "current"), ((inj, 0), "needle_lift"), (drain, "drain_voltage"),
            (fuel, "fuel_g"))  # fmt: skip
    for k, (src, name) in enumerate(outs):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    for k, b in enumerate(d.blocks):
        b.meta["position"] = [float(150 * (k % 6)), float(110 * (k // 6))]
    d.tests = [
        TestCase(
            "opening and closing delay at 14 V with the clamp",
            "The needle is open 1 ms after the command and closed 0.6 ms after its end",
            stop_time=8e-3,
            checks=[
                Check("bounds", "needle_lift", {"lower": 0.5, "t_from": 2.0e-3, "t_to": 4e-3}),
                Check("bounds", "needle_lift", {"upper": 0.5, "t_from": 4.6e-3}),
            ],
        ),
        TestCase(
            "the clamp limits the drain voltage",
            "When the transistor switches off, the drain voltage is clamped at about 60 V",
            stop_time=8e-3,
            checks=[Check("bounds", "drain_voltage", {"upper": 62.0})],
        ),
    ]
    return d


def timing(res: SimResult) -> dict[str, float]:
    """Opening and closing delay [ms] of the needle (lift crossing 0.5) and the injected fuel [mg]."""
    t, lift = res.t, np.ravel(res["needle_lift"])
    opened = t[np.argmax(lift > 0.5)]
    closing = t[(t > PULSE[1]) & (lift < 0.5)]
    closed = float(closing[0]) if closing.size else float("nan")
    return {"open_ms": 1000 * (opened - PULSE[0]), "close_ms": 1000 * (closed - PULSE[1]),
            "fuel_mg": 1000 * float(np.ravel(res["fuel_g"])[-1])}  # fmt: skip


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "injector_driver.nervus")
    for r in run_tests(d):
        print(r.summary())
    out = {}
    for v in (9.0, 12.0, 14.0):
        for fw in (0.0, 1.0):
            res = simulate(d, params={"V_bat": v, "freewheel": fw})
            out[f"{v:g}V_{'freewheel' if fw else 'clamp'}"] = res
            tm = timing(res)
            print(f"{v:4.0f} V, {'freewheel diode' if fw else 'clamp only    '}: opens after {tm['open_ms']:.2f} ms, "
                  f"closes {tm['close_ms']:.2f} ms after the end, {tm['fuel_mg']:.2f} mg "
                  f"(ideal 3 ms × 3.5 g/s = 10.5 mg)")  # fmt: skip
    return out


if __name__ == "__main__":
    main()
