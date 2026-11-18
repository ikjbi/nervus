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
        return self.sample_time().period

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
