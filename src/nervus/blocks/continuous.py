"""Continuous-time blocks (with continuous states)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import signal as sps

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import CONTINUOUS
from nervus.core.types import Array, as_signal

CATEGORY = "Continuous"


class _Continuous(Block):
    category = CATEGORY
    DEFAULT_SAMPLE_TIME = CONTINUOUS


@register
class Integrator(_Continuous):
    """Integrates its input:

    $$ y(t) = y_0 + \\int_0^t u(\\tau)\\,d\\tau $$

    where y₀ is *initial*.

    ![Integrator with and without limits](figures/integrator_limits.png)

    The output is limited to [*lower*, *upper*]. At a limit the integration stops (no wind-up).
    A vector *initial* gives a vector integrator; a scalar *initial* expands to the input width.
    """

    type_id = "continuous.integrator"
    label = "Integrator"
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("initial", 0.0, ParamKind.ARRAY, "Initial condition"),
        Param("upper", math.inf, ParamKind.FLOAT, "Upper saturation limit"),
        Param("lower", -math.inf, ParamKind.FLOAT, "Lower saturation limit"),
    )

    def validate_params(self) -> None:
        if self.params["lower"] > self.params["upper"]:
            raise ParameterError("lower limit must be <= upper limit")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        n = as_signal(self.params["initial"]).size
        if n > 1:
            return [n]
        return [in_widths[0] if in_widths[0] is not None else 1]

    def initial_continuous_state(self) -> Array:
        x0 = np.broadcast_to(as_signal(self.params["initial"]), (self.out_widths[0],)).copy()
        return np.clip(x0, self.params["lower"], self.params["upper"])

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] not in (1, out_widths[0]):
            raise ValueError(f"input width {in_widths[0]} does not match the initial condition width {out_widths[0]}")
        self._limited = bool(np.isfinite(self.params["lower"]) or np.isfinite(self.params["upper"]))

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        if not self._limited:
            return [xc.copy()]
        return [np.minimum(np.maximum(xc, self.params["lower"]), self.params["upper"])]

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        if not self._limited:
            return u[0] if u[0].shape == xc.shape else np.broadcast_to(u[0], xc.shape).copy()
        du = np.broadcast_to(u[0], xc.shape).copy()
        if self.mode is not None:  # frozen: held at a limit (+1/-1) or free (0)
            du[self.mode != 0] = 0.0
            return du
        du[(xc >= self.params["upper"]) & (du > 0)] = 0.0
        du[(xc <= self.params["lower"]) & (du < 0)] = 0.0
        return du

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        if not self._limited:
            return None
        lo, hi = self.params["lower"], self.params["upper"]
        parts = [np.broadcast_to(u[0], xc.shape)]  # leaving a limit: the input changes sign
        if np.isfinite(hi):
            parts.append(xc - hi)
        if np.isfinite(lo):
            parts.append(xc - lo)
        return np.concatenate(parts)

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        if not self._limited:
            return None
        lo, hi = self.params["lower"], self.params["upper"]
        tol = 1e-9 * max(1.0, float(np.max(np.abs(np.nan_to_num(xc)))) if xc.size else 1.0)
        du = np.broadcast_to(u[0], xc.shape)
        return np.where((xc >= hi - tol) & (du >= 0), 1.0, np.where((xc <= lo + tol) & (du <= 0), -1.0, 0.0))


@register
class Derivative(_Continuous):
    """Approximate time derivative of the input.

    An exact derivative cannot be simulated robustly, so this block uses the filtered derivative

    $$ Y(s) = \\frac{s}{\\tau s + 1} U(s) $$

    with a small *time_constant* τ. Smaller τ is more exact but noisier and stiffer. The filter starts at rest,
    so a non-zero input at t = 0 gives an initial spike.
    """

    type_id = "continuous.derivative"
    label = "Derivative"
    PARAMS = (Param("time_constant", 1e-3, ParamKind.FLOAT, "Filter time constant τ", "s"),)

    def validate_params(self) -> None:
        if self.params["time_constant"] <= 0:
            raise ParameterError("time_constant must be > 0")

    def initial_continuous_state(self) -> Array:
        return np.zeros(self.out_widths[0])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [(u[0] - xc) / self.params["time_constant"]]

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return (u[0] - xc) / self.params["time_constant"]


def _check_ss(a: Array, b: Array, c: Array, d: Array) -> None:
    n = a.shape[0]
    if a.shape != (n, n):
        raise ParameterError("A must be square")
    if b.shape[0] != n or c.shape[1] != n:
        raise ParameterError("B must have as many rows, and C as many columns, as A")
    if d.shape != (c.shape[0], b.shape[1]):
        raise ParameterError(f"D must be {c.shape[0]}x{b.shape[1]}")


def _tf_to_ss(num: Array, den: Array) -> tuple[Array, Array, Array, Array]:
    num, den = np.atleast_1d(num).astype(float), np.atleast_1d(den).astype(float)
    den = np.trim_zeros(den, "f")
    num = np.trim_zeros(num, "f") if np.any(num) else np.zeros(1)
    if den.size == 0:
        raise ParameterError("denominator cannot be zero")
    if num.size > den.size:
        raise ParameterError("transfer function must be proper (numerator order <= denominator order)")
    if den.size == 1:  # a static gain: no states
        return np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), np.array([[num[-1] / den[0]]])
    a, b, c, d = sps.tf2ss(num, den)
    return (
        np.atleast_2d(np.asarray(a, float)).reshape(den.size - 1, den.size - 1),
        np.asarray(b, float).reshape(den.size - 1, 1),
        np.asarray(c, float).reshape(1, den.size - 1),
        np.asarray(d, float).reshape(1, 1),
    )


class _StateSpaceBase(Block):
    """Shared implementation of x' = Ax + Bu, y = Cx + Du (continuous) or x[k+1] = Ax + Bu (discrete)."""

    DISCRETE = False

    def matrices(self) -> tuple[Array, Array, Array, Array]:
        raise NotImplementedError

    def initial_state_param(self) -> Array:
        return np.zeros(0)

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [self.matrices()[2].shape[0]]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        a, b, c, d = self.matrices()
        if in_widths[0] != b.shape[1]:
            raise ValueError(f"input width is {in_widths[0]} but the system expects {b.shape[1]} input(s)")
        self._abcd = (a, b, c, d)

    def direct_feedthrough(self) -> bool:
        return bool(np.any(self.matrices()[3]))

    def _x0(self) -> Array:
        n = self.matrices()[0].shape[0]
        x0 = self.initial_state_param()
        if x0.size in (0, 1):
            return np.full(n, float(x0[0]) if x0.size else 0.0)
        if x0.size != n:
            raise ValueError(f"initial state must have {n} elements")
        return x0.copy()

    def initial_continuous_state(self) -> Array:
        return np.zeros(0) if self.DISCRETE else self._x0()

    def initial_discrete_state(self) -> Array:
        return self._x0() if self.DISCRETE else np.zeros(0)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        _a, _b, c, d = self._abcd
        x = xd if self.DISCRETE else xc
        return [c @ x + d @ u[0]]

    def derivatives(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        a, b, _c, _d = self._abcd
        return a @ xc + b @ u[0]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        a, b, _c, _d = self._abcd
        return a @ xd + b @ u[0]


@register
class TransferFunction(_StateSpaceBase, _Continuous):
    """Continuous SISO transfer function

    ![Step responses of a first- and a second-order transfer function](figures/transfer_function.png)

    $$ G(s) = \\frac{b_0 s^m + \\dots + b_m}{a_0 s^n + \\dots + a_n} $$

    *numerator* and *denominator* are coefficient lists in descending powers of *s*, e.g. ``[1]`` and ``[0.5, 1]``
    for ``1 / (0.5 s + 1)``. The initial state is zero.
    """

    type_id = "continuous.transfer_function"
    label = "Transfer Fcn"
    PARAMS = (
        Param("numerator", [1.0], ParamKind.ARRAY, "Numerator coefficients (descending powers of s)"),
        Param(
            "denominator",
            [1.0, 1.0],
            ParamKind.ARRAY,
            "Denominator coefficients (descending powers of s)",
        ),
    )

    def validate_params(self) -> None:
        _tf_to_ss(self.params["numerator"], self.params["denominator"])

    def matrices(self) -> tuple[Array, Array, Array, Array]:
        return _tf_to_ss(self.params["numerator"], self.params["denominator"])


@register
class StateSpace(_StateSpaceBase, _Continuous):
    """Continuous linear state-space system

    $$ \\dot x = A x + B u, \\qquad y = C x + D u $$

    The input width must equal the number of columns of *B*; the output width is the number of rows of *C*.
    """

    type_id = "continuous.state_space"
    label = "State-Space"
    PARAMS = (
        Param("A", [[-1.0]], ParamKind.ARRAY, "State matrix (n×n)"),
        Param("B", [[1.0]], ParamKind.ARRAY, "Input matrix (n×m)"),
        Param("C", [[1.0]], ParamKind.ARRAY, "Output matrix (p×n)"),
        Param("D", [[0.0]], ParamKind.ARRAY, "Feedthrough matrix (p×m)"),
        Param("initial", 0.0, ParamKind.ARRAY, "Initial state (scalar or n-vector)"),
    )

    def validate_params(self) -> None:
        _check_ss(*self.matrices())

    def matrices(self) -> tuple[Array, Array, Array, Array]:
        return tuple(np.atleast_2d(np.asarray(self.params[k], float)) for k in "ABCD")  # type: ignore[return-value]

    def initial_state_param(self) -> Array:
        return as_signal(self.params["initial"])
