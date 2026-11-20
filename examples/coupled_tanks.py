"""Level control of two coupled water tanks: the nonlinear process-control experiment of lab courses.

A pump fills the upper tank; water runs through an orifice into the lower tank and out through a second orifice
(Torricelli: the outflow grows with the square root of the level). The controller holds the level of the lower
tank with a PI controller that drives the pump voltage (0-22 V). The dimensions are those of a common lab rig:

    A dh1/dt = Kp·V - a1·sqrt(2 g h1)        tank cross-section A = 15.5 cm², tanks 30 cm high
    A dh2/dt = a1·sqrt(2 g h1) - a2·sqrt(2 g h2)   orifices a1 = 0.317 cm², a2 = 0.178 cm²; pump 3.3 cm³/s per V

The levels start in equilibrium at 15 cm (lower tank). The reference steps to 17 cm, 13 cm, and then to 5 cm,
where the same controller behaves differently because the process is nonlinear.

Run with ``uv run python examples/coupled_tanks.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    PID,
    Constant,
    FromWorkspace,
    Gain,
    Integrator,
    MathFunction,
    Outport,
    Scope,
    Sum,
    Switch,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent

G = 981.0  # cm/s²
CONSTANTS = {
    "A_tank": (15.52, "cm²", "Tank cross-section (both tanks)"),
    "a1": (0.3167, "cm²", "Outlet orifice of the upper tank"),
    "a2": (0.1781, "cm²", "Outlet orifice of the lower tank"),
    "K_pump": (3.3, "cm³/(s·V)", "Pump flow per volt"),
    "V_max": (22.0, "V", "Pump amplifier limit"),
    "h_max": (30.0, "cm", "Tank height (overflow)"),
    "Kc": (0.47, "V/cm", "PI controller: proportional gain"),
    "Ti": (15.2, "s", "PI controller: integral time (= the lower tank's time constant at 15 cm)"),
    "closed_loop": (1.0, "-", "1: PI level control, 0: constant pump voltage V_open"),
    "V_open": (9.25, "V", "Pump voltage in open loop (equilibrium at 15 cm)"),
}
REFERENCE = [(0, 15.0), (50, 15.0), (50.01, 17.0), (150, 17.0), (150.01, 13.0), (250, 13.0), (250.01, 5.0),
             (400, 5.0)]  # fmt: skip


def equilibrium(h2: float) -> tuple[float, float]:
    """Pump voltage and upper level for the lower tank at ``h2`` cm in steady state."""
    q = CONSTANTS["a2"][0] * math.sqrt(2 * G * h2)
    h1 = (q / CONSTANTS["a1"][0]) ** 2 / (2 * G)
    return q / CONSTANTS["K_pump"][0], h1


def build() -> Diagram:
    d = Diagram("coupled_tanks")
    d.settings.t_final = 400.0
    d.settings.max_step = 0.5
    for name, (value, unit, desc) in CONSTANTS.items():
        d.workspace.add(Variable(name, value, desc, unit))
    v0, h1_0 = equilibrium(15.0)
    t, r = zip(*REFERENCE, strict=True)
    ref = d.add(FromWorkspace(time=list(t), data=[[x] for x in r]), name="level_ref")
    err = d.add(Sum(signs="+-"), name="error")
    pi = d.add(PID(P="Kc", I="Kc / Ti", upper="V_max", lower=0.0, anti_windup="clamping", initial_integrator=v0),
               name="pi")  # fmt: skip
    v_open = d.add(Constant(value="V_open"), name="open_loop_voltage")
    mode = d.add(Constant(value="closed_loop"), name="mode")
    sel = d.add(Switch(threshold=0.5), name="pump_voltage")
    inflow = d.add(Gain(gain="K_pump"), name="pump_flow")
    # Upper tank
    net1 = d.add(Sum(signs="+-"), name="net_flow_1")
    dh1 = d.add(Gain(gain="1 / A_tank"), name="dh1")
    h1 = d.add(Integrator(initial=h1_0, lower=0.0, upper="h_max"), name="h1")
    sq1 = d.add(MathFunction(function="sqrt"), name="sqrt_h1")
    out1 = d.add(Gain(gain=f"a1 * {math.sqrt(2 * G):.6f}"), name="flow_1_to_2")
    # Lower tank
    net2 = d.add(Sum(signs="+-"), name="net_flow_2")
    dh2 = d.add(Gain(gain="1 / A_tank"), name="dh2")
    h2 = d.add(Integrator(initial=15.0, lower=0.0, upper="h_max"), name="h2")
    sq2 = d.add(MathFunction(function="sqrt"), name="sqrt_h2")
    out2 = d.add(Gain(gain=f"a2 * {math.sqrt(2 * G):.6f}"), name="outflow")
    d.connect(ref, (err, 0))
    d.connect(h2, (err, 1))
    d.chain(err, pi)
    d.connect(pi, (sel, 0))
    d.connect(mode, (sel, 1))
    d.connect(v_open, (sel, 2))
    d.chain(sel, inflow)
    d.connect(inflow, (net1, 0))
    d.connect(out1, (net1, 1))
    d.chain(net1, dh1, h1, sq1, out1)
    d.connect(out1, (net2, 0))
    d.connect(out2, (net2, 1))
    d.chain(net2, dh2, h2, sq2, out2)
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(ref, (scope, 0))
    d.connect(h2, (scope, 1))
    d.connect(h1, (scope, 2))
    for k, (src, name) in enumerate(((h2, "level_2"), (h1, "level_1"), (sel, "voltage"))):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    positions = {"level_ref": (0, 0), "error": (130, 10), "pi": (250, 10), "open_loop_voltage": (250, 110),
                 "mode": (250, 200), "pump_voltage": (390, 60), "pump_flow": (520, 60), "net_flow_1": (650, 70),
                 "dh1": (770, 70), "h1": (890, 70), "sqrt_h1": (1010, 70), "flow_1_to_2": (1130, 70),
                 "net_flow_2": (650, 230), "dh2": (770, 230), "h2": (890, 230), "sqrt_h2": (1010, 230),
                 "outflow": (1130, 230), "scope": (1130, -80), "level_2": (1010, 330), "level_1": (1010, -20),
                 "voltage": (520, -60)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.block("flow_1_to_2").meta["flipped"] = True
    d.block("outflow").meta["flipped"] = True
    d.tests = [
        TestCase(
            "follows the steps around 15 cm",
            "After the step to 17 cm the level is within 0.2 cm after 60 s, and overshoots by less than 1 cm",
            stop_time=150.0,
            checks=[
                Check("bounds", "level_2", {"lower": 16.8, "upper": 17.2, "t_from": 110.0}),
                Check("bounds", "level_2", {"upper": 18.0}),
            ],
        ),
        TestCase(
            "the upper tank never overflows",
            "The pump limit and the anti-windup keep the upper tank below 30 cm",
            stop_time=400.0,
            checks=[Check("bounds", "level_1", {"upper": 29.9})],
        ),
    ]
    return d


def settling(res: SimResult, t0: float, t1: float, target: float, band: float = 0.02) -> float:
    """Time after ``t0`` until the lower level stays within ``band`` (relative to the step) of ``target``."""
    m = (res.t >= t0) & (res.t <= t1)
    t, h = res.t[m], np.ravel(res["level_2"])[m]
    step = abs(target - h[0]) or 1.0
    out = np.where(np.abs(h - target) > band * step)[0]
    return float(t[out[-1]] - t0) if len(out) else 0.0


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "coupled_tanks.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    print(f"equilibrium at 15 cm: {equilibrium(15.0)[0]:.2f} V, upper tank {equilibrium(15.0)[1]:.2f} cm")
    print(f"settling (2 %): 15→17 cm {settling(res, 50, 150, 17):.0f} s, 17→13 cm {settling(res, 150, 250, 13):.0f} s, "
          f"13→5 cm {settling(res, 250, 400, 5):.0f} s")  # fmt: skip
    return res


if __name__ == "__main__":
    main()
