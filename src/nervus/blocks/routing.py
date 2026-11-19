"""Signal routing blocks."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width, broadcast_widths
from nervus.core.params import Param, ParamKind, output_type_param
from nervus.core.types import Array

CATEGORY = "Signal Routing"


class _Routing(Block):
    category = CATEGORY


@register
class Mux(_Routing):
    """Combines its inputs into one vector signal, in port order.

    ![Mux and Demux](figures/mux_demux.png)
    """

    type_id = "routing.mux"
    label = "Mux"
    PARAMS = (Param("num_inputs", 2, ParamKind.INT, "Number of inputs", min=1),)

    def num_inputs(self) -> int:
        return int(self.params["num_inputs"])

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        if any(w is None for w in in_widths):
            return [None]
        return [sum(w for w in in_widths if w is not None)]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.concatenate(u)]


@register
class Demux(_Routing):
    """Splits a vector signal into *num_outputs* equally sized parts.

    ![Mux and Demux](figures/mux_demux.png)
    """

    type_id = "routing.demux"
    label = "Demux"
    PARAMS = (Param("num_outputs", 2, ParamKind.INT, "Number of outputs", min=1),)

    def num_outputs(self) -> int:
        return int(self.params["num_outputs"])

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        w, n = in_widths[0], self.num_outputs()
        if w is None:
            return [None] * n
        if w % n:
            raise ValueError(f"input width {w} cannot be split into {n} equal parts")
        return [w // n] * n

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [part.copy() for part in np.split(u[0], self.num_outputs())]


@register
class Switch(_Routing):
    """Passes input 0 when the control input (input 1) satisfies *criterion*, otherwise input 2:

    $$ y = \\begin{cases} u_0 & \\text{if } u_1 \\geq \\mathrm{threshold} \\\\ u_2 & \\text{otherwise} \\end{cases} $$

    ![Switch ports](figures/switch.png)

    Criteria: ``u1 >= threshold``, ``u1 > threshold`` or ``u1 != 0``. The control input must be scalar.
    """

    type_id = "routing.switch"
    label = "Switch"
    NUM_INPUTS = 3
    TYPE_INPUTS = (0, 2)  # the control input does not determine the output type
    PARAMS = (
        Param(
            "criterion",
            "u1 >= threshold",
            ParamKind.CHOICE,
            "Condition on the control input",
            choices=("u1 >= threshold", "u1 > threshold", "u1 != 0"),
        ),
        Param("threshold", 0.0, ParamKind.FLOAT, "Threshold"),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [broadcast_widths([in_widths[0], in_widths[2]])]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[1] != 1:
            raise ValueError("the control input (input 1) must be scalar")

    def _passed(self, u: Sequence[Array]) -> bool:
        c, thr = float(u[1][0]), self.params["threshold"]
        crit = self.params["criterion"]
        return bool(c >= thr if crit == "u1 >= threshold" else c > thr if crit == "u1 > threshold" else c != 0)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        passed = bool(self.mode[0] > 0.5) if self.mode is not None else self._passed(u)
        chosen = u[0] if passed else u[2]
        return [np.broadcast_to(chosen, (self.out_widths[0],)).copy()]

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        if self.params["criterion"] == "u1 != 0":
            return u[1]
        return u[1] - self.params["threshold"]

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        return np.array([1.0 if self._passed(u) else 0.0])

    def coverage_outcomes(self) -> list[str]:
        return ["input 0 passed", "input 2 passed"]

    def coverage_hits(self, t: float, u: Sequence[Array], y: Sequence[Array], xd: Array) -> list[str]:
        return ["input 0 passed" if self._passed(u) else "input 2 passed"]


@register
class DataTypeConversion(_Routing):
    """Converts the input to another data type, e.g. a sensor value to ``int16`` or a controller output to
    fixed point.

    ![Converting a signal to int8 and to fixed point](figures/datatype_conversion.png)

    The real-world value is kept as well as the type allows:

    $$ Q = \\mathrm{round}\\left(\\frac{u - \\mathrm{bias}}{\\mathrm{slope}}\\right), \\qquad y = \\mathrm{slope} \\cdot Q + \\mathrm{bias} $$

    *rounding*: ``nearest`` (half away from zero), ``floor``, ``ceil`` or ``zero`` (truncate). *overflow*:
    ``saturate`` limits to the type's range; ``wrap`` wraps around like C integer arithmetic. For example
    ``int8`` turns 3.6 into 4, and 200 into 127 (saturate) or -56 (wrap).
    """

    type_id = "routing.datatype_conversion"
    label = "Data Type Conversion"
    category = "Signal Attributes"
    PARAMS = (
        output_type_param("int16"),
        Param("rounding", "nearest", ParamKind.CHOICE, "Rounding", choices=("nearest", "floor", "ceil", "zero")),
        Param("overflow", "saturate", ParamKind.CHOICE, "Out-of-range values", choices=("saturate", "wrap")),
    )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [u[0].copy()]  # the conversion itself is applied by the simulator from output_type
