"""Signal data types: floating point, integers, boolean and fixed point.

ECU software rarely uses ``double``: sensor values arrive as integers, and controllers without a floating-point
unit compute in **fixed point**, where an integer *stored value* ``Q`` represents the real value

    V = slope · Q + bias,      slope = 2^-fraction_length (binary-point scaling)

with ``Q`` limited to the range of the integer word (e.g. -32768 … 32767 for 16 bits signed).

Type names (also accepted in block parameters):

* ``double``, ``single``, ``boolean``
* ``int8``, ``uint8``, ``int16``, ``uint16``, ``int32``, ``uint32``
* ``fixdt(signed, word_length, fraction_length)``, e.g. ``fixdt(1, 16, 8)``: signed 16-bit, resolution 1/256
* ``fixdt(signed, word_length, slope, bias)``, e.g. ``fixdt(0, 8, 0.5, -40)`` for a temperature in 0.5 °C
  steps starting at -40 °C
* ``inherit``: take the type from the inputs

Converting a value to a type rounds it (*rounding*: ``nearest`` = half away from zero, ``floor``, ``ceil``,
``zero``) and handles values outside the range (*overflow*: ``saturate`` or ``wrap``), exactly like the
generated C code does.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from nervus.core.errors import ParameterError
from nervus.core.types import Array

ROUNDING = ("nearest", "floor", "ceil", "zero")
OVERFLOW = ("saturate", "wrap")

_INTS = {
    "int8": (True, 8),
    "uint8": (False, 8),
    "int16": (True, 16),
    "uint16": (False, 16),
    "int32": (True, 32),
    "uint32": (False, 32),
}


@dataclass(frozen=True)
class DataType:
    kind: str
    """``double``, ``single``, ``boolean`` or ``fixed`` (integers are fixed point with slope 1, bias 0)."""
    signed: bool = True
    bits: int = 64
    slope: float = 1.0
    bias: float = 0.0

    # ------------------------------------------------------------------ properties

    @property
    def is_double(self) -> bool:
        return self.kind == "double"

    @property
    def is_integer(self) -> bool:
        return self.kind == "fixed" and self.slope == 1.0 and self.bias == 0.0

    @property
    def is_fixed(self) -> bool:
        return self.kind == "fixed"

    @property
    def stored_min(self) -> int:
        return -(2 ** (self.bits - 1)) if self.signed else 0

    @property
    def stored_max(self) -> int:
        return 2 ** (self.bits - 1) - 1 if self.signed else 2**self.bits - 1

    @property
    def min(self) -> float:
        if self.kind == "boolean":
            return 0.0
        if self.kind != "fixed":
            return -float(np.finfo(np.float32 if self.kind == "single" else np.float64).max)
        return self.stored_min * self.slope + self.bias

    @property
    def max(self) -> float:
        if self.kind == "boolean":
            return 1.0
        if self.kind != "fixed":
            return float(np.finfo(np.float32 if self.kind == "single" else np.float64).max)
        return self.stored_max * self.slope + self.bias

    @property
    def resolution(self) -> float:
        return self.slope if self.kind == "fixed" else 0.0

    @property
    def name(self) -> str:
        if self.kind != "fixed":
            return self.kind
        if self.is_integer and self.bits in (8, 16, 32):
            return f"{'' if self.signed else 'u'}int{self.bits}"
        frac = -math.log2(self.slope) if self.slope > 0 else 0.0
        if self.bias == 0.0 and float(frac).is_integer():
            return f"fixdt({int(self.signed)}, {self.bits}, {int(frac)})"
        return f"fixdt({int(self.signed)}, {self.bits}, {self.slope!r}, {self.bias!r})"

    @property
    def short_name(self) -> str:
        """Compact name for labels, Simulink style: ``sfix16_En8`` (16 bits, 8 fraction bits),
        ``ufix8_S0.5_B-40`` (slope 0.5, bias -40)."""
        if self.kind != "fixed" or self.is_integer:
            return self.name
        base = f"{'s' if self.signed else 'u'}fix{self.bits}"
        frac = -math.log2(self.slope)
        if self.bias == 0.0 and float(frac).is_integer():
            return f"{base}_En{int(frac)}"
        return f"{base}_S{self.slope:g}_B{self.bias:g}"

    @property
    def c_type(self) -> str:
        """The C type used for this type's stored value at the generated code's interface."""
        if self.kind == "double":
            return "real_T"
        if self.kind == "single":
            return "real32_T"
        if self.kind == "boolean":
            return "boolean_T"
        width = 8 if self.bits <= 8 else 16 if self.bits <= 16 else 32
        return f"{'int' if self.signed else 'uint'}{width}_T"

    def __str__(self) -> str:
        return self.name

    # ------------------------------------------------------------------ conversion

    def quantize(self, x: Array, rounding: str = "nearest", overflow: str = "saturate") -> Array:
        """Convert real-world values to this type and back: the value the type can actually hold."""
        x = np.asarray(x, dtype=np.float64)
        if self.kind == "double":
            return x
        if self.kind == "single":
            return x.astype(np.float32).astype(np.float64)
        if self.kind == "boolean":
            return (x != 0).astype(np.float64)
        q = round_values((x - self.bias) / self.slope, rounding)
        q = handle_overflow(q, self.stored_min, self.stored_max, overflow)
        return q * self.slope + self.bias

    def to_stored(self, x: Array) -> Array:
        """Stored integers of already-quantized real-world values."""
        if self.kind != "fixed":
            return np.asarray(x, dtype=np.float64)
        return np.rint((np.asarray(x, dtype=np.float64) - self.bias) / self.slope)


def round_values(x: Array, rounding: str) -> Array:
    """Rounding exactly as C's ``round`` (half away from zero), ``floor``, ``ceil`` and ``trunc``."""
    if rounding == "floor":
        return np.floor(x)
    if rounding == "ceil":
        return np.ceil(x)
    if rounding == "zero":
        return np.trunc(x)
    t = np.trunc(x)
    frac = x - t  # exact in floating point
    return t + np.where(np.abs(frac) >= 0.5, np.sign(x), 0.0)


