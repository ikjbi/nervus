"""Discontinuous blocks: dead zone, relay, rate limiter, quantizer (Saturation lives in math_ops)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array, as_signal

CATEGORY = "Discontinuities"


def _st(default: float = -1.0) -> Param:
    return Param("sample_time", default, ParamKind.SAMPLE_TIME, "Sample period (-1 = inherit)", "s")


@register
class DeadZone(Block):
    """Zero output inside the dead zone [*start*, *end*]; outside, the input shifted by the zone edge.

    ![Dead zone characteristic](figures/dead_zone.png)

    $$ y = \\begin{cases} u - \\mathrm{end} & \\text{if } u > \\mathrm{end} \\\\ 0 & \\text{if } \\mathrm{start} \\leq u \\leq \\mathrm{end} \\\\ u - \\mathrm{start} & \\text{if } u < \\mathrm{start} \\end{cases} $$

    Typical use: ignore small pedal or sensor noise around zero.
    """

    type_id = "discontinuities.dead_zone"
    label = "Dead Zone"
    category = CATEGORY
    PARAMS = (
        Param("start", -0.5, ParamKind.FLOAT, "Lower edge of the dead zone"),
        Param("end", 0.5, ParamKind.FLOAT, "Upper edge of the dead zone"),
    )

    def validate_params(self) -> None:
        if self.params["start"] > self.params["end"]:
            raise ParameterError("start must be <= end")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        lo, hi = self.params["start"], self.params["end"]
        x = u[0]
        return [np.where(x > hi, x - hi, np.where(x < lo, x - lo, 0.0))]


@register
class Quantizer(Block):
    """Rounds the input to a multiple of *interval*, like an ADC or a fixed-resolution sensor.

    $$ y = q \\cdot \\mathrm{round}(u / q) $$
    """

    type_id = "discontinuities.quantizer"
    label = "Quantizer"
    category = CATEGORY
    PARAMS = (Param("interval", 0.5, ParamKind.FLOAT, "Quantization interval q", min=0.0),)

    def validate_params(self) -> None:
        if self.params["interval"] <= 0:
            raise ParameterError("interval must be > 0")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        q = self.params["interval"]
        return [q * np.round(u[0] / q)]


@register
class Relay(Block):
    """Switch with hysteresis: turns **on** when the input rises to *on_point* and **off** when it falls to
    *off_point*. In between it keeps its previous state.

    ![Relay hysteresis](figures/relay.png)

    $$ s[k] = \\begin{cases} 1 & \\text{if } u[k] \\geq \\mathrm{on\\_point} \\\\ 0 & \\text{if } u[k] \\leq \\mathrm{off\\_point} \\\\ s[k-1] & \\text{otherwise} \\end{cases} $$

    The output is *on_value* when $s = 1$ and *off_value* when $s = 0$. Use it for thermostats, fan control or
    any on/off decision that must not chatter. The relay is evaluated at its sample time, so it needs a
    discrete rate (set *sample_time*, or drive it from a discrete block).
    """

    type_id = "discontinuities.relay"
    label = "Relay"
    category = CATEGORY
    PARAMS = (
        Param("on_point", 1.0, ParamKind.FLOAT, "Switch on when u >= on_point"),
        Param("off_point", 0.0, ParamKind.FLOAT, "Switch off when u <= off_point"),
        Param("on_value", 1.0, ParamKind.FLOAT, "Output when on"),
        Param("off_value", 0.0, ParamKind.FLOAT, "Output when off"),
        Param("initial_state", "off", ParamKind.CHOICE, "State before the first sample", choices=("off", "on")),
        _st(),
    )

    def validate_params(self) -> None:
        if self.params["off_point"] > self.params["on_point"]:
            raise ParameterError("off_point must be <= on_point")

    def initial_discrete_state(self) -> Array:
        return np.full(self.out_widths[0], 1.0 if self.params["initial_state"] == "on" else 0.0)

    def _state(self, u: Array, xd: Array) -> Array:
        p = self.params
        return np.where(u >= p["on_point"], 1.0, np.where(u <= p["off_point"], 0.0, xd))

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        s = self._state(np.broadcast_to(u[0], xd.shape), xd)
        return [np.where(s > 0.5, self.params["on_value"], self.params["off_value"])]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self._state(np.broadcast_to(u[0], xd.shape), xd)


@register
class RateLimiter(Block):
    """Limits how fast the signal may change, e.g. torque or throttle ramps for drivability.

    ![Rate limiter](figures/rate_limiter.png)

    $$ y[k] = \\min\\left(\\max\\left(u[k],\\ y[k-1] + R_f T\\right),\\ y[k-1] + R_r T\\right) $$

    with rising rate $R_r > 0$ and falling rate $R_f < 0$ in units per second, and sample period $T$.
    """

    type_id = "discontinuities.rate_limiter"
    label = "Rate Limiter"
    category = CATEGORY
    PARAMS = (
        Param("rising_rate", 1.0, ParamKind.FLOAT, "Maximum increase per second", "1/s", min=0.0),
        Param("falling_rate", -1.0, ParamKind.FLOAT, "Maximum decrease per second (negative)", "1/s", max=0.0),
        Param("initial", 0.0, ParamKind.ARRAY, "Output before the first sample"),
        _st(),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        return [n if n > 1 else in_widths[0] if in_widths[0] is not None else 1]

    def initial_discrete_state(self) -> Array:
        return np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()

    def _limit(self, u: Array, prev: Array) -> Array:
        ts = self.period()
        p = self.params
        return np.minimum(np.maximum(u, prev + p["falling_rate"] * ts), prev + p["rising_rate"] * ts)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [self._limit(np.broadcast_to(u[0], xd.shape), xd)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self._limit(np.broadcast_to(u[0], xd.shape), xd)
