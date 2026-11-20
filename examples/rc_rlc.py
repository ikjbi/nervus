"""RC and RLC circuits: the first lab of every electronics course, simulated and analysed.

Two circuits, each driven by a controlled voltage source from an In block (5 V, or 1 V for the RLC) and measured
with a voltage sensor to an Out block. The capacitor starts empty, so running the model shows the **step
response**; **Analysis ▸ Linear Analysis** from the In to the Out block shows the **frequency response**.

* ``rc_filter.nervus``: R = 1 kΩ, C = 1 µF: a first-order low-pass, τ = RC = 1 ms, cut-off 1/(2πRC) = 159 Hz.
* ``rlc_circuit.nervus``: R = 10 Ω, L = 10 mH, C = 10 µF in series, the output across C: a second-order system with
  the resonance 1/(2π√(LC)) = 503 Hz and the damping ratio ζ = (R/2)·√(C/L) = 0.16.

Run with ``uv run python examples/rc_rlc.py``.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Capacitor,
    ElectricalReference,
    Inductor,
    Inport,
    Outport,
    Resistor,
    Scope,
    VoltageSensor,
    VoltageSource,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent


def _circuit(name: str, v_in: float, t_final: float, parts: list[tuple[str, object]]) -> tuple[Diagram, object]:
    """Source → the series ``parts`` → ground; returns the diagram and the last part (the capacitor)."""
    d = Diagram(name)
    d.settings.t_final = t_final
    d.settings.max_step = t_final / 500
    u = d.add(Inport(port=1, value=v_in), name="v_in")
    src = d.add(VoltageSource(controlled=True), name="source")
    gnd = d.add(ElectricalReference(), name="gnd")
    d.connect(u, src)
    d.link((src, "n"), (gnd, "p"))
    prev = (src, "p")
    blocks = []
    for pname, block in parts:
        b = d.add(block, name=pname)  # type: ignore[arg-type]
        d.link(prev, (b, "p"))
        prev = (b, "n")
        blocks.append(b)
    d.link(prev, (gnd, "p"))
    cap = blocks[-1]
    sense = d.add(VoltageSensor(), name="v_cap_sensor")
    d.link((sense, "p"), (cap, "p"))
    d.link((sense, "n"), (gnd, "p"))
    d.connect(sense, d.add(Outport(port=1), name="v_out"))
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(u, (scope, 0))
    d.connect(sense, (scope, 1))
    for k, b in enumerate(d.blocks):
        b.meta["position"] = [float(140 * (k % 5)), float(110 * (k // 5))]
    return d, cap


def build_rc() -> Diagram:
    d, _cap = _circuit("rc_filter", 5.0, 0.008,
                       [("R", Resistor(R="R")), ("C", Capacitor(C="C"))])  # fmt: skip
    d.workspace.add(Variable("R", 1e3, "Resistor", "Ω"))
    d.workspace.add(Variable("C", 1e-6, "Capacitor", "F"))
    d.tests = [
        TestCase(
            "time constant",
            "After one time constant (RC = 1 ms) the capacitor is at 63 % of 5 V; after 5 RC at 99 %",
            stop_time=0.008,
            checks=[
                Check("bounds", "v_out", {"lower": 3.14, "upper": 3.18, "t_from": 0.001, "t_to": 0.00101}),
                Check("bounds", "v_out", {"lower": 4.96, "t_from": 0.005}),
            ],
        )
    ]
    return d


def build_rlc() -> Diagram:
    d, _cap = _circuit("rlc_circuit", 1.0, 0.012,
                       [("R", Resistor(R="R")), ("L", Inductor(L="L")), ("C", Capacitor(C="C"))])  # fmt: skip
    d.workspace.add(Variable("R", 10.0, "Series resistor (critical damping at 2√(L/C) = 63 Ω)", "Ω"))
    d.workspace.add(Variable("L", 10e-3, "Inductor", "H"))
    d.workspace.add(Variable("C", 10e-6, "Capacitor", "F"))
    d.tests = [
        TestCase(
            "underdamped step",
            "ζ = 0.16: the capacitor voltage overshoots by about 60 % and rings at the resonance (503 Hz)",
            stop_time=0.012,
            checks=[Check("max", "v_out", {"value": 1.62}), Check("min", "v_out", {"value": 0.0})],
        )
    ]
    return d


def resonance(l_h: float, c_f: float, r: float) -> tuple[float, float]:
    """Resonance frequency [Hz] and damping ratio of the series RLC (output across C)."""
    return 1 / (2 * math.pi * math.sqrt(l_h * c_f)), r / 2 * math.sqrt(c_f / l_h)


def bode_point(d: Diagram, f_hz: float) -> tuple[float, float]:
    """Gain [dB] and phase [°] from the In to the Out block at ``f_hz`` (from the linearized model)."""
    from nervus.analysis import linearize

    num, den = linearize(d).transfer_function()
    s = 2j * math.pi * f_hz
    g = np.polyval(num, s) / np.polyval(den, s)
    return float(20 * np.log10(abs(g))), float(np.degrees(np.angle(g)))


def main() -> dict[str, SimResult]:
    from nervus.testing import run_tests

    rc, rlc = build_rc(), build_rlc()
    save(rc, HERE / "rc_filter.nervus")
    save(rlc, HERE / "rlc_circuit.nervus")
    for d in (rc, rlc):
        for r in run_tests(d):
            print(r.summary())
    gain, phase = bode_point(rc, 1 / (2 * math.pi * 1e-3))
    print(f"RC at 159 Hz: {gain:.2f} dB, {phase:.1f}°")
    f0, zeta = resonance(10e-3, 10e-6, 10.0)
    print(f"RLC: f0 = {f0:.0f} Hz, zeta = {zeta:.3f}, peak at f0: {bode_point(rlc, f0)[0]:.1f} dB")
    return {"rc": simulate(rc), "rlc": simulate(rlc)}


if __name__ == "__main__":
    main()