def handle_overflow(q: Array, lo: int, hi: int, overflow: str) -> Array:
    if overflow == "wrap":
        span = float(hi - lo + 1)
        return np.mod(q - lo, span) + lo
    return np.minimum(np.maximum(q, float(lo)), float(hi))


DOUBLE = DataType("double")
SINGLE = DataType("single", bits=32)
BOOLEAN = DataType("boolean", signed=False, bits=8)

_FIXDT = re.compile(r"^fixdt\s*\((.*)\)$")


def parse_datatype(text: str) -> DataType | None:
    """Parse a type name. Returns ``None`` for ``inherit``. Raises :class:`ParameterError` if invalid."""
    s = str(text).strip()
    low = s.lower()
    if low in ("inherit", "auto", ""):
        return None
    if low == "double":
        return DOUBLE
    if low in ("single", "float"):
        return SINGLE
    if low in ("boolean", "bool"):
        return BOOLEAN
    if low in _INTS:
        signed, bits = _INTS[low]
        return DataType("fixed", signed, bits)
    m = _FIXDT.match(low)
    if m:
        try:
            from nervus.core.expressions import parse_value

            args = [float(parse_value(a.replace("^", "**"))) for a in m.group(1).split(",")]
        except Exception as exc:
            raise ParameterError(f"invalid fixdt arguments in {s!r}") from exc
        if len(args) not in (3, 4):
            raise ParameterError(
                "fixdt needs (signed, word_length, fraction_length) or (signed, word_length, slope, bias)"
            )
        signed, bits = bool(args[0]), int(args[1])
        if not 1 < bits <= 32:
            raise ParameterError("fixed-point word length must be 2 … 32 bits")
        if len(args) == 3:
            slope, bias = 2.0 ** -args[2], 0.0
        else:
            slope, bias = args[2], args[3]
        if slope <= 0:
            raise ParameterError("fixed-point slope must be > 0")
        return DataType("fixed", signed, bits, slope, bias)
    raise ParameterError(f"unknown data type {s!r}; use double, single, boolean, int8 … uint32, fixdt(...) or inherit")


def common_type(types: list[DataType]) -> DataType:
    """The type of an operation on several inputs: the shared type, or double if they differ."""
    unique = set(types)
    return unique.pop() if len(unique) == 1 else DOUBLE
