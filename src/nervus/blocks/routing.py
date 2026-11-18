"""Signal routing blocks."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width, broadcast_widths
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "Signal Routing"


class _Routing(Block):
    category = CATEGORY


@register
class Mux(_Routing):
    """Combines its inputs into one vector signal, in port order."""

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
    """Splits a vector signal into *num_outputs* equally sized parts."""

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
    """Passes input 0 when the control input (input 1) satisfies *criterion*, otherwise input 2.

    Criteria: ``u1 >= threshold``, ``u1 > threshold`` or ``u1 != 0``. The control input must be scalar.
    """

    type_id = "routing.switch"
    label = "Switch"
    NUM_INPUTS = 3
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

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        c, thr = float(u[1][0]), self.params["threshold"]
        crit = self.params["criterion"]
        passed = c >= thr if crit == "u1 >= threshold" else c > thr if crit == "u1 > threshold" else c != 0
        chosen = u[0] if passed else u[2]
        return [np.broadcast_to(chosen, (self.out_widths[0],)).copy()]
