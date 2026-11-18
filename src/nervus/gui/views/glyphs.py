"""The short text drawn inside each block on the canvas (presentation only)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from nervus.core import Block
from nervus.core.expressions import format_value


def _num(v: object) -> str:
    s = v if isinstance(v, str) else format_value(v)
    return s if len(s) <= 10 else s[:9] + "…"


def _tf(b: Block, var: str) -> str:
    def poly(c: object) -> str:
        coeffs = [float(x) for x in np.atleast_1d(np.asarray(c, dtype=float))]
        n = len(coeffs) - 1
        terms = []
        for i, a in enumerate(coeffs):
            p = n - i
            if a == 0:
                continue
            mag = abs(a)
            coef = "" if (mag == 1 and p > 0) else f"{mag:g}"
            term = coef + (var if p == 1 else f"{var}²" if p == 2 else f"{var}^{p}" if p > 2 else "")
            terms.append(("-" if a < 0 else "+") + term)
        s = "".join(terms) or "0"
        return s[1:] if s.startswith("+") else s

    return f"{poly(b.params['numerator'])}\n{'─' * 6}\n{poly(b.params['denominator'])}"


_GLYPHS: dict[str, Callable[[Block], str]] = {
    "sources.constant": lambda b: _num(b.param_source("value")),
    "sources.step": lambda b: "⌐ step",
    "sources.ramp": lambda b: "⟋",
    "sources.sine": lambda b: "∿",
    "sources.pulse": lambda b: "⊓⊓",
    "sources.clock": lambda b: "🕒 t",
    "sources.from_workspace": lambda b: "data",
    "math.gain": lambda b: _num(b.param_source("gain")),
    "math.sum": lambda b: "Σ " + b.params["signs"].replace("|", ""),
    "math.product": lambda b: "× " + b.params["ops"],
    "math.abs": lambda b: "|u|",
    "math.saturation": lambda b: "⟋̲̅",
    "math.function": lambda b: b.params["function"],
    "continuous.integrator": lambda b: "1/s",
    "continuous.derivative": lambda b: "du/dt",
    "continuous.transfer_function": lambda b: _tf(b, "s"),
    "continuous.state_space": lambda b: "ẋ = Ax+Bu\ny = Cx+Du",
    "discrete.unit_delay": lambda b: "1/z",
    "discrete.zero_order_hold": lambda b: "ZOH",
    "discrete.integrator": lambda b: "KTs\n───\nz-1",
    "discrete.transfer_function": lambda b: _tf(b, "z"),
    "control.pid": lambda b: "PID(s)",
    "control.discrete_pid": lambda b: "PID(z)",
    "sinks.scope": lambda b: "📈",
    "sinks.to_workspace": lambda b: b.params["variable"],
    "sinks.terminator": lambda b: "⊣",
    "routing.mux": lambda b: "mux",
    "routing.demux": lambda b: "demux",
    "routing.switch": lambda b: "switch",
    "user.python_function": lambda b: "f(u)",
}


def glyph(block: Block) -> str:
    fn = _GLYPHS.get(block.type_id)
    try:
        return fn(block) if fn else block.label
    except Exception:
        return block.label
