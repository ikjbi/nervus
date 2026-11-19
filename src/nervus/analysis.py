"""Linear analysis: linearize a model, find steady states, and compute frequency responses and margins.

The model's top-level **In** blocks are the inputs and its **Out** blocks the outputs. Linearization works on
the continuous-time part of the model (blocks with continuous states); discrete blocks are held at their
current output.

    from nervus import load
    from nervus.analysis import linearize, trim

    plant = load("motor.nervus")
    op = trim(plant, {"voltage": 6.0})            # steady state for a 6 V input
    lin = linearize(plant, x0=op.x, u0={"voltage": 6.0})
    print(lin.poles(), lin.dc_gain())
    w, mag_db, phase = lin.bode()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import optimize
from scipy import signal as sps

from nervus.blocks.ports import Inport, Outport
from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError
from nervus.core.signals import Signal
from nervus.core.types import Array
from nervus.sim.compiler import CompiledModel, compile_diagram


@dataclass
class Margins:
    gain_margin_db: float
    """How much the loop gain can increase before instability (inf if the phase never reaches -180°)."""
    phase_margin_deg: float
    """How much phase lag can be added at the gain crossover before instability (inf if |L| never crosses 1)."""
    gain_crossover: float
    """Frequency [rad/s] where |L| = 1 (0 dB)."""
    phase_crossover: float
    """Frequency [rad/s] where the phase is -180°."""


@dataclass
class LinearModel:
    """x' = A x + B u, y = C x + D u around an operating point."""

    A: Array
    B: Array
    C: Array
    D: Array
    inputs: list[str]
    outputs: list[str]
    states: list[str] = field(default_factory=list)

    def poles(self) -> npt.NDArray[np.complex128]:
        return np.asarray(np.linalg.eigvals(self.A) if self.A.size else np.zeros(0), dtype=np.complex128)

    def is_stable(self) -> bool:
        return bool(np.all(self.poles().real < 0))

    def _siso(self, i: int, o: int) -> tuple[Array, Array, Array, Array]:
        return self.A, self.B[:, i : i + 1], self.C[o : o + 1, :], self.D[o : o + 1, i : i + 1]

    def transfer_function(self, input: int = 0, output: int = 0) -> tuple[Array, Array]:
        """Numerator and denominator (descending powers of s) from one input to one output."""
        a, b, c, d = self._siso(input, output)
        if a.size == 0:
            return np.atleast_1d(d.ravel()), np.array([1.0])
        num, den = sps.ss2tf(a, b, c, d)
        num = np.trim_zeros(np.where(np.abs(num[0]) < 1e-12 * np.max(np.abs(num[0]) + 1e-300), 0.0, num[0]), "f")
        return (num if num.size else np.array([0.0])), den

    def zeros(self, input: int = 0, output: int = 0) -> npt.NDArray[np.complex128]:
        num, _ = self.transfer_function(input, output)
        return np.asarray(np.roots(num) if num.size > 1 else np.zeros(0), dtype=np.complex128)

    def dc_gain(self, input: int = 0, output: int = 0) -> float:
        num, den = self.transfer_function(input, output)
        return float(np.polyval(num, 0.0) / np.polyval(den, 0.0)) if np.polyval(den, 0.0) != 0 else float("inf")

    def frequency_response(self, w: Array, input: int = 0, output: int = 0) -> Array:
        num, den = self.transfer_function(input, output)
        s = 1j * np.asarray(w, dtype=float)
        return np.polyval(num, s) / np.polyval(den, s)

    def bode(self, w: Array | None = None, input: int = 0, output: int = 0) -> tuple[Array, Array, Array]:
        """(w [rad/s], magnitude [dB], phase [°]) with the phase unwrapped."""
        if w is None:
            w = self.default_frequencies()
        h = self.frequency_response(w, input, output)
        mag = 20 * np.log10(np.maximum(np.abs(h), 1e-300))
        phase = np.degrees(np.unwrap(np.angle(h)))
        return np.asarray(w), mag, phase

    def default_frequencies(self) -> Array:
        p = np.abs(self.poles())
        z = np.abs(self.zeros())
        corners = np.concatenate([p[p > 0], z[z > 0]])
        lo = np.min(corners) / 100 if corners.size else 1e-2
        hi = np.max(corners) * 100 if corners.size else 1e2
        return np.logspace(np.log10(lo), np.log10(hi), 600)

    def margins(self, input: int = 0, output: int = 0) -> Margins:
        """Stability margins of this model used as an **open loop** L(s) in a unity negative feedback loop."""
        w = np.logspace(-4, 5, 20000)
        _, mag, phase = self.bode(w, input, output)
        gm, pm, wgc, wpc = np.inf, np.inf, np.nan, np.nan
        cross = np.nonzero(np.diff(np.sign(mag)) != 0)[0]
        if cross.size:
            k = cross[0]
            wgc = float(np.interp(0.0, [mag[k + 1], mag[k]], [w[k + 1], w[k]]))
            ph = float(np.interp(wgc, w, phase))
            pm = 180.0 + ph
        shifted = phase + 180.0
        pc = np.nonzero(np.diff(np.sign(shifted)) != 0)[0]
        if pc.size:
            k = pc[0]
            wpc = float(
                np.interp(
                    0.0,
                    sorted([shifted[k], shifted[k + 1]]),
                    [w[k], w[k + 1]] if shifted[k] < shifted[k + 1] else [w[k + 1], w[k]],
                )
            )
            gm = -float(np.interp(wpc, w, mag))
        return Margins(gm, pm, wgc, wpc)

    def step_response(self, t: Array | None = None, input: int = 0, output: int = 0) -> tuple[Array, Array]:
        num, den = self.transfer_function(input, output)
        tt, y = sps.step((num, den), T=t)
        return np.asarray(tt), np.asarray(y)


