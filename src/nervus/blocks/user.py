"""User-defined blocks."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array, as_signal

CATEGORY = "User-Defined"

_DEFAULT_CODE = '''def f(t, u):
    """Return the output for time t and input u (a NumPy array)."""
    return 2 * u
'''


@register
class PythonFunction(Block):
    """Runs your own Python function, the equivalent of Simulink's MATLAB Function block.

    *code* must define a function ``f(t, u0, u1, ...)`` with one argument per input. It returns one value per
    output (a tuple if there are several). Values may be scalars or arrays. ``np`` (NumPy) and ``math`` are
    available.

    The function must be *stateless*: its output may only depend on ``t`` and the inputs. Use Unit Delay or
    Integrator blocks for memory.

    !!! warning
        The code runs with full Python privileges. Only open model files from sources you trust.
    """

    type_id = "user.python_function"
    label = "Python Function"
    category = CATEGORY
    TYPE_RULE = "double"
    PARAMS = (
        Param("code", _DEFAULT_CODE, ParamKind.CODE, "Python source defining f(t, u0, ...)"),
        Param("num_inputs", 1, ParamKind.INT, "Number of inputs", min=0),
        Param("num_outputs", 1, ParamKind.INT, "Number of outputs", min=1),
        Param(
            "output_width",
            -1,
            ParamKind.INT,
            "Width of each output (-1 = same as input 0, or 1)",
            min=-1,
        ),
    )

    def validate_params(self) -> None:
        self._fn = self._compile()

    def _compile(self) -> Callable[..., Any]:
        namespace: dict[str, Any] = {"np": np, "math": math}
        try:
            exec(
                compile(self.params["code"], f"<{self.name or 'PythonFunction'}>", "exec"),
                namespace,
            )
        except SyntaxError as exc:
            raise ParameterError(f"syntax error in code, line {exc.lineno}: {exc.msg}") from exc
        fn = namespace.get("f")
        if not callable(fn):
            raise ParameterError("code must define a function named f")
        return fn

    def num_inputs(self) -> int:
        return int(self.params["num_inputs"])

    def num_outputs(self) -> int:
        return int(self.params["num_outputs"])

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        w = self.params["output_width"]
        if w > 0:
            return [w] * self.num_outputs()
        if self.num_inputs() == 0:
            return [1] * self.num_outputs()
        return [in_widths[0]] * self.num_outputs()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        args = [ui[0] if ui.size == 1 else ui for ui in u]
        out = self._fn(t, *args)
        if self.num_outputs() == 1:
            out = (out,)
        if not isinstance(out, tuple | list) or len(out) != self.num_outputs():
            raise ValueError(f"f must return {self.num_outputs()} values")
        return [np.broadcast_to(as_signal(o), (w,)).copy() for o, w in zip(out, self.out_widths, strict=True)]
