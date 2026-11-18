"""Math operation blocks."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width, broadcast_widths
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array, as_signal

CATEGORY = "Math Operations"


class _Math(Block):
    category = CATEGORY


@register
class Gain(_Math):
    """Multiplies the input by a constant.

    With *multiplication* = ``elementwise`` the output is ``gain .* u`` (scalars expand). With ``matrix``
    the output is the matrix product ``gain @ u``.
    """

    type_id = "math.gain"
    label = "Gain"
    PARAMS = (
        Param("gain", 1.0, ParamKind.ARRAY, "Gain value (scalar, vector or matrix)"),
        Param(
            "multiplication",
            "elementwise",
            ParamKind.CHOICE,
            "Multiplication",
            choices=("elementwise", "matrix"),
        ),
    )

    def validate_params(self) -> None:
        if self.params["multiplication"] == "matrix" and np.ndim(self.params["gain"]) != 2:
            raise ParameterError("matrix multiplication needs a 2-D gain matrix")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        g = np.asarray(self.params["gain"])
        if self.params["multiplication"] == "matrix":
            return [g.shape[0]]
        return [broadcast_widths([in_widths[0], g.size])]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        g = np.asarray(self.params["gain"], dtype=np.float64)
        if self.params["multiplication"] == "matrix" and g.shape[1] != in_widths[0]:
            raise ValueError(f"gain matrix has {g.shape[1]} columns but the input has width {in_widths[0]}")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        g = self.params["gain"]
        if self.params["multiplication"] == "matrix":
            return [g @ u[0]]
        return [as_signal(g) * u[0]]


@register
class Sum(_Math):
    """Adds and subtracts its inputs.

    *signs* holds one ``+`` or ``-`` per input, e.g. ``"+-"`` gives ``u0 - u1``. ``|`` characters are ignored
    (for spacing, as in Simulink).
    """

    type_id = "math.sum"
    label = "Sum"
    PARAMS = (Param("signs", "++", ParamKind.STR, "One + or - per input"),)

    def _signs(self) -> str:
        return self.params["signs"].replace("|", "").replace(" ", "")

    def validate_params(self) -> None:
        s = self._signs()
        if not s or set(s) - {"+", "-"}:
            raise ParameterError("signs must contain only '+', '-' (and optionally '|')")

    def num_inputs(self) -> int:
        return len(self._signs())

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        y = np.zeros(self.out_widths[0])
        for s, ui in zip(self._signs(), u, strict=True):
            y = y + ui if s == "+" else y - ui
        return [y]


@register
class Product(_Math):
    """Multiplies and divides its inputs elementwise.

    *ops* holds one ``*`` or ``/`` per input, e.g. ``"*/"`` gives ``u0 / u1``.
    """

    type_id = "math.product"
    label = "Product"
    PARAMS = (Param("ops", "**", ParamKind.STR, "One * or / per input"),)

    def validate_params(self) -> None:
        s = self.params["ops"]
        if not s or set(s) - {"*", "/"}:
            raise ParameterError("ops must contain only '*' and '/'")

    def num_inputs(self) -> int:
        return len(self.params["ops"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        y = np.ones(self.out_widths[0])
        for op, ui in zip(self.params["ops"], u, strict=True):
            y = y * ui if op == "*" else y / ui
        return [y]


@register
class Abs(_Math):
    """Absolute value, ``|u|``."""

    type_id = "math.abs"
    label = "Abs"

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.abs(u[0])]


@register
class Saturation(_Math):
    """Limits the input to the range [*lower*, *upper*]."""

    type_id = "math.saturation"
    label = "Saturation"
    category = "Discontinuities"
    PARAMS = (
        Param("upper", 0.5, ParamKind.FLOAT, "Upper limit"),
        Param("lower", -0.5, ParamKind.FLOAT, "Lower limit"),
    )

    def validate_params(self) -> None:
        if self.params["lower"] > self.params["upper"]:
            raise ParameterError("lower limit must be <= upper limit")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.clip(u[0], self.params["lower"], self.params["upper"])]


_FUNCTIONS: dict[str, Callable[[Array], Array]] = {
    "exp": np.exp,
    "log": np.log,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "square": np.square,
    "reciprocal": np.reciprocal,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "sign": np.sign,
    "floor": np.floor,
    "ceil": np.ceil,
    "round": np.round,
}


@register
class MathFunction(_Math):
    """Applies a mathematical function elementwise: exp, log, sqrt, square, sin, cos, tanh, sign, ..."""

    type_id = "math.function"
    label = "Math Function"
    PARAMS = (Param("function", "exp", ParamKind.CHOICE, "Function", choices=tuple(_FUNCTIONS)),)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [_FUNCTIONS[self.params["function"]](u[0])]