@dataclass
class OperatingPoint:
    x: Array
    """Continuous states."""
    u: dict[str, float]
    residual: float
    """Largest |dx/dt| left (0 for an exact steady state)."""


class _Evaluator:
    def __init__(self, diagram: Diagram, t: float) -> None:
        self.diagram = diagram
        self.t = t
        self.ins = sorted((b for b in diagram.blocks if isinstance(b, Inport)), key=lambda b: b.params["port"])
        self.outs = sorted((b for b in diagram.blocks if isinstance(b, Outport)), key=lambda b: b.params["port"])
        for b in self.ins:
            b.signal = Signal.constant(np.atleast_1d(np.asarray(b.params["value"], dtype=float)).tolist())
        self.model: CompiledModel = compile_diagram(diagram)
        if any(w != 1 for b in self.ins for w in [b.signal.width]):
            raise ModelError("linearization supports scalar In blocks only")
        m = self.model
        m.reset()
        m.eval_outputs(t, m.xc0, frozenset(range(len(m.rates))), init=True)
        self.out_nodes = [m.index_of(b) for b in self.outs]

    def close(self) -> None:
        for b in self.ins:
            b.signal = None

    def set_u(self, u: Array) -> None:
        for b, v in zip(self.ins, u, strict=True):
            b.signal = Signal.constant(float(v))

    def f(self, x: Array, u: Array) -> Array:
        self.set_u(u)
        return self.model.derivatives(self.t, x)

    def y(self, x: Array, u: Array) -> Array:
        self.set_u(u)
        self.model.eval_outputs(self.t, x, None)
        vals = []
        for i in self.out_nodes:
            s, p = self.model.inputs[i][0]
            vals.append(float(self.model.y[s][p][0]))
        return np.array(vals)


def _u_vector(ev: _Evaluator, u0: dict[str, Any] | None) -> Array:
    u0 = u0 or {}
    unknown = set(u0) - {b.name for b in ev.ins}
    if unknown:
        raise ModelError(f"no top-level In block named {', '.join(sorted(unknown))}")
    return np.array([float(u0.get(b.name, np.ravel(b.params["value"])[0])) for b in ev.ins])


def linearize(
    diagram: Diagram,
    x0: Array | None = None,
    u0: dict[str, Any] | None = None,
    t: float = 0.0,
    eps: float = 1e-6,
) -> LinearModel:
    """Linearize around the states ``x0`` (default: the initial states) and inputs ``u0`` (by In-block name;
    default: each In block's value), using central differences."""
    ev = _Evaluator(diagram, t)
    try:
        m = ev.model
        x = np.asarray(m.xc0 if x0 is None else x0, dtype=float).copy()
        u = _u_vector(ev, u0)
        n, k, p = x.size, u.size, len(ev.outs)
        a, b = np.zeros((n, n)), np.zeros((n, k))
        c, d = np.zeros((p, n)), np.zeros((p, k))
        for j in range(n):
            h = eps * max(1.0, abs(x[j]))
            xp, xm = x.copy(), x.copy()
            xp[j] += h
            xm[j] -= h
            a[:, j] = (ev.f(xp, u) - ev.f(xm, u)) / (2 * h)
            c[:, j] = (ev.y(xp, u) - ev.y(xm, u)) / (2 * h)
        for j in range(k):
            h = eps * max(1.0, abs(u[j]))
            up, um = u.copy(), u.copy()
            up[j] += h
            um[j] -= h
            b[:, j] = (ev.f(x, up) - ev.f(x, um)) / (2 * h)
            d[:, j] = (ev.y(x, up) - ev.y(x, um)) / (2 * h)
        states = []
        for i, sl in enumerate(m.xc_slices):
            states += [m.names[i] + (f"[{q}]" if sl.stop - sl.start > 1 else "") for q in range(sl.stop - sl.start)]
        return LinearModel(a, b, c, d, [bl.name for bl in ev.ins], [bl.name for bl in ev.outs], states)
    finally:
        ev.close()


def trim(
    diagram: Diagram, u0: dict[str, Any] | None = None, x_guess: Array | None = None, t: float = 0.0
) -> OperatingPoint:
    """Find continuous states where all derivatives are zero (a steady state) for constant inputs ``u0``."""
    ev = _Evaluator(diagram, t)
    try:
        u = _u_vector(ev, u0)
        x0 = np.asarray(ev.model.xc0 if x_guess is None else x_guess, dtype=float)
        if x0.size == 0:
            return OperatingPoint(x0, {b.name: float(v) for b, v in zip(ev.ins, u, strict=True)}, 0.0)
        sol = optimize.least_squares(lambda x: ev.f(x, u), x0, xtol=1e-12, ftol=1e-12, gtol=1e-12)
        res = float(np.max(np.abs(ev.f(sol.x, u))))
        return OperatingPoint(sol.x, {b.name: float(v) for b, v in zip(ev.ins, u, strict=True)}, res)
    finally:
        ev.close()
