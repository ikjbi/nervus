"""Hydraulics on the same network solver: pressure [bar] is the across value, volume flow [L/min] the through.

A fuel system, a brake circuit or an oil circuit: pumps and pressure sources, orifices and valves, volumes
whose pressure rises as fluid is pushed in. Pressures are relative to the tank (0 bar).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from nervus.blocks.electrical import _positive
from nervus.blocks.registry import register
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array
from nervus.physical.network import GROUND, PhysicalBlock, Solution, Stamper

CATEGORY = "Hydraulic"
PIPE = (("a", "hydraulic"), ("b", "hydraulic"))


class _Hydraulic(PhysicalBlock):
    category = CATEGORY
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = PIPE


@register
class HydraulicReference(_Hydraulic):
    """The tank: the port linked to it is at 0 bar (ambient)."""

    type_id = "hydraulic.reference"
    label = "Tank"
    PORTS = (("a", "hydraulic"),)
    REFERENCE = True


@register
class FlowSource(_Hydraulic):
    """A pump with a given flow from ``a`` (suction) to ``b`` (outlet), whatever the pressure: the parameter
    *Q* or the input signal (an electric fuel pump driven by the ECU)."""

    type_id = "hydraulic.flow_source"
    label = "Flow Source (Pump)"
    PARAMS = (
        Param("Q", 1.0, ParamKind.FLOAT, "Flow (when not controlled)", "L/min"),
        Param("controlled", False, ParamKind.BOOL, "The flow comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["flow"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        q = u[0] if self.params["controlled"] else float(self.params["Q"])
        s.flow(nodes[0], nodes[1], q)  # through the pump from a to b: out of b into the circuit


@register
class PressureSource(_Hydraulic):
    """Holds port ``a`` at a pressure above the tank: the parameter *p* or the input signal."""

    type_id = "hydraulic.pressure_source"
    label = "Pressure Source"
    N_BRANCHES = 1
    PORTS = (("a", "hydraulic"),)
    PARAMS = (
        Param("p", 4.0, ParamKind.FLOAT, "Pressure (when not controlled)", "bar"),
        Param("controlled", False, ParamKind.BOOL, "The pressure comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["pressure"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], GROUND, u[0] if self.params["controlled"] else float(self.params["p"]))


@register
class Orifice(_Hydraulic):
    """A restriction with turbulent flow (an injector nozzle, a valve seat, a filter):

    $$ q = q_1\\,\\frac{\\Delta p}{\\sqrt{|\\Delta p| + p_{lam}}} $$

    *q_1* is the flow at 1 bar; at high pressure the flow grows with the square root of the pressure drop,
    near zero it becomes laminar (linear) below *p_lam*, so the equations stay smooth. A *controlled* orifice
    scales its opening with the input (0 closed .. 1 open), e.g. a valve.
    """

    type_id = "hydraulic.orifice"
    label = "Orifice"
    NONLINEAR = True
    PARAMS = (
        Param("q1", 1.0, ParamKind.FLOAT, "Flow at a pressure drop of 1 bar", "L/min"),
        Param("p_lam", 0.01, ParamKind.FLOAT, "Laminar pressure range", "bar"),
        Param("controlled", False, ParamKind.BOOL, "The opening (0..1) comes from the input signal"),
    )

    def validate_params(self) -> None:
        _positive(self, "q1", "p_lam")

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["opening"] if self.params["controlled"] else []

    def flow(self, dp: float, opening: float = 1.0) -> tuple[float, float]:
        """Flow and its derivative d q / d Δp."""
        q1, pl = self.params["q1"] * max(opening, 0.0), self.params["p_lam"]
        root = math.sqrt(abs(dp) + pl)
        return q1 * dp / root, q1 * (abs(dp) / 2 + pl) / (root**3)

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        opening = float(np.clip(u[0], 0.0, 1.0)) if self.params["controlled"] else 1.0
        dp = s.across_guess(nodes[0]) - s.across_guess(nodes[1])
        q, g = self.flow(dp, opening)
        g = max(g, 1e-9)
        s.conductance(nodes[0], nodes[1], g)
        s.flow(nodes[0], nodes[1], q - g * dp)


@register
class ReliefValve(_Hydraulic):
    """A pressure relief (or pressure regulator) valve: closed below the cracking pressure, then opening in
    proportion to the overpressure, like the regulator of a returnless fuel system:

    $$ q = k\\,\\max(\\Delta p - p_{crack},\\ 0) \\quad \\text{(smoothed over 0.05 bar)} $$
    """

    type_id = "hydraulic.relief_valve"
    label = "Relief Valve"
    NONLINEAR = True
    PARAMS = (
        Param("p_crack", 4.0, ParamKind.FLOAT, "Cracking pressure", "bar"),
        Param("k", 20.0, ParamKind.FLOAT, "Flow per bar above the cracking pressure", "L/min/bar"),
    )

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        dp = s.across_guess(nodes[0]) - s.across_guess(nodes[1])
        w = 0.05
        z = (dp - self.params["p_crack"]) / w
        soft = w * (math.log1p(math.exp(-abs(z))) + max(z, 0.0))  # smooth max(dp - p_crack, 0)
        k = self.params["k"]
        sigmoid = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))  # without overflow
        q, g = k * soft, k * sigmoid + 1e-9
        s.conductance(nodes[0], nodes[1], g)
        s.flow(nodes[0], nodes[1], q - g * dp)


@register
class HydraulicVolume(_Hydraulic):
    """A volume of fluid (a fuel rail, an accumulator, a hose): its pressure rises as fluid flows in,

    $$ \\frac{V}{\\beta}\\,\\frac{dp}{dt} = q_{in} $$

    with the bulk modulus β of the fluid (about 15 000 bar for petrol; less with air or a soft hose: the
    effective value). Its pressure is a state.
    """

    type_id = "hydraulic.volume"
    label = "Hydraulic Volume"
    N_BRANCHES = 1
    PORTS = (("a", "hydraulic"),)
    PARAMS = (
        Param("V", 0.05, ParamKind.FLOAT, "Volume", "L"),
        Param("beta", 15000.0, ParamKind.FLOAT, "Effective bulk modulus", "bar"),
        Param("p0", 0.0, ParamKind.FLOAT, "Initial pressure", "bar"),
    )

    def validate_params(self) -> None:
        _positive(self, "V", "beta")

    def physical_states(self) -> Array:
        return np.array([float(self.params["p0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], GROUND, float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        q_l_per_s = sol.through(branches[0]) / 60.0
        return np.array([q_l_per_s * self.params["beta"] / self.params["V"]])


@register
class PressureSensor(_Hydraulic):
    """Measures the pressure of a port (above the tank) as a signal, in bar."""

    type_id = "hydraulic.pressure_sensor"
    label = "Pressure Sensor"
    PORTS = (("a", "hydraulic"),)
    NUM_OUTPUTS = 1

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.across(nodes[0])]


@register
class FlowSensor(_Hydraulic):
    """Measures the flow through it from ``a`` to ``b`` as a signal, in L/min."""

    type_id = "hydraulic.flow_sensor"
    label = "Flow Sensor"
    NUM_OUTPUTS = 1
    N_BRANCHES = 1

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], nodes[1], 0.0)

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.through(branches[0])]
