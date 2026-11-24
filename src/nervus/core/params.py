"""Declarative block parameters.

Blocks declare their parameters with :class:`Param`. The declarations are used to validate and convert values, to
build the property editor in the GUI, to save and load model files, and to generate the block reference docs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from nervus.core.errors import ParameterError


class ParamKind(StrEnum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    ARRAY = "array"  # scalar, vector or matrix of floats
    CHOICE = "choice"
    STR = "str"
    CODE = "code"  # multi-line source code
    SAMPLE_TIME = "sample_time"
    DATATYPE = "datatype"  # double, int16, fixdt(1,16,8), inherit, ...


_KIND_HINTS = {
    ParamKind.FLOAT: "Write a number (2.5, 1e-3), a workspace variable (Kp) or an expression (3.6 / m, 2*pi).",
    ParamKind.INT: "Write a whole number, or a workspace variable that holds one.",
    ParamKind.ARRAY: "Write a number, a vector [1 2 3], a matrix [1 0; 0 1], a workspace variable or an expression "
    "(e.g. Kp, 2*pi, [0 0.5 1] * v_max).",
    ParamKind.SAMPLE_TIME: "-1: inherited from the input · 0: continuous · 0.01: every 10 ms · [0.1, 0.02]: every "
    "100 ms, the first time at 20 ms (an offset).",
    ParamKind.DATATYPE: "inherit, double, single, boolean, int8 … int32, uint8 … uint32, or fixed point: "
    "fixdt(signed, bits, fraction bits), e.g. fixdt(1, 16, 8), or fixdt(signed, bits, slope, bias).",
    ParamKind.CODE: "Edit the text, then press Apply code.",
}
"""What can be written in a field of each kind, when the parameter has no hint of its own."""


@dataclass(frozen=True)
class Param:
    """Declaration of one block parameter."""

    name: str
    default: Any
    kind: ParamKind = ParamKind.FLOAT
    description: str = ""
    unit: str = ""
    choices: tuple[str, ...] = field(default=())
    min: float | None = None
    max: float | None = None
    hint: str = ""
    """What can be written, with examples (shown when the field is hovered or clicked in the editor)."""

    def help_text(self) -> str:
        """The description, what can be written (the hint, or the usual forms for this kind of parameter), the
        allowed range and the default: the help shown for the field in the Properties panel."""
        parts = [self.description.rstrip(".") + "." if self.description else self.name]
        parts.append(self.hint or _KIND_HINTS.get(self.kind, ""))
        if self.kind is ParamKind.CHOICE and self.choices:
            parts.append("Choose one of: " + ", ".join(self.choices) + ".")
        if self.unit:
            parts.append(f"Unit: {self.unit}.")
        if self.min is not None or self.max is not None:
            lo = "" if self.min is None else f"{self.min:g} ≤ "
            hi = "" if self.max is None else f" ≤ {self.max:g}"
            parts.append(f"Allowed: {lo}{self.name}{hi}.")
        if self.kind not in (ParamKind.CODE,) and self.default not in ("", None):
            parts.append(f"Default: {self.default}.")
        return "\n".join(x for x in parts if x)

    def coerce(self, value: Any) -> Any:
        """Convert ``value`` to this parameter's type, raising :class:`ParameterError` if invalid."""
        try:
            result = self._convert(value)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ParameterError):
                raise
            raise ParameterError(f"parameter '{self.name}': {exc}") from exc
        if self.kind in (ParamKind.FLOAT, ParamKind.INT):
            if self.min is not None and result < self.min:
                raise ParameterError(f"parameter '{self.name}' must be >= {self.min}, got {result}")
            if self.max is not None and result > self.max:
                raise ParameterError(f"parameter '{self.name}' must be <= {self.max}, got {result}")
        return result

    def _convert(self, value: Any) -> Any:
        kind = self.kind
        if kind is ParamKind.FLOAT:
            return float(value)
        if kind is ParamKind.INT:
            f = float(value)
            if not f.is_integer():
                raise ParameterError(f"parameter '{self.name}' must be an integer, got {value!r}")
            return int(f)
        if kind is ParamKind.BOOL:
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes", "on"):
                    return True
                if value.lower() in ("false", "0", "no", "off"):
                    return False
                raise ParameterError(f"parameter '{self.name}' must be a boolean, got {value!r}")
            return bool(value)
        if kind is ParamKind.ARRAY:
            arr = np.array(value, dtype=np.float64)
            if arr.ndim > 4:
                raise ParameterError(f"parameter '{self.name}' has more than 4 dimensions")
            return arr
        if kind is ParamKind.CHOICE:
            s = str(value)
            if s not in self.choices:
                raise ParameterError(f"parameter '{self.name}' must be one of {', '.join(self.choices)}; got {s!r}")
            return s
        if kind in (ParamKind.STR, ParamKind.CODE):
            return str(value)
        if kind is ParamKind.DATATYPE:
            from nervus.core.datatypes import parse_datatype

            parse_datatype(str(value))  # validates
            return str(value).strip()
        if kind is ParamKind.SAMPLE_TIME:
            from nervus.core.sample_time import SampleTime

            if isinstance(value, np.ndarray):
                value = value.tolist()
            st = SampleTime.from_value(value)
            return [st.period, st.offset] if st.offset else st.period
        raise AssertionError(kind)  # pragma: no cover


def output_type_param(default: str = "inherit") -> Param:
    """The standard *output_type* parameter (see :mod:`nervus.core.datatypes`)."""
    return Param(
        "output_type",
        default,
        ParamKind.DATATYPE,
        "Output data type: inherit, double, single, boolean, int8…uint32, fixdt(signed, bits, fraction)",
    )


def to_jsonable(value: Any) -> Any:
    """Convert a parameter value into something JSON can store."""
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
