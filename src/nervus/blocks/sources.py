"""Source blocks: signals that do not depend on any input."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import CONSTANT, CONTINUOUS
from nervus.core.types import Array, as_signal

CATEGORY = "Sources"
_ST_CONT = Param("sample_time", 0.0, ParamKind.SAMPLE_TIME, "0 = continuous, > 0 = discrete period", "s")


class _Source(Block):
    category = CATEGORY
    NUM_INPUTS = 0
    DEFAULT_SAMPLE_TIME = CONTINUOUS


@register
class Constant(_Source):
    """Outputs a constant value (scalar or vector).

    **Parameters**

    - *value*: the output value.
    """

    type_id = "sources.constant"
    label = "Constant"
    PARAMS = (
        Param("value", 1.0, ParamKind.ARRAY, "Output value"),
        Param("sample_time", math.inf, ParamKind.SAMPLE_TIME, "inf = constant", "s"),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [as_signal(self.params["value"]).size]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [as_signal(self.params["value"])]


@register
class Step(_Source):
    """Steps from *initial* to *final* at *time*.

    ![Step parameters](figures/step.png)

    $$ y(t) = \\begin{cases} \\text{initial} & \\text{if } t < \\text{time} \\\\
    \\text{final} & \\text{if } t \\ge \\text{time} \\end{cases} $$
    """

    type_id = "sources.step"
    label = "Step"
    PARAMS = (
        Param("time", 1.0, ParamKind.FLOAT, "Step time", "s"),
        Param("initial", 0.0, ParamKind.ARRAY, "Value before the step"),
        Param("final", 1.0, ParamKind.ARRAY, "Value after the step"),
        _ST_CONT,
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        a, b = as_signal(self.params["initial"]), as_signal(self.params["final"])
        return [np.broadcast_shapes(a.shape, b.shape)[0]]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        key = "final" if t >= self.params["time"] else "initial"
        return [np.broadcast_to(as_signal(self.params[key]), (self.out_widths[0],)).copy()]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        return [float(self.params["time"])]


@register
class Ramp(_Source):
    """A ramp starting at *start_time*:

    $$ y(t) = \\mathrm{initial} + \\mathrm{slope} \\cdot \\max(0,\\ t - t_\\mathrm{start}) $$

    ![Ramp parameters](figures/ramp.png)
    """

    type_id = "sources.ramp"
    label = "Ramp"
    PARAMS = (
        Param("slope", 1.0, ParamKind.FLOAT, "Slope", "1/s"),
        Param("start_time", 0.0, ParamKind.FLOAT, "Time the ramp starts", "s"),
        Param("initial", 0.0, ParamKind.FLOAT, "Output before the ramp starts"),
        _ST_CONT,
    )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        p = self.params
        return [as_signal(p["initial"] + p["slope"] * max(0.0, t - p["start_time"]))]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        return [float(self.params["start_time"])]


@register
class Sine(_Source):
    """Sine wave:

    $$ y(t) = A \\sin(\\omega t + \\varphi) + b $$

    with amplitude *A*, angular *frequency* ω, *phase* φ and *bias* b.

    ![Sine Wave parameters](figures/sine.png)

    *frequency* is in rad/s, as in Simulink. For a frequency *f* in Hz use ``2*pi*f``.
    """

    type_id = "sources.sine"
    label = "Sine Wave"
    PARAMS = (
        Param("amplitude", 1.0, ParamKind.FLOAT, "Amplitude"),
        Param("frequency", 1.0, ParamKind.FLOAT, "Angular frequency", "rad/s"),
        Param("phase", 0.0, ParamKind.FLOAT, "Phase", "rad"),
        Param("bias", 0.0, ParamKind.FLOAT, "Offset added to the wave"),
        _ST_CONT,
    )

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        p = self.params
        return [as_signal(p["amplitude"] * math.sin(p["frequency"] * t + p["phase"]) + p["bias"])]


@register
class Pulse(_Source):
    """Square pulse train. High (*amplitude*) for *duty* percent of each *period*, otherwise 0.
    The first pulse starts at *delay*.

    ![Pulse Generator parameters](figures/pulse.png)
    """

    type_id = "sources.pulse"
    label = "Pulse Generator"
    PARAMS = (
        Param("amplitude", 1.0, ParamKind.FLOAT, "Pulse height"),
        Param("period", 1.0, ParamKind.FLOAT, "Period", "s", min=0.0),
        Param("duty", 50.0, ParamKind.FLOAT, "Pulse width as % of the period", "%", min=0.0, max=100.0),
        Param("delay", 0.0, ParamKind.FLOAT, "Phase delay", "s", min=0.0),
        _ST_CONT,
    )

    def validate_params(self) -> None:
        if self.params["period"] <= 0:
            raise ParameterError("period must be > 0")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        p = self.params
        if t < p["delay"]:
            return [as_signal(0.0)]
        # Count whole periods with a tiny tolerance, so round-off exactly at a rising edge
        # (e.g. t = 3 * 0.1) does not land in the previous period.
        k = math.floor((t - p["delay"]) / p["period"] + 1e-12)
        phase = max(0.0, t - p["delay"] - k * p["period"])
        on = phase < p["duty"] / 100 * p["period"]
        return [as_signal(p["amplitude"] if on else 0.0)]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        p = self.params
        period, width = p["period"], p["duty"] / 100 * p["period"]
        pts: list[float] = []
        k = max(0, math.floor((t_start - p["delay"]) / period))
        while True:
            start = p["delay"] + k * period
            if start > t_final:
                break
            pts.extend((start, start + width))
            k += 1
        return pts


@register
class Clock(_Source):
    """Outputs the simulation time *t*."""

    type_id = "sources.clock"
    label = "Clock"
    PARAMS = ()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [as_signal(t)]


@register
class FromWorkspace(_Source):
    """Plays back recorded data.

    ![Linear interpolation vs hold](figures/from_workspace.png)

    Give either *time* and *data* arrays (data has one row per time point, one column per signal element), or a
    *csv_file* whose first column is time and remaining columns are data (a header row is skipped automatically).

    *interpolation*: ``linear`` interpolates between points; ``hold`` keeps the last value (zero-order hold).
    Outside the time range the first/last value is held.
    """

    type_id = "sources.from_workspace"
    label = "From Workspace"
    PARAMS = (
        Param("time", [0.0, 1.0], ParamKind.ARRAY, "Time points (increasing)", "s"),
        Param("data", [0.0, 1.0], ParamKind.ARRAY, "Values: one row per time point"),
        Param("csv_file", "", ParamKind.STR, "Optional CSV file (overrides time/data)"),
        Param("interpolation", "linear", ParamKind.CHOICE, "Interpolation", choices=("linear", "hold")),
        _ST_CONT,
    )

    def _table(self) -> tuple[Array, Array]:
        if self.params["csv_file"]:
            path = Path(self.params["csv_file"])
            if not path.exists():
                raise ParameterError(f"CSV file not found: {path}")
            raw = np.genfromtxt(path, delimiter=",", dtype=np.float64)
            if raw.ndim == 1:
                raw = raw[None, :]
            raw = raw[~np.isnan(raw).any(axis=1)]  # drop header / blank rows
            time, data = raw[:, 0], raw[:, 1:]
        else:
            time = np.asarray(self.params["time"], dtype=np.float64).ravel()
            data = np.asarray(self.params["data"], dtype=np.float64)
            if data.ndim <= 1:
                data = data.reshape(-1, 1)
        if time.size == 0 or time.size != data.shape[0]:
            raise ParameterError("time and data must have the same number of rows")
        if np.any(np.diff(time) < 0):
            raise ParameterError("time points must be increasing")
        return time, data

    def validate_params(self) -> None:
        if not self.params["csv_file"]:
            self._table()

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [self._table()[1].shape[1]]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        self._time, self._data = self._table()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        time, data = self._time, self._data
        if self.params["interpolation"] == "hold":
            k = int(np.searchsorted(time, t, side="right")) - 1
            return [data[max(k, 0)].copy()]
        return [np.array([np.interp(t, time, data[:, j]) for j in range(data.shape[1])])]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        if self.params["interpolation"] == "hold":
            return [float(v) for v in self._table()[0]]
        return []


@register
class Ground(_Source):
    """Outputs zero. Use it to connect an input you do not need, instead of leaving it unconnected."""

    type_id = "sources.ground"
    label = "Ground"
    DEFAULT_SAMPLE_TIME = CONSTANT
    PARAMS = ()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.zeros(1)]
