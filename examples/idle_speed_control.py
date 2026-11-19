"""Idle speed control on a mean-value engine model.

The **plant** is a classic mean-value engine model (MVEM) of a 1.6 l four-stroke petrol engine:

* throttle body: air mass flow through the throttle plate (compressible, choked flow)
  ``m_th = Cd·A(α)·p_amb/√(R·T)·Ψ(p_im/p_amb)``
* intake manifold: pressure builds up from the difference between inflow and outflow
  ``dp_im/dt = R·T/V_im · (m_th − m_cyl)``
* cylinders: speed-density air flow ``m_cyl = η_vol·p_im·V_d·ω/(4π·R·T)``
* torque from the burnt fuel (stoichiometric, AFR 14.7) minus friction and the external load
  ``T = η_th·Q_LHV·(m_cyl/14.7)/ω − (T_f0 + c_f·ω) − T_load``
* crankshaft: ``J·dω/dt = T``

The **ECU** (a subsystem that can be generated as C code) samples the engine speed every 10 ms and adjusts
the throttle with a discrete PI controller plus a feed-forward base opening, to hold 800 rpm. At t = 5 s
the air-conditioning compressor switches on (+12 N·m of load). The manifold needs time to fill, so feedback
alone lets the speed dip; like production ECUs, the controller also gets the AC *request* 200 ms early and
opens the throttle by ``alpha_ac`` in advance (feed-forward). Set ``alpha_ac = 0`` to see the difference.

Run with ``uv run python examples/idle_speed_control.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Bias,
    DiscretePID,
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
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable
from nervus.core.layout import auto_layout

HERE = Path(__file__).parent
RPM_PER_RAD_S = 60 / (2 * np.pi)

THROTTLE_FLOW = '''def f(t, alpha_deg, p_im):
    """Air mass flow through the throttle [kg/s] (compressible orifice flow)."""
    p_amb, T, R, gamma, cd = 101325.0, 293.0, 287.0, 1.4, 0.8
    area = 2.8e-3 * (1 - math.cos(math.radians(max(alpha_deg, 0.0)))) + 4e-6   # plate + leakage [m^2]
    pr = min(max(p_im / p_amb, 0.0), 1.0)
    if pr < 0.528:  # choked flow
        psi = 0.6847
    else:
        psi = math.sqrt(2 * gamma / (gamma - 1) * (pr ** (2 / gamma) - pr ** ((gamma + 1) / gamma)))
    return cd * area * p_amb / math.sqrt(R * T) * psi
'''

CYLINDER_FLOW = '''def f(t, p_im, omega):
    """Air mass flow into the cylinders [kg/s] (speed-density, four-stroke)."""
    eta_vol, v_d, R, T = 0.85, 1.6e-3, 287.0, 293.0
    return eta_vol * p_im * v_d * max(omega, 0.0) / (4 * math.pi * R * T)
'''

ENGINE_TORQUE = '''def f(t, m_cyl, omega, load):
    """Net torque on the crankshaft [N·m]: combustion - friction - load."""
    eta_th, q_lhv, afr = 0.30, 44e6, 14.7
    omega = max(omega, 10.0)
    combustion = eta_th * q_lhv * (m_cyl / afr) / omega
    friction = 10.0 + 0.02 * omega
    return combustion - friction - load
'''


def build_ecu() -> Subsystem:
    ecu = Diagram("ECU")
    rpm = ecu.add(Inport(port=1), name="engine_rpm")
    sample = ecu.add(ZeroOrderHold(sample_time="Ts"), name="rpm_sample")
    err = ecu.add(Sum(signs="-+"), name="rpm_error")  # target - measured, target via Bias
    pid = ecu.add(
        DiscretePID(P="Kp_idle", I="Ki_idle", upper=15.0, lower=-2.0, anti_windup="clamping", sample_time="Ts"),
        name="idle_pi",
    )
    ff = ecu.add(Bias(bias="alpha_base"), name="base_opening")
    out = ecu.add(Outport(port=1), name="throttle_cmd_deg")
    target = ecu.add(Inport(port=2), name="target_rpm")
    ac = ecu.add(Inport(port=3), name="ac_request")
    ac_ff = ecu.add(Gain(gain="alpha_ac"), name="ac_feedforward")
    total = ecu.add(Sum(signs="++"), name="throttle_sum")
    ecu.chain(rpm, sample)
    ecu.connect(sample, err.in_port(0))
    ecu.connect(target, err.in_port(1))
    ecu.chain(err, pid, ff)
    ecu.connect(ff, total.in_port(0))
    ecu.chain(ac, ac_ff)
    ecu.connect(ac_ff, total.in_port(1))
    ecu.chain(total, out)
    return Subsystem(system=ecu)


def build() -> Diagram:
    d = Diagram("idle_speed_control")
    d.settings.t_final = 12.0
    d.settings.max_step = 0.01
    ws = d.workspace
    ws.add(Variable("Ts", 0.01, "ECU task period", "s"))
    ws.add(Variable("rpm_idle", 800.0, "Idle speed target", "rpm", min=500.0, max=1500.0))
    ws.add(Variable("Kp_idle", 0.04, "Idle PI proportional gain", "°/rpm", min=0.0))
    ws.add(Variable("Ki_idle", 0.03, "Idle PI integral gain", "°/(rpm·s)", min=0.0))
    ws.add(Variable("alpha_base", 2.0, "Feed-forward throttle opening at idle", "°", min=0.0, max=20.0))
    ws.add(Variable("J_engine", 0.15, "Crankshaft and flywheel inertia", "kg·m²"))
    ws.add(Variable("V_im", 2.0e-3, "Intake manifold volume", "m³"))
    ws.add(Variable("T_ac", 12.0, "Air-conditioning compressor load", "N·m"))
    ws.add(Variable("alpha_ac", 3.0, "Extra throttle opening when the AC is requested", "°", min=0.0, max=10.0))

    target = d.add(Inport(port=1, value="rpm_idle"), name="target_rpm")
    ecu = d.add(build_ecu(), name="ECU")
    actuator = d.add(TransferFunction(numerator=[1.0], denominator=[0.03, 1.0]), name="throttle_actuator")
    flow = d.add(PythonFunction(code=THROTTLE_FLOW, num_inputs=2), name="throttle_flow")
    cyl = d.add(PythonFunction(code=CYLINDER_FLOW, num_inputs=2), name="cylinder_flow")
    dm = d.add(Sum(signs="+-"), name="manifold_net_flow")
    k_im = d.add(Gain(gain="287 * 293 / V_im"), name="R_T_over_V")
    p_im = d.add(Integrator(initial=30000.0, lower=1000.0, upper=101325.0), name="p_intake")
    load = d.add(Step(time=5.0, initial=0.0, final="T_ac"), name="ac_load")
    ac_req = d.add(Step(time=4.8, initial=0.0, final=1.0), name="ac_request")  # request 200 ms before engaging
    torque = d.add(PythonFunction(code=ENGINE_TORQUE, num_inputs=3), name="net_torque")
    inv_j = d.add(Gain(gain="1 / J_engine"), name="1/J")
    omega = d.add(Integrator(initial=800.0 / RPM_PER_RAD_S, lower=0.0), name="omega")
    rpm = d.add(Gain(gain=RPM_PER_RAD_S), name="engine_rpm")
    scope = d.add(Scope(num_inputs=3), name="scope")

    d.connect(rpm, ecu.in_port(0))
    d.connect(target, ecu.in_port(1))
    d.connect(ac_req, ecu.in_port(2))
    d.chain(ecu, actuator)
    d.connect(actuator, flow.in_port(0))
    d.connect(p_im, flow.in_port(1))
    d.connect(p_im, cyl.in_port(0))
    d.connect(omega, cyl.in_port(1))
    d.connect(flow, dm.in_port(0))
    d.connect(cyl, dm.in_port(1))
    d.chain(dm, k_im, p_im)
    d.connect(cyl, torque.in_port(0))
    d.connect(omega, torque.in_port(1))
    d.connect(load, torque.in_port(2))
    d.chain(torque, inv_j, omega, rpm)
    d.connect(rpm, scope.in_port(0))
    d.connect(actuator, scope.in_port(1))
    d.connect(p_im, scope.in_port(2))
    auto_layout(d, width_of=lambda b: 190.0 if isinstance(b, Subsystem) else 90.0)
    auto_layout(d.block("ECU").system)
    d.tests = [
        TestCase(
            "AC compressor on at 5 s",
            "With feed-forward the speed dips less than 50 rpm, and is back within ±20 rpm after 4 s",
            checks=[
                Check("bounds", "engine_rpm", {"lower": 780.0, "upper": 820.0, "t_from": 3.0, "t_to": 4.8}),
                Check("min", "engine_rpm", {"value": 750.0}),
                Check("bounds", "engine_rpm", {"lower": 780.0, "upper": 820.0, "t_from": 9.0}),
            ],
        ),
        TestCase(
            "AC compressor on, no feed-forward",
            "Feedback alone: a much deeper dip (but the engine must not stall)",
            parameters={"alpha_ac": 0.0},
            checks=[Check("bounds", "engine_rpm", {"lower": 600.0, "upper": 900.0, "t_from": 4.5})],
        ),
        TestCase(
            "higher idle target",
            parameters={"rpm_idle": 1000.0},
            checks=[Check("final_value", "engine_rpm", {"value": 1000.0, "tolerance": 15.0})],
        ),
    ]
    return d


def main() -> SimResult:
    d = build()
    save(d, HERE / "idle_speed_control.nervus")
    res = simulate(d)
    rpm = res["engine_rpm"]
    t = res.t
    print(f"speed before the load: {np.interp(4.9, t, rpm):.0f} rpm")
    print(f"lowest speed after AC on: {rpm[t > 5].min():.0f} rpm")
    print(
        f"speed at 8 s: {np.interp(8.0, t, rpm):.0f} rpm; intake pressure {np.interp(8.0, t, res['p_intake']) / 1000:.1f} kPa"
    )
    from nervus.testing import run_tests

    for r in run_tests(d):
        print(r.summary())
    return res


if __name__ == "__main__":
    main()
