"""Discrete-time blocks (updated at a fixed sample period)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.continuous import _StateSpaceBase, _tf_to_ss
from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import SampleTime
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

    *external_reset* adds a second input, **reset**. When it fires, the state goes back to *initial* before the
    output of that step is computed: ``rising`` (reset goes from ≤ 0 to > 0), ``falling`` (> 0 to ≤ 0),
    ``either``, or ``level`` (every step while reset ≠ 0). Typical use: clear an accumulated error or an
    on-time counter when a mode changes.
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
        Param(
            "external_reset",
            "none",
            ParamKind.CHOICE,
            "Add a reset input that sets the state back to the initial value",
            choices=("none", "rising", "falling", "either", "level"),
        ),
        _st(1.0),
    )

    def validate_params(self) -> None:
        if self.params["lower"] > self.params["upper"]:
            raise ParameterError("lower limit must be <= upper limit")

    @property
    def _has_reset(self) -> bool:
        return self.params.get("external_reset", "none") != "none"

    def num_inputs(self) -> int:
        return 2 if self._has_reset else 1

    def input_names(self) -> list[str]:
        return ["u", f"reset ({self.params['external_reset']})"] if self._has_reset else ["u"]

    def _reset_now(self, r: float, r_prev: float) -> bool:
        mode = self.params["external_reset"]
        rising, falling = r_prev <= 0 < r, r_prev > 0 >= r
        return {"rising": rising, "falling": falling, "either": rising or falling, "level": r != 0}.get(mode, False)

    def _effective(self, u: Sequence[Array], xd: Array) -> Array:
        """The state after an external reset (if one fires at this step)."""
        w = self.out_widths[0]
        if self._has_reset and self._reset_now(float(np.ravel(u[1])[0]), float(xd[w])):
            return self._x0()
        return xd[:w]

    def _period(self) -> float:
        return self.period()

    def direct_feedthrough(self) -> bool:
        return bool(self.params["method"] == "backward_euler") or self._has_reset

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        return [n if n > 1 else in_widths[0] if in_widths[0] is not None else 1]

    def _x0(self) -> Array:
        x0 = np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()
        return np.clip(x0, self.params["lower"], self.params["upper"])

    def initial_discrete_state(self) -> Array:
        """The accumulator, plus the previous reset input when there is an external reset."""
        x0 = self._x0()
        return np.concatenate([x0, [0.0]]) if self._has_reset else x0

    def _step(self, u: Array, xd: Array) -> Array:
        return np.clip(
            xd + self.params["gain"] * self._period() * u,
            self.params["lower"],
            self.params["upper"],
        )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        x = self._effective(u, xd)
        if self.params["method"] == "backward_euler":
            return [self._step(u[0], x)]
        return [x.copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        new = self._step(u[0], self._effective(u, xd))
        if self._has_reset:
            return np.concatenate([new, [float(np.ravel(u[1])[0])]])
        return new


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
    TYPE_RULE = "double"
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
    TYPE_RULE = "boolean"
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
    TYPE_RULE = "boolean"
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


@register
class RateTransition(_Discrete):
    """Passes a signal between two rates (two ECU tasks) in a way that is deterministic on an RTOS.

    ![Rate transitions between a 10 ms and a 100 ms task](figures/rate_transition.png)

    Set *sample_time* to the **slower** of the two rates. For ``slow_to_fast``, also set *output_sample_time* to
    the fast rate, so that the blocks after it inherit the fast rate.

    - ``fast_to_slow``: the slow task gets the fast signal sampled at its own start:
      $y = u$ at every slow sample (like a Zero-Order Hold).
    - ``slow_to_fast``: the fast task gets the slow signal **one slow period late**:
      $y[k] = u[k-1]$ at the slow rate (like a Unit Delay), held in between.

    Why the delay? On an ECU the fast task interrupts the slow one. If the fast task read the slow task's output
    directly, it would sometimes see the old and sometimes the new value, depending on timing. With the delay it
    always sees the value the slow task finished one period ago, in the simulation and on the target.
    C code generated with one function per task (``generate_c(..., tasks=True)``) requires a Rate Transition on
    every signal that crosses between rates.
    """

    type_id = "discrete.rate_transition"
    label = "Rate Transition"
    category = "Signal Attributes"
    PARAMS = (
        Param(
            "direction",
            "fast_to_slow",
            ParamKind.CHOICE,
            "From a faster to a slower rate, or from slower to faster",
            choices=("fast_to_slow", "slow_to_fast"),
        ),
        Param("initial", 0.0, ParamKind.ARRAY, "Output before the first slow sample has arrived (slow_to_fast)"),
        _st(0.1),
        Param(
            "output_sample_time",
            -1.0,
            ParamKind.SAMPLE_TIME,
            "slow_to_fast: the fast rate that the blocks after it inherit (-1 = the sample time)",
            "s",
        ),
    )

    def output_sample_time(self) -> SampleTime | None:
        st = SampleTime.from_value(self.params["output_sample_time"])
        return st if self._delayed and st.is_discrete else None

    @property
    def _delayed(self) -> bool:
        return bool(self.params["direction"] == "slow_to_fast")

    def validate_params(self) -> None:
        st = self.sample_time()
        if not st.is_discrete:
            raise ParameterError("a Rate Transition needs a discrete sample time: the slower of the two rates")

    def direct_feedthrough(self) -> bool:
        return not self._delayed

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        if not self._delayed:
            return np.zeros(0)
        return np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd.copy()] if self._delayed else [u[0].copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return np.broadcast_to(u[0], xd.shape).copy() if self._delayed else xd
