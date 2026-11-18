"""The throttle controller as an ECU software component, with generated C code.

Same plant and controller as ``throttle_pi.py``, but everything that runs on the ECU (sampling the throttle
position sensor, the control error and the discrete PI controller) is inside a subsystem called ``ECU``. Its
In/Out blocks are the software interface:

* input ``target_deg``: requested throttle angle from the pedal map [°]
* input ``tps_deg``: measured throttle position [°]
* output ``duty_pct``: H-bridge duty cycle [%]

Running this script simulates the whole system, generates C code for the ECU subsystem into
``examples/generated/ECU/``, and (if a C compiler is installed) runs a back-to-back test of the generated code
against the model.

Run with ``uv run python examples/throttle_ecu.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    DiscretePID,
    FromWorkspace,
    Gain,
    Inport,
    Integrator,
    Outport,
    Scope,
    Subsystem,
    Sum,
    ZeroOrderHold,
)
from nervus.codegen import GeneratedCode, generate_c
from nervus.codegen.sil import back_to_back, find_compiler
from nervus.core import Check, TestCase, Variable
from nervus.core.layout import auto_layout

HERE = Path(__file__).parent


def build_ecu() -> Subsystem:
    ecu = Diagram("ECU")
    target = ecu.add(Inport(port=1), name="target_deg")
    tps = ecu.add(Inport(port=2), name="tps_deg")
    sample = ecu.add(ZeroOrderHold(sample_time="Ts"), name="tps_sample")
    err = ecu.add(Sum(signs="+-"), name="error")
    pi = ecu.add(
        DiscretePID(P="Kp", I="Ki", upper=100.0, lower=0.0, anti_windup="clamping", sample_time="Ts"),
        name="throttle_pi",
    )
    duty = ecu.add(Outport(port=1), name="duty_pct")
    ecu.chain(tps, sample)
    ecu.connect(target, err.in_port(0))
    ecu.connect(sample, err.in_port(1))
    ecu.chain(err, pi, duty)
    auto_layout(ecu)
    return Subsystem(system=ecu)


def build() -> Diagram:
    d = Diagram("throttle_ecu")
    d.settings.t_final = 2.0
    ws = d.workspace
    ws.add(Variable("Kp", 1.5, "Proportional gain", "%/°", min=0.0))
    ws.add(Variable("Ki", 40.0, "Integral gain", "%/(°·s)", min=0.0))
    ws.add(Variable("Ts", 0.01, "ECU task period", "s", min=0.001))
    ws.add(Variable("tau", 0.05, "Actuator time constant", "s", min=0.0))
    ws.add(Variable("k_act", 0.9, "Actuator gain", "°/%"))

    target = d.add(
        FromWorkspace(time=[0.0, 0.2, 1.2], data=[5.0, 60.0, 20.0], interpolation="hold"), name="pedal_target"
    )
    ecu = d.add(build_ecu(), name="ECU")
    k = d.add(Gain(gain="k_act"), name="deg_per_pct")
    lag = d.add(Sum(signs="+-"), name="lag")
    inv_tau = d.add(Gain(gain="1/tau"), name="1/tau")
    angle = d.add(Integrator(initial=5.0, lower=0.0, upper=90.0), name="plate_angle")
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(target, ecu.in_port(0))
    d.connect(angle, ecu.in_port(1))
    d.chain(ecu, k)
    d.connect(k, lag.in_port(0))
    d.connect(angle, lag.in_port(1))
    d.chain(lag, inv_tau, angle)
    d.connect(target, scope.in_port(0))
    d.connect(angle, scope.in_port(1))
    d.connect(ecu, scope.in_port(2))
    auto_layout(d, width_of=lambda b: 190.0 if isinstance(b, Subsystem) else 70.0)
    d.tests = test_cases()
    return d


def test_cases() -> list[TestCase]:
    """Requirements for the throttle controller, as test cases stored with the model."""
    return [
        TestCase(
            "tip-in, baseline calibration",
            "Reaches 59° within 150 ms of the step to 60°, with at most 5° overshoot",
            checks=[
                Check("reaches", "plate_angle", {"value": 59.0, "before": 0.35}),
                Check("max", "plate_angle", {"value": 65.0}),
                Check("final_value", "plate_angle", {"value": 20.0, "tolerance": 0.5}),
            ],
        ),
        TestCase(
            "tip-in, tight calibration",
            "The higher-gain calibration overshoots less than 1°",
            parameter_set="throttle_tight.nervcal",
            checks=[Check("max", "plate_angle", {"value": 61.0})],
        ),
        TestCase(
            "duty cycle within actuator limits",
            checks=[Check("bounds", "ECU/throttle_pi", {"lower": 0.0, "upper": 100.0})],
        ),
    ]


def generate(d: Diagram, folder: Path = HERE / "generated" / "ECU") -> GeneratedCode:
    code = generate_c(d.block("ECU"))
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in code.c_files.items():
        (folder / name).write_text(text, encoding="utf-8")
    (folder / "main_example.c").write_text(code.files["main_example.c"], encoding="utf-8")
    return code


def main() -> SimResult:
    d = build()
    save(d, HERE / "throttle_ecu.nervus")
    res = simulate(d)
    print(f"angle at t = 1.15 s: {float(np.interp(1.15, res.t, res['plate_angle'])):.2f}° (target 60°)")
    from nervus.testing import run_tests

    for result in run_tests(d, base_dir=HERE):
        print(result.summary())
    code = generate(d)
    print(f"generated {', '.join(code.c_files)}: call {code.name}_step() every {code.base_period:g} s")
    if find_compiler():
        k = np.arange(300)
        inputs = {
            "target_deg": np.where(k > 20, 60.0, 5.0),
            "tps_deg": 5 + 55 * (1 - np.exp(-np.maximum(k - 20, 0) / 8)),
        }
        print(back_to_back(d.block("ECU"), inputs, 300).summary())
    return res


if __name__ == "__main__":
    main()
