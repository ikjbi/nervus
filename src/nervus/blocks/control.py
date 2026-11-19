"""Controller blocks."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import CONTINUOUS
from nervus.core.types import Array

CATEGORY = "Control"

_PID_PARAMS = (
    Param("P", 1.0, ParamKind.FLOAT, "Proportional gain"),
    Param("I", 0.0, ParamKind.FLOAT, "Integral gain", "1/s"),
    Param("D", 0.0, ParamKind.FLOAT, "Derivative gain", "s"),
    Param("N", 100.0, ParamKind.FLOAT, "Derivative filter coefficient", "rad/s"),
    Param("initial_integrator", 0.0, ParamKind.FLOAT, "Initial value of the integral term"),
    Param("upper", math.inf, ParamKind.FLOAT, "Output upper limit"),
    Param("lower", -math.inf, ParamKind.FLOAT, "Output lower limit"),
    Param(
        "anti_windup",
        "none",
        ParamKind.CHOICE,
        "Anti-windup method used while the output is saturated",
        choices=("none", "clamping", "back_calculation"),
    ),
    Param("Kb", 1.0, ParamKind.FLOAT, "Back-calculation gain", "1/s", min=0.0),
)


class _PIDBase(Block):
    category = CATEGORY
    TYPE_RULE = "double"

    def validate_params(self) -> None:
        p = self.params
        if p["lower"] > p["upper"]:
            raise ParameterError("lower limit must be <= upper limit")
        if p["N"] <= 0:
            raise ParameterError("filter coefficient N must be > 0")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0]]

    def _initial(self) -> Array:
        w = self.out_widths[0]
        return np.concatenate([np.full(w, self.params["initial_integrator"]), np.zeros(w)])

    def _law(self, e: Array, x: Array) -> tuple[Array, Array, Array]:
        """Return (saturated output, integral rate, filter rate) for error ``e`` and state ``x``."""
        p = self.params
        w = e.size
        xi, xf = x[:w], x[w:]
        d_term = p["D"] * p["N"] * (e - xf)
        unsat = p["P"] * e + xi + d_term
        di = p["I"] * e
        mode = getattr(self, "mode", None)
        if mode is not None:  # frozen during variable-step integration: saturation -1 / 0 / +1
            sat = mode[:w]
            y = np.where(sat > 0, p["upper"], np.where(sat < 0, p["lower"], unsat))
        else:
            y = np.clip(unsat, p["lower"], p["upper"])
        if p["anti_windup"] == "clamping":
            if mode is not None or getattr(self, "sliding", False):
                # Variable step: a hard on/off clamp makes the integrator chatter at the limit (it switches off,
                # the output drops below the limit, it switches on ...). The true solution slides along the
                # limit with the integrator integrating just enough to stay there; a thin boundary layer gives
                # that solution without a discontinuity.
                finite = [abs(v) for v in (p["upper"], p["lower"]) if np.isfinite(v)]
                eps = 1e-3 * max(1.0, *finite) if finite else 1e-3
                room = np.where(di > 0, p["upper"] - unsat, unsat - p["lower"])
                di = di * np.clip(room / eps, 0.0, 1.0)
            else:
                # Fixed step: stop integrating when the output is saturated and integrating pushes it further out.
                pushing = (unsat != y) & (np.sign(unsat - y) == np.sign(di))
                di = np.where(pushing, 0.0, di)
        if p["anti_windup"] == "back_calculation":
            # Bleed the integrator by the amount the output exceeds the limit.
            di = di + p["Kb"] * (y - unsat)
        # Without a D term the filter state is unused: keep it still (a fast filter is stiff for nothing).
        df = p["N"] * (e - xf) if p["D"] != 0 else np.zeros_like(xf)
        return y, di, df


@register
class PID(_PIDBase):
    """Continuous PID controller (parallel form) with a filtered derivative:

    ![PID structure](figures/pid_structure.png)

    $$ u = P\\,e + I \\int e\\,dt + D \\frac{N s}{s + N} e $$

    The input is the control error *e*. The output is limited to [*lower*, *upper*]. When the output saturates,
    the integral term keeps growing ("winds up") and causes overshoot. *anti_windup* prevents that:

    - ``clamping`` stops integrating while the output is saturated and the error would push it further out.
    - ``back_calculation`` feeds the excess ``Kb·(y - u_unsat)`` back into the integrator. It is smooth, which
      variable-step solvers handle well.

    ![Anti-windup comparison](figures/pid_anti_windup.png)

    With variable-step solvers, zero-crossing detection locates the moments the output saturates exactly. With
    ``clamping``, the integrator then slides along the limit: it integrates just enough to keep the output there
    (a thin boundary layer of 0.1 % of the limit, instead of switching the integrator on and off, which would
    chatter). With a fixed-step solver the integrator is switched off in every step that would push the output
    further out.
    """

    type_id = "control.pid"
    label = "PID Controller"
    DEFAULT_SAMPLE_TIME = CONTINUOUS
    PARAMS = _PID_PARAMS

    def initial_continuous_state(self) -> Array:
        return self._initial()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [self._law(u[0], xc)[0]]

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        _, di, df = self._law(u[0], xc)
        return np.concatenate([di, df])

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        p = self.params
        if not (np.isfinite(p["upper"]) or np.isfinite(p["lower"])):
            return None
        w = u[0].size
        unsat = p["P"] * u[0] + xc[:w] + p["D"] * p["N"] * (u[0] - xc[w:])
        return np.concatenate([unsat - p["upper"], unsat - p["lower"]])

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        p = self.params
        if not (np.isfinite(p["upper"]) or np.isfinite(p["lower"])):
            return None
        w = u[0].size
        e = u[0]
        unsat = p["P"] * e + xc[:w] + p["D"] * p["N"] * (e - xc[w:])
        return np.where(unsat > p["upper"], 1.0, np.where(unsat < p["lower"], -1.0, 0.0))


@register
class DiscretePID(_PIDBase):
    """Discrete PID controller (parallel form), as it would run on an ECU every *sample_time* seconds.

    The integral and the derivative filter use forward Euler:

    $$ u[k] = P\\,e[k] + x_i[k] + D N (e[k] - x_f[k]) $$
    $$ x_i[k+1] = x_i[k] + I\\,T\\,e[k], \\qquad x_f[k+1] = x_f[k] + N\\,T\\,(e[k] - x_f[k]) $$

    The derivative filter is stable only when ``N·T < 2``. See :class:`PID` for the anti-windup options;
    ``clamping`` works well here because the controller is discrete.
    """

    type_id = "control.discrete_pid"
    label = "Discrete PID Controller"
    PARAMS = (*_PID_PARAMS, Param("sample_time", 0.01, ParamKind.SAMPLE_TIME, "Sample period", "s"))

    def validate_params(self) -> None:
        super().validate_params()
        st = self.sample_time()
        if st.is_discrete and self.params["D"] and self.params["N"] * st.period >= 2:
            raise ParameterError(
                f"N·T = {self.params['N'] * st.period:g} >= 2 makes the derivative filter unstable; "
                "reduce N or the sample time"
            )

    def initial_discrete_state(self) -> Array:
        return self._initial()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [self._law(u[0], xd)[0]]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        _, di, df = self._law(u[0], xd)
        return xd + self.period() * np.concatenate([di, df])


def _pid_outcomes(self: Block) -> list[str]:
    p = self.params
    out = []
    if np.isfinite(p["upper"]):
        out.append("output at upper limit")
    if np.isfinite(p["lower"]):
        out.append("output at lower limit")
    return [*out, "output within limits"] if out else []


def _pid_hits(self: Block, t: float, u: Sequence[Array], y: Sequence[Array], xd: Array) -> list[str]:
    p, out = self.params, y[0]
    hits = []
    if np.any(out >= p["upper"]):
        hits.append("output at upper limit")
    if np.any(out <= p["lower"]):
        hits.append("output at lower limit")
    if np.any((out > p["lower"]) & (out < p["upper"])):
        hits.append("output within limits")
    return hits


for _cls in (PID, DiscretePID):
    _cls.coverage_outcomes = _pid_outcomes  # type: ignore[method-assign]
    _cls.coverage_hits = _pid_hits  # type: ignore[method-assign]
