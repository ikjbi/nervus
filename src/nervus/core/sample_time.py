"""Sample times: when a block's outputs and states are updated.

Values follow the Simulink convention:

* ``0``    – continuous (updated at every solver step)
* ``> 0``  – discrete with that period in seconds
* ``-1``   – inherited from the blocks driving the inputs
* ``inf``  – constant (computed once, at the start)

A discrete sample time can also be given as ``[period, offset]``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from nervus.core.errors import ParameterError


@dataclass(frozen=True)
class SampleTime:
    period: float
    offset: float = 0.0

    @classmethod
    def from_value(cls, value: float | Sequence[float] | SampleTime) -> SampleTime:
        if isinstance(value, SampleTime):
            return value
        if isinstance(value, Sequence) and not isinstance(value, str):
            if len(value) != 2:
                raise ParameterError("sample time must be a number or [period, offset]")
            period, offset = float(value[0]), float(value[1])
        else:
            period, offset = float(value), 0.0
        if period == -1 or period == 0 or math.isinf(period):
            if offset != 0:
                raise ParameterError("an offset is only allowed for discrete sample times")
            return cls(period if not math.isinf(period) else math.inf)
        if period < 0:
            raise ParameterError(f"invalid sample time {period}: use -1, 0, inf or a period > 0")
        if not 0 <= offset < period:
            raise ParameterError("sample time offset must satisfy 0 <= offset < period")
        return cls(period, offset)

    @property
    def is_continuous(self) -> bool:
        return self.period == 0

    @property
    def is_discrete(self) -> bool:
        return 0 < self.period < math.inf

    @property
    def is_inherited(self) -> bool:
        return self.period == -1

    @property
    def is_constant(self) -> bool:
        return math.isinf(self.period)

    def __str__(self) -> str:
        if self.is_continuous:
            return "continuous"
        if self.is_inherited:
            return "inherited"
        if self.is_constant:
            return "constant"
        return f"discrete({self.period:g}" + (f", offset {self.offset:g})" if self.offset else ")")


CONTINUOUS = SampleTime(0.0)
INHERITED = SampleTime(-1.0)
CONSTANT = SampleTime(math.inf)
