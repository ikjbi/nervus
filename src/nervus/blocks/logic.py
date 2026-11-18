"""Logic and comparison blocks. Boolean signals are 1.0 (true) and 0.0 (false)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "Logic and Bit Operations"

_RELATIONS: dict[str, Callable[[Array, Array], Array]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


@register
class RelationalOperator(Block):
    """Compares input 0 with input 1: ``y = (u0 OP u1)``, giving 1 when true and 0 when false.

    $$ y = \\begin{cases} 1 & \\text{if } u_0 \\ \\mathrm{op}\\ u_1 \\\\ 0 & \\text{otherwise} \\end{cases} $$

    Avoid ``==`` and ``!=`` on computed floating-point signals; compare against a tolerance instead.
    """

    type_id = "logic.relational"
    label = "Relational Operator"
    category = CATEGORY
    NUM_INPUTS = 2
    PARAMS = (Param("operator", "<=", ParamKind.CHOICE, "Comparison", choices=tuple(_RELATIONS)),)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        if self.mode is not None:
            return [self.mode.copy()]
        res = _RELATIONS[self.params["operator"]](u[0], u[1])
        return [np.broadcast_to(np.asarray(res, dtype=float), (self.out_widths[0],)).copy()]

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        return np.broadcast_to(u[0] - u[1], (self.out_widths[0],)).copy()

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        res = _RELATIONS[self.params["operator"]](u[0], u[1])
        return np.broadcast_to(np.asarray(res, dtype=float), (self.out_widths[0],)).copy()


@register
class CompareToConstant(Block):
    """Compares the input with a constant: ``y = (u OP constant)``, 1 when true, 0 when false."""

    type_id = "logic.compare_to_constant"
    label = "Compare To Constant"
    category = CATEGORY
    PARAMS = (
        Param("operator", ">=", ParamKind.CHOICE, "Comparison", choices=tuple(_RELATIONS)),
        Param("constant", 0.0, ParamKind.FLOAT, "Constant to compare with"),
    )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        if self.mode is not None:
            return [self.mode.copy()]
        return [np.asarray(_RELATIONS[self.params["operator"]](u[0], self.params["constant"]), dtype=float)]

    def zero_crossings(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        return u[0] - self.params["constant"]

    def compute_mode(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array | None:
        return np.asarray(_RELATIONS[self.params["operator"]](u[0], self.params["constant"]), dtype=float)


_LOGIC = ("AND", "OR", "NOT", "XOR", "NAND", "NOR")


@register
class LogicalOperator(Block):
    """Boolean logic. Inputs are true when non-zero. The output is 1 (true) or 0 (false).

    | operator | output is true when |
    |---|---|
    | AND | all inputs are true |
    | OR | any input is true |
    | NOT | the (single) input is false |
    | XOR | an odd number of inputs is true |
    | NAND | not all inputs are true |
    | NOR | no input is true |
    """

    type_id = "logic.logical"
    label = "Logical Operator"
    category = CATEGORY
    PARAMS = (
        Param("operator", "AND", ParamKind.CHOICE, "Operation", choices=_LOGIC),
        Param("num_inputs", 2, ParamKind.INT, "Number of inputs (NOT has 1)", min=1),
    )

    def validate_params(self) -> None:
        if self.params["operator"] != "NOT" and self.params["num_inputs"] < 2:
            raise ParameterError(f"{self.params['operator']} needs at least 2 inputs")

    def num_inputs(self) -> int:
        return 1 if self.params["operator"] == "NOT" else int(self.params["num_inputs"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        w = self.out_widths[0]
        b = np.array([np.broadcast_to(ui != 0, (w,)) for ui in u])
        op = self.params["operator"]
        if op == "NOT":
            r = ~b[0]
        elif op == "AND":
            r = b.all(axis=0)
        elif op == "OR":
            r = b.any(axis=0)
        elif op == "XOR":
            r = b.sum(axis=0) % 2 == 1
        elif op == "NAND":
            r = ~b.all(axis=0)
        else:  # NOR
            r = ~b.any(axis=0)
        return [r.astype(float)]
