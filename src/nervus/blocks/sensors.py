"""Sensor and actuator models: the imperfections of real hardware, and faults to test diagnostics against."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "Sensors & Actuators"
SENSOR_FAULTS = ("none", "stuck", "open_circuit", "short_to_supply", "drift")


def _noise(seed: int, k: int) -> float:
    """A reproducible standard-normal sample number ``k`` of the stream ``seed`` (same result every run)."""
    return float(np.random.default_rng([seed, k]).standard_normal())


@register
class SensorModel(Block):
    """A real sensor between the physical value and the ECU's input, sampled every *sample_time*:

    ![Noise, quantization and three injected faults](figures/sensor_model.png)

    $$ y = \\mathrm{quantize}(\\mathrm{clip}(g\\,u(t - d) + o + \\sigma\\,n,\\ y_{min},\\ y_{max})) $$

    with gain error *g* (1 = exact), offset *o*, white noise of standard deviation *σ* (reproducible: the same
    every run for the same *seed*), a delay *d* of whole samples (filtering, a slow bus), limits of the measuring
    range and the *resolution* of the A/D converter (0 = none).

    *fault* injects a failure from *fault_time*: ``stuck`` (the last good value), ``open_circuit`` (the lower
    rail, *y_min*), ``short_to_supply`` (the upper rail, *y_max*), ``drift`` (an offset growing by *drift_rate*
    per second). Use it to test the ECU's plausibility checks and diagnostic monitors.
    """

    type_id = "sensors.sensor"
    label = "Sensor Model"
    category = CATEGORY
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("gain", 1.0, ParamKind.FLOAT, "Gain (1 = exact)"),
        Param("offset", 0.0, ParamKind.FLOAT, "Offset error"),
        Param("noise", 0.0, ParamKind.FLOAT, "Noise standard deviation"),
        Param("delay", 0, ParamKind.INT, "Delay in samples", min=0),
        Param("resolution", 0.0, ParamKind.FLOAT, "Quantization step (0 = none)", min=0.0),
        Param("y_min", -math.inf, ParamKind.FLOAT, "Lower end of the measuring range"),
        Param("y_max", math.inf, ParamKind.FLOAT, "Upper end of the measuring range"),
        Param("fault", "none", ParamKind.CHOICE, "Injected fault", choices=SENSOR_FAULTS),
        Param("fault_time", 0.0, ParamKind.FLOAT, "When the fault starts", "s"),
        Param("drift_rate", 1.0, ParamKind.FLOAT, "Offset growth for the drift fault", "1/s"),
        Param("seed", 1, ParamKind.INT, "Noise stream (change it for an independent sensor)"),
        Param("sample_time", 0.01, ParamKind.SAMPLE_TIME, "Sample period", "s"),
    )

    def validate_params(self) -> None:
        if self.params["y_min"] > self.params["y_max"]:
            raise ParameterError("y_min must be <= y_max")
        if self.params["noise"] < 0:
            raise ParameterError("noise must be >= 0")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1]

    def initial_discrete_state(self) -> Array:
        # [sample counter, last output, delay line (oldest first)...]
        return np.zeros(2 + int(self.params["delay"]))

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([xd[1]])]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        p = self.params
        k = int(xd[0])
        line = list(xd[2:])
        value = float(np.ravel(u[0])[0])
        if line:  # the value from `delay` samples ago
            line.append(value)
            value = line.pop(0)
        y = p["gain"] * value + p["offset"]
        if p["noise"] > 0:
            y += p["noise"] * _noise(int(p["seed"]), k)
        faulty = p["fault"] != "none" and t >= p["fault_time"]
        if faulty and p["fault"] == "drift":
            y += p["drift_rate"] * (t - p["fault_time"])
        y = min(max(y, p["y_min"]), p["y_max"])
        if p["resolution"] > 0:
            y = round(y / p["resolution"]) * p["resolution"]
        if faulty and p["fault"] == "stuck":
            y = float(xd[1]) if k > 0 else y
        elif faulty and p["fault"] == "open_circuit":
            y = p["y_min"] if math.isfinite(p["y_min"]) else 0.0
        elif faulty and p["fault"] == "short_to_supply":
            y = p["y_max"] if math.isfinite(p["y_max"]) else 0.0
        return np.array([k + 1, y, *line], dtype=float)


@register
class ActuatorModel(Block):
    """A real actuator between the ECU's command and the physical effect, sampled every *sample_time*: a delay
    of whole samples (driver stage, bus), a rate limit (it cannot move faster than *rate* per second) and the
    limits of its range. *fault* ``stuck`` freezes it at its position from *fault_time* (a sticking valve)."""

    type_id = "sensors.actuator"
    label = "Actuator Model"
    category = CATEGORY
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("delay", 0, ParamKind.INT, "Delay in samples", min=0),
        Param("rate", math.inf, ParamKind.FLOAT, "Largest change per second", min=0.0),
        Param("y_min", -math.inf, ParamKind.FLOAT, "Lower limit"),
        Param("y_max", math.inf, ParamKind.FLOAT, "Upper limit"),
        Param("initial", 0.0, ParamKind.FLOAT, "Initial position"),
        Param("fault", "none", ParamKind.CHOICE, "Injected fault", choices=("none", "stuck")),
        Param("fault_time", 0.0, ParamKind.FLOAT, "When the fault starts", "s"),
        Param("sample_time", 0.01, ParamKind.SAMPLE_TIME, "Sample period", "s"),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1]

    def initial_discrete_state(self) -> Array:
        return np.array([float(self.params["initial"]), *([float(self.params["initial"])] * int(self.params["delay"]))])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([xd[0]])]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        p = self.params
        line = list(xd[1:])
        cmd = float(np.ravel(u[0])[0])
        if line:
            line.append(cmd)
            cmd = line.pop(0)
        pos = float(xd[0])
        if p["fault"] == "stuck" and t >= p["fault_time"]:
            return np.array([pos, *line])
        step = p["rate"] * self.period()
        new = pos + min(max(cmd - pos, -step), step) if math.isfinite(step) else cmd
        new = min(max(new, p["y_min"]), p["y_max"])
        return np.array([new, *line])
