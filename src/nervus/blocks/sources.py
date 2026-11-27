"""Source blocks: signals that do not depend on any input."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind, output_type_param
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
        output_type_param("double"),
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

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        w = (out_widths[0],)
        self._before = np.broadcast_to(as_signal(self.params["initial"]), w).copy()
        self._after = np.broadcast_to(as_signal(self.params["final"]), w).copy()
        self._at = float(self.params["time"])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [(self._after if t >= self._at else self._before).copy()]

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
class RepeatingSequence(_Source):
    """Repeats a sequence of points: a sawtooth, a triangle or a drive pattern.

    The output interpolates linearly between the points (*times*, *values*) and starts again after the last time
    point, which is the period. Two points at the same time make a jump. As Simulink's Repeating Sequence block.
    """

    type_id = "sources.repeating_sequence"
    label = "Repeating Sequence"
    PARAMS = (
        Param("times", [0.0, 2.0], ParamKind.ARRAY, "Times of the points; the last one is the period", "s"),
        Param("values", [0.0, 2.0], ParamKind.ARRAY, "Values at those times"),
        _ST_CONT,
    )

    def validate_params(self) -> None:
        times = np.asarray(self.params["times"], dtype=np.float64).ravel()
        values = np.asarray(self.params["values"], dtype=np.float64).ravel()
        if times.size < 2 or times.size != values.size:
            raise ParameterError("times and values need the same number of points (at least two)")
        if np.any(np.diff(times) < 0) or times[-1] <= times[0]:
            raise ParameterError("times must increase (equal times make a jump)")
        self._times, self._values = times, values

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        t0, period = self._times[0], self._times[-1] - self._times[0]
        tau = t0 + (t - t0) % period
        k = int(np.searchsorted(self._times, tau, side="right"))  # at a jump: the value after it
        if k >= self._times.size:
            return [as_signal(self._values[-1])]
        if k == 0:
            return [as_signal(self._values[0])]
        ta, tb = self._times[k - 1], self._times[k]
        va, vb = self._values[k - 1], self._values[k]
        return [as_signal(va + (vb - va) * (tau - ta) / (tb - ta))]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        t0, period = self._times[0], self._times[-1] - self._times[0]
        pts: list[float] = []
        k = max(0, math.floor((t_start - t0) / period))
        while t0 + k * period <= t_final and len(pts) < 100000:
            pts += [float(t0 + k * period + x - t0) for x in self._times]
            k += 1
        return [p for p in pts if t_start <= p <= t_final]


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


@register
class DriveCycle(_Source):
    """A standard drive cycle as a speed profile (the target for a driver model):

    - ``wltc3b``: WLTC class 3b (WLTP, the European type approval since 2017), 1800 s, 23.3 km, up to 131 km/h;
    - ``ftp75``: FTP-75, the US city cycle, 1874 s, 17.8 km;
    - ``ece15``: ECE-15, the urban part of the old NEDC, 195 s, 1 km;
    - ``csv_file``: your own: two columns, time [s] and speed [km/h].

    ![The bundled cycles](figures/drive_cycle_block.png)

    Output 0 is the speed (km/h or m/s, *unit*), output 1 the acceleration [m/s²] (the slope of the profile,
    useful as a feed-forward for a driver model). After the end of the cycle the speed stays 0. The WLTC and
    FTP-75 tables are the official second-by-second values.
    """

    type_id = "sources.drive_cycle"
    label = "Drive Cycle"
    NUM_OUTPUTS = 2
    PARAMS = (
        Param("cycle", "wltc3b", ParamKind.CHOICE, "Cycle", choices=("wltc3b", "ftp75", "ece15", "csv_file")),
        Param("csv_file", "", ParamKind.STR, "CSV file (time s, speed km/h) for cycle = csv_file"),
        Param("unit", "km/h", ParamKind.CHOICE, "Speed unit of the output", choices=("km/h", "m/s")),
        _ST_CONT,
    )

    def _profile(self) -> tuple[Array, Array]:
        from nervus.cycles import cycle

        if self.params["cycle"] == "csv_file":
            path = str(self.params["csv_file"]).strip()
            if not path:
                raise ParameterError("choose a CSV file (time [s], speed [km/h])")
            data = np.loadtxt(path, delimiter=",", comments="#")
            return data[:, 0], data[:, 1]
        return cycle(str(self.params["cycle"]))

    def validate_params(self) -> None:
        if self.params["cycle"] == "csv_file" and not str(self.params["csv_file"]).strip():
            return  # chosen in the editor next
        self._profile()

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1, 1]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        times, v = self._profile()
        speed = float(np.interp(t, times, v, right=0.0)) / 3.6
        k = int(np.clip(np.searchsorted(times, t, side="right") - 1, 0, times.size - 2))
        accel = (v[k + 1] - v[k]) / 3.6 / (times[k + 1] - times[k]) if t <= times[-1] else 0.0
        scale = 3.6 if self.params["unit"] == "km/h" else 1.0
        return [np.array([speed * scale]), np.array([accel])]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        times, _ = self._profile()
        return [float(x) for x in times if t_start < x <= t_final] if times.size < 400 else []
