"""Discrete-time blocks (updated at a fixed sample period)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.continuous import _StateSpaceBase, _tf_to_ss
from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array, as_signal

CATEGORY = "Discrete"


def _st(default: float) -> Param:
    return Param(
        "sample_time",
        default,
        ParamKind.SAMPLE_TIME,
        "Sample period (-1 = inherit from input)",
        "s",
    )


class _Discrete(Block):
    category = CATEGORY


@register
class UnitDelay(_Discrete):
    """Delays its input by one sample period:

    $$ y[k] = u[k-1], \\qquad y[0] = \\mathrm{initial} $$

    ![Unit Delay input and output](figures/unit_delay.png)

    Like an Integrator in continuous time, a Unit Delay breaks algebraic loops in discrete-time feedback.
    """

    type_id = "discrete.unit_delay"
    label = "Unit Delay"
    DIRECT_FEEDTHROUGH = False
    PARAMS = (Param("initial", 0.0, ParamKind.ARRAY, "Initial output"), _st(-1.0))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        return [n if n > 1 else in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd.copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return np.broadcast_to(u[0], xd.shape).copy()


@register
class ZeroOrderHold(_Discrete):
    """Samples its input every *sample_time* seconds and holds the value until the next sample:

    $$ y(t) = u(kT) \\quad \\mathrm{for}\\ kT \\leq t < (k+1)T $$

    ![Sampling a continuous signal with a Zero-Order Hold](figures/zero_order_hold.png)

    This is how a continuous signal (e.g. a sensor) enters a discrete controller.
    """

    type_id = "discrete.zero_order_hold"
    label = "Zero-Order Hold"
    PARAMS = (_st(1.0),)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [u[0].copy()]


@register
class DiscreteIntegrator(_Discrete):
    """Discrete-time integrator (accumulator).

    ![Forward vs backward Euler](figures/discrete_integrator.png)

    ``forward_euler`` (no direct feedthrough):

    $$ y[k] = x[k], \\qquad x[k+1] = x[k] + K\\,T\\,u[k] $$

    ``backward_euler``:

    $$ y[k] = x[k] + K\\,T\\,u[k], \\qquad x[k+1] = y[k] $$

    The state is limited to [*lower*, *upper*].
    """

    type_id = "discrete.integrator"
    label = "Discrete-Time Integrator"
    PARAMS = (
        Param("gain", 1.0, ParamKind.FLOAT, "Gain K"),
        Param("initial", 0.0, ParamKind.ARRAY, "Initial condition"),
        Param(
            "method",
            "forward_euler",
            ParamKind.CHOICE,
            "Integration method",
            choices=("forward_euler", "backward_euler"),
        ),
        Param("upper", np.inf, ParamKind.FLOAT, "Upper limit"),
        Param("lower", -np.inf, ParamKind.FLOAT, "Lower limit"),
        _st(1.0),
    )

    def validate_params(self) -> None:
        if self.params["lower"] > self.params["upper"]:
            raise ParameterError("lower limit must be <= upper limit")

    def _period(self) -> float:
        return self.period()

    def direct_feedthrough(self) -> bool:
        return bool(self.params["method"] == "backward_euler")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        return [n if n > 1 else in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        x0 = np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()
        return np.clip(x0, self.params["lower"], self.params["upper"])

    def _step(self, u: Array, xd: Array) -> Array:
        return np.clip(
            xd + self.params["gain"] * self._period() * u,
            self.params["lower"],
            self.params["upper"],
        )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        if self.params["method"] == "backward_euler":
            return [self._step(u[0], xd)]
        return [xd.copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self._step(u[0], xd)


@register
class DiscreteTransferFunction(_StateSpaceBase, _Discrete):
    """Discrete SISO transfer function

    $$ H(z) = \\frac{b_0 z^m + \\dots + b_m}{a_0 z^n + \\dots + a_n} $$

    Coefficients are in descending powers of *z*. For example ``[1]`` / ``[1, -0.9]`` is a first-order low-pass.
    """

    type_id = "discrete.transfer_function"
    label = "Discrete Transfer Fcn"
    DISCRETE = True
    PARAMS = (
        Param("numerator", [1.0], ParamKind.ARRAY, "Numerator coefficients (descending powers of z)"),
        Param(
            "denominator",
            [1.0, 0.5],
            ParamKind.ARRAY,
            "Denominator coefficients (descending powers of z)",
        ),
        _st(1.0),
    )

    def validate_params(self) -> None:
        _tf_to_ss(self.params["numerator"], self.params["denominator"])

    def matrices(self) -> tuple[Array, Array, Array, Array]:
        return _tf_to_ss(self.params["numerator"], self.params["denominator"])


@register
class IntegerDelay(_Discrete):
    """Delays its input by *delay* samples: ``y[k] = u[k - N]``. The first N outputs are *initial*.

    $$ y[k] = u[k-N] $$

    Use it to model communication or processing delays, e.g. a CAN message that arrives one 10 ms frame late.
    """

    type_id = "discrete.integer_delay"
    label = "Integer Delay"
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("delay", 2, ParamKind.INT, "Number of samples N", min=1),
        Param("initial", 0.0, ParamKind.FLOAT, "Output during the first N samples"),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.full(int(self.params["delay"]) * self.out_widths[0], self.params["initial"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd[: self.out_widths[0]].copy()]  # oldest sample first

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        w = self.out_widths[0]
        return np.concatenate([xd[w:], np.broadcast_to(u[0], (w,))])


@register
class Counter(_Discrete):
    """Counts samples while the input is non-zero (true).

    ![Counter](figures/counter.png)

    $$ y[k] = c[k], \\qquad c[k+1] = \\begin{cases} c[k] + 1 & \\text{if } u[k] \\neq 0 \\\\ c[k] & \\text{otherwise} \\end{cases} $$

    At *limit* the counter either ``wrap``s to 0 or ``saturate``s (stays at the limit). Connect a Constant 1
    for a free-running counter, e.g. to schedule something every N task periods.
    """

    type_id = "discrete.counter"
    label = "Counter"
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("limit", 255.0, ParamKind.FLOAT, "Largest value", min=1.0),
        Param("at_limit", "wrap", ParamKind.CHOICE, "What happens at the limit", choices=("wrap", "saturate")),
        Param("initial", 0.0, ParamKind.FLOAT, "Initial count"),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.full(self.out_widths[0], self.params["initial"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd.copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        lim = self.params["limit"]
        nxt = xd + (np.broadcast_to(u[0], xd.shape) != 0)
        if self.params["at_limit"] == "wrap":
            return np.where(nxt > lim, 0.0, nxt)
        return np.minimum(nxt, lim)


@register
class EdgeDetect(_Discrete):
    """Outputs 1 for one sample when the (boolean) input changes, otherwise 0.

    ![Edge detection](figures/edge_detect.png)

    *direction*: ``rising`` (false → true), ``falling`` (true → false) or ``either``. The input counts as
    true when it is non-zero. Typical use: react once when a switch is pressed or a fault appears.
    """

    type_id = "discrete.edge_detect"
    label = "Edge Detect"
    PARAMS = (
        Param("direction", "rising", ParamKind.CHOICE, "Which edge", choices=("rising", "falling", "either")),
        Param("initial", 0.0, ParamKind.FLOAT, "Previous input before the first sample (0 or 1)"),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.full(self.out_widths[0], 1.0 if self.params["initial"] else 0.0)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        now = np.broadcast_to(u[0], xd.shape) != 0
        before = xd != 0
        d = self.params["direction"]
        edge = (now & ~before) if d == "rising" else (~now & before) if d == "falling" else (now != before)
        return [edge.astype(float)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return (np.broadcast_to(u[0], xd.shape) != 0).astype(float)


@register
class Debounce(_Discrete):
    """Debounces a boolean input: the output turns on only after the input has been true for *on_samples*
    consecutive samples, and off after it has been false for *off_samples* samples.

    ![Debounce](figures/debounce.png)

    This is how ECUs filter switch bounce and confirm faults before setting a diagnostic trouble code.
    """

    type_id = "discrete.debounce"
    label = "Debounce"
    PARAMS = (
        Param("on_samples", 3, ParamKind.INT, "Samples the input must be true to switch on", min=1),
        Param("off_samples", 3, ParamKind.INT, "Samples the input must be false to switch off", min=1),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] != 1:
            raise ValueError("Debounce needs a scalar input")

    def initial_discrete_state(self) -> Array:
        return np.zeros(2)  # [output state, consecutive samples disagreeing with the state]

    def _next(self, u: Array, xd: Array) -> Array:
        state, count = xd
        now = float(u[0] != 0)
        if now == state:
            return np.array([state, 0.0])
        count += 1
        needed = self.params["on_samples"] if now else self.params["off_samples"]
        return np.array([now, 0.0]) if count >= needed else np.array([state, count])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [self._next(u[0], xd)[:1]]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self._next(u[0], xd)


@register
class DiscreteFilter(_Discrete):
    """First-order low-pass filter, the workhorse for smoothing sensor signals in ECU software.

    ![Low-pass filter](figures/discrete_filter.png)

    $$ y[k] = y[k-1] + \\alpha\\,(u[k] - y[k-1]), \\qquad \\alpha = \\frac{T}{\\tau + T} $$

    with time constant τ and sample period T. Larger τ gives a smoother but slower signal.
    """

    type_id = "discrete.filter"
    label = "Discrete Filter (PT1)"
    PARAMS = (
        Param("time_constant", 0.1, ParamKind.FLOAT, "Filter time constant τ", "s", min=0.0),
        Param("initial", 0.0, ParamKind.ARRAY, "Initial output"),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        return [n if n > 1 else in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()

    def _alpha(self) -> float:
        ts = self.period()
        return float(ts / (self.params["time_constant"] + ts))

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd + self._alpha() * (np.broadcast_to(u[0], xd.shape) - xd)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self.outputs(t, u, xc, xd)[0]


@register
class MovingAverage(_Discrete):
    """Average of the last *length* samples (including the current one).

    $$ y[k] = \\frac{1}{N} \\sum_{i=0}^{N-1} u[k-i] $$

    Before N samples exist, the missing ones count as *initial*.
    """

    type_id = "discrete.moving_average"
    label = "Moving Average"
    PARAMS = (
        Param("length", 4, ParamKind.INT, "Number of samples N", min=1),
        Param("initial", 0.0, ParamKind.FLOAT, "Value of samples before the start"),
        _st(-1.0),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.full((int(self.params["length"]) - 1) * self.out_widths[0], self.params["initial"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        w, n = self.out_widths[0], int(self.params["length"])
        window = np.concatenate([xd, np.broadcast_to(u[0], (w,))]).reshape(n, w)
        return [window.mean(axis=0)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        w = self.out_widths[0]
        if xd.size == 0:
            return xd
        return np.concatenate([xd[w:], np.broadcast_to(u[0], (w,))])
