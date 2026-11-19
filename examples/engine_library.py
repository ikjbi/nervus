"""Reusable engine components in a library, used twice in one model.

``library/engine_parts.nervlib`` holds two masked components, built from the same equations as the idle
speed control example:

* **mean_value_engine**: throttle body, intake manifold, cylinders, torque and crankshaft of a four-stroke
  petrol engine. Inputs: throttle angle [°] and load torque [N·m]. Outputs: engine speed [rpm] and intake
  manifold pressure [Pa]. Mask parameters: displacement, manifold volume, inertia, volumetric and thermal
  efficiency, throttle area.
* **throttle_actuator**: the electronic throttle as a first-order lag with time constant ``tau``.

``engine_comparison.nervus`` links both components twice to compare a 1.6 l and a 2.0 l engine with the same
throttle steps. Change a component in the library and both engines (and every other model that uses it)
get the change the next time the model is opened.

Run with ``uv run python examples/engine_library.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Gain,
    Inport,
    Integrator,
    Outport,
    PythonFunction,
    Scope,
    Step,
    Subsystem,
    Sum,
    TransferFunction,
)
from nervus.core import Check, TestCase, Variable
from nervus.library import instantiate, save_to_library

HERE = Path(__file__).parent
LIBRARY = HERE / "library" / "engine_parts.nervlib"
RPM_PER_RAD_S = 60 / (2 * np.pi)

THROTTLE_FLOW = '''def f(t, alpha_deg, p_im):
    """Air mass flow through the throttle [kg/s]. p = [max throttle area m^2]"""
    p_amb, T, R, gamma, cd = 101325.0, 293.0, 287.0, 1.4, 0.8
    area = p[0] * (1 - math.cos(math.radians(max(alpha_deg, 0.0)))) + 4e-6
    pr = min(max(p_im / p_amb, 0.0), 1.0)
    if pr < 0.528:  # choked flow
        psi = 0.6847
    else:
        psi = math.sqrt(2 * gamma / (gamma - 1) * (pr ** (2 / gamma) - pr ** ((gamma + 1) / gamma)))
    return cd * area * p_amb / math.sqrt(R * T) * psi
'''

CYLINDER_FLOW = '''def f(t, p_im, omega):
    """Air mass flow into the cylinders [kg/s]. p = [eta_vol, displacement m^3]"""
    R, T = 287.0, 293.0
    return p[0] * p_im * p[1] * max(omega, 0.0) / (4 * math.pi * R * T)
'''

ENGINE_TORQUE = '''def f(t, m_cyl, omega, load):
    """Net crankshaft torque [N·m]. p = [eta_th, displacement m^3]"""
    q_lhv, afr = 44e6, 14.7
    omega = max(omega, 10.0)
    combustion = p[0] * q_lhv * (m_cyl / afr) / omega
    friction = (10.0 + 0.02 * omega) * p[1] / 1.6e-3  # friction grows with engine size
    return combustion - friction - load
'''


def _place(positions: dict[tuple[int, int], object]) -> None:
    for (x, y), block in positions.items():
        block.meta["position"] = [float(x), float(y)]  # type: ignore[attr-defined]


def mean_value_engine() -> Subsystem:
    d = Diagram("mean_value_engine")
    alpha = d.add(Inport(port=1), name="throttle_deg")
    load = d.add(Inport(port=2), name="load_torque")
    flow = d.add(PythonFunction(code=THROTTLE_FLOW, num_inputs=2, parameters="[throttle_area]"), name="throttle_flow")
    cyl = d.add(
        PythonFunction(code=CYLINDER_FLOW, num_inputs=2, parameters="[eta_vol, displacement]"), name="cylinder_flow"
    )
    net = d.add(Sum(signs="+-"), name="manifold_net_flow")
    k_im = d.add(Gain(gain="287 * 293 / V_im"), name="R_T_over_V")
    p_im = d.add(Integrator(initial=30000.0, lower=1000.0, upper=101325.0), name="p_intake")
    torque = d.add(
        PythonFunction(code=ENGINE_TORQUE, num_inputs=3, parameters="[eta_th, displacement]"), name="net_torque"
    )
    inv_j = d.add(Gain(gain="1 / J"), name="1/J")
    omega = d.add(Integrator(initial=800.0 / RPM_PER_RAD_S, lower=0.0), name="omega")
    rpm = d.add(Gain(gain=RPM_PER_RAD_S), name="to_rpm")
    rpm_out = d.add(Outport(port=1), name="rpm")
    p_out = d.add(Outport(port=2), name="p_im")
    d.connect(alpha, flow.in_port(0))
    d.connect(p_im, flow.in_port(1))
    d.connect(p_im, cyl.in_port(0))
    d.connect(omega, cyl.in_port(1))
    d.connect(flow, net.in_port(0))
    d.connect(cyl, net.in_port(1))
    d.chain(net, k_im, p_im)
    d.connect(cyl, torque.in_port(0))
    d.connect(omega, torque.in_port(1))
    d.connect(load, torque.in_port(2))
    d.chain(torque, inv_j, omega, rpm, rpm_out)
    d.connect(p_im, p_out)
    # Air path on top, torque path below.
    _place(
        {
            throttle_deg_pos: blk
            for throttle_deg_pos, blk in (
                ((0, 0), alpha),
                ((150, 0), flow),
                ((300, 0), net),
                ((450, 0), k_im),
                ((600, 0), p_im),
                ((900, 0), p_out),
                ((450, 150), cyl),
                ((0, 300), load),
                ((600, 300), torque),
                ((750, 300), inv_j),
                ((900, 300), omega),
                ((1050, 300), rpm),
                ((1200, 300), rpm_out),
            )
        }
    )
    sub = Subsystem("mean_value_engine", system=d)
    sub.mask.add(Variable("displacement", 1.6e-3, "Swept volume of all cylinders", "m³"))
    sub.mask.add(Variable("V_im", 2.0e-3, "Intake manifold volume", "m³"))
    sub.mask.add(Variable("J", 0.15, "Crankshaft and flywheel inertia", "kg·m²"))
    sub.mask.add(Variable("eta_vol", 0.85, "Volumetric efficiency", "-"))
    sub.mask.add(Variable("eta_th", 0.30, "Thermal efficiency", "-"))
    sub.mask.add(Variable("throttle_area", 2.8e-3, "Throttle plate area when fully open", "m²"))
    sub.mask_icon = "Mean-value\\nengine"
    sub.mask_description = "Four-stroke petrol engine (mean-value model): throttle [°], load [N·m] → rpm, p_im [Pa]"
    return sub


def throttle_actuator() -> Subsystem:
    d = Diagram("throttle_actuator")
    u = d.add(Inport(port=1), name="command_deg")
    lag = d.add(TransferFunction(numerator=[1.0], denominator="[tau, 1]"), name="lag")
    d.chain(u, lag, d.add(Outport(port=1), name="angle_deg"))
    _place({(0, 0): u, (150, 0): lag, (300, 0): d.block("angle_deg")})
    sub = Subsystem("throttle_actuator", system=d)
    sub.mask.add(Variable("tau", 0.03, "Time constant of the throttle motor and plate", "s"))
    sub.mask_icon = "Throttle\\nactuator"
    sub.mask_description = "Electronic throttle as a first-order lag"
    return sub


def build_library() -> Path:
    LIBRARY.parent.mkdir(exist_ok=True)
    if LIBRARY.exists():
        LIBRARY.unlink()
    save_to_library(mean_value_engine(), LIBRARY)
    return save_to_library(throttle_actuator(), LIBRARY)


def build() -> Diagram:
    """Two engines from the same library component, with the same throttle steps."""
    d = Diagram("engine_comparison")
    d.settings.t_final = 8.0
    d.settings.max_step = 0.01
    d.source_path = str(HERE / "engine_comparison.nervus")  # library paths are stored relative to this
    d.workspace.add(Variable("alpha_step", 6.0, "Throttle angle after the step", "°"))
    throttle = d.add(Step(time=2.0, initial=3.0, final="alpha_step"), name="throttle_cmd")
    load = d.add(Step(time=5.0, initial=0.0, final=15.0), name="load")
    scope = d.add(Scope(num_inputs=2), name="rpm_scope")
    rel = LIBRARY.relative_to(HERE)
    for k, (name, displacement, inertia) in enumerate((("engine_1_6l", 1.6e-3, 0.15), ("engine_2_0l", 2.0e-3, 0.2))):
        act = d.add(instantiate(rel, "throttle_actuator", base_dir=HERE), name=f"actuator_{name[7:]}")
        eng = d.add(instantiate(rel, "mean_value_engine", base_dir=HERE), name=name)
        eng.mask["displacement"] = displacement
        eng.mask["J"] = inertia
        d.chain(throttle, act)
        d.connect(act, eng.in_port(0))
        d.connect(load, eng.in_port(1))
        d.connect(eng.out_port(0), scope.in_port(k))
        d.connect(eng.out_port(1), d.add(Scope(), name=f"p_im_{name[7:]}"))
    for k, name in enumerate(("1_6l", "2_0l")):
        y = 260 * k
        _place(
            {
                (220, y): d.block(f"actuator_{name}"),
                (640, y): d.block(f"engine_{name}"),
                (1020, y + 120): d.block(f"p_im_{name}"),
            }
        )
    _place({(0, 0): throttle, (460, 130): load, (1020, 40): scope})
    d.tests = [
        TestCase(
            "both engines settle after the throttle step",
            checks=[
                Check("bounds", "engine_1_6l/to_rpm", {"lower": 500.0, "upper": 4000.0, "t_from": 1.0}),
                Check("bounds", "engine_2_0l/to_rpm", {"lower": 500.0, "upper": 4000.0, "t_from": 1.0}),
            ],
        ),
    ]
    return d


def main() -> SimResult:
    build_library()
    d = build()
    save(d, HERE / "engine_comparison.nervus")
    res = simulate(d)
    t = res.t
    for name in ("engine_1_6l", "engine_2_0l"):
        rpm = res[f"{name}/to_rpm"]
        print(
            f"{name}: {np.interp(1.9, t, rpm):.0f} rpm at 3°, {np.interp(4.9, t, rpm):.0f} rpm at "
            f"{d.workspace['alpha_step']:g}°, {rpm[-1]:.0f} rpm with 15 N·m load"
        )
    return res


if __name__ == "__main__":
    main()
