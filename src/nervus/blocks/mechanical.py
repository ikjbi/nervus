"""Rotational mechanics and heat transfer, on the same network solver as the electrical components.

Rotational: the across value of a port is its angular velocity ω [rad/s], the through value the torque
[N·m] transmitted. Inertias are measured against the fixed frame (the reference), so a shaft needs no
reference block; a **Rotational Reference** fixes a port (a housing, a wall).

Thermal: the across value is the temperature [°C], the through value the heat flow [W]. Thermal masses store
heat against a fixed reference, like inertias.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from nervus.blocks.electrical import _positive
from nervus.blocks.registry import register
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array
from nervus.physical.network import GROUND, PhysicalBlock, Solution, Stamper

ROTATIONAL = "Rotational"
THERMAL = "Thermal"
FLANGES = (("a", "rotational"), ("b", "rotational"))


class _Rotational(PhysicalBlock):
    category = ROTATIONAL
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = FLANGES


@register
class RotationalReference(_Rotational):
    """A fixed point: the port linked to it does not rotate (ω = 0), e.g. a housing."""

    type_id = "rotational.reference"
    label = "Rotational Reference"
    PORTS = (("a", "rotational"),)
    REFERENCE = True


@register
class Inertia(_Rotational):
    """A rotating mass; its speed is a state:

    $$ J\\,\\frac{d\\omega}{dt} = \\sum \\tau, \\qquad \\omega(0) = \\omega_0 $$

    The sum of the torques acting on its port accelerates it.
    """

    type_id = "rotational.inertia"
    label = "Inertia"
    N_BRANCHES = 1
    PORTS = (("a", "rotational"),)
    PARAMS = (
        Param("J", 0.01, ParamKind.FLOAT, "Moment of inertia", "kg·m²"),
        Param("w0", 0.0, ParamKind.FLOAT, "Initial speed", "rad/s"),
    )

    def validate_params(self) -> None:
        _positive(self, "J")

    def physical_states(self) -> Array:
        return np.array([float(self.params["w0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], GROUND, float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([sol.through(branches[0]) / self.params["J"]])


@register
class RotationalSpring(_Rotational):
    """A torsion spring between two flanges; its torque is a state:

    $$ \\frac{d\\tau}{dt} = k\\,(\\omega_a - \\omega_b), \\qquad \\tau(0) = k\\,\\varphi_0 $$

    *phi0* is the initial twist (preload), e.g. a throttle return spring.
    """

    type_id = "rotational.spring"
    label = "Rotational Spring"
    PARAMS = (
        Param("k", 1.0, ParamKind.FLOAT, "Stiffness", "N·m/rad"),
        Param("phi0", 0.0, ParamKind.FLOAT, "Initial twist (preload)", "rad"),
    )

    def validate_params(self) -> None:
        _positive(self, "k")

    def physical_states(self) -> Array:
        return np.array([float(self.params["k"] * self.params["phi0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.flow(nodes[0], nodes[1], float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([self.params["k"] * (sol.across(nodes[0]) - sol.across(nodes[1]))])


@register
class RotationalDamper(_Rotational):
    """Viscous friction between two flanges: $\\tau = d\\,(\\omega_a - \\omega_b)$. Link ``b`` to a Rotational
    Reference for bearing friction against the housing."""

    type_id = "rotational.damper"
    label = "Rotational Damper"
    PARAMS = (Param("d", 0.01, ParamKind.FLOAT, "Damping", "N·m·s/rad"),)

    def validate_params(self) -> None:
        _positive(self, "d")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.conductance(nodes[0], nodes[1], float(self.params["d"]))


@register
class TorqueSource(_Rotational):
    """A torque on a flange, against the reference: the parameter *tau*, or the input signal when
    *controlled* (e.g. a load torque, or an engine's torque)."""

    type_id = "rotational.torque_source"
    label = "Torque Source"
    PORTS = (("a", "rotational"),)
    PARAMS = (
        Param("tau", 1.0, ParamKind.FLOAT, "Torque (when not controlled)", "N·m"),
        Param("controlled", False, ParamKind.BOOL, "The torque comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["torque"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        tau = u[0] if self.params["controlled"] else float(self.params["tau"])
        s.flow(GROUND, nodes[0], tau)


@register
class SpeedSource(_Rotational):
    """Drives a flange at a given speed, whatever the torque: the parameter *w* or the input signal."""

    type_id = "rotational.speed_source"
    label = "Speed Source"
    N_BRANCHES = 1
    PORTS = (("a", "rotational"),)
    PARAMS = (
        Param("w", 100.0, ParamKind.FLOAT, "Speed (when not controlled)", "rad/s"),
        Param("controlled", False, ParamKind.BOOL, "The speed comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["speed"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        w = u[0] if self.params["controlled"] else float(self.params["w"])
        s.effort(branches[0], nodes[0], GROUND, w)


@register
class IdealGear(_Rotational):
    """A gear without losses or backlash, ratio *n* = ω_a / ω_b:

    $$ \\omega_a = n\\,\\omega_b, \\qquad \\tau_b = n\\,\\tau_a $$

    For example a throttle's gear train (n = 20: the motor turns 20 times faster than the plate) or a gearbox.
    """

    type_id = "rotational.gear"
    label = "Ideal Gear"
    N_BRANCHES = 1
    PARAMS = (Param("n", 10.0, ParamKind.FLOAT, "Ratio ω_a / ω_b"),)

    def validate_params(self) -> None:
        _positive(self, "n")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        a, b, r, n = nodes[0], nodes[1], s.branch(branches[0]), float(self.params["n"])
        # w_a - n w_b = 0; the torque j enters at a, and n·j leaves at b.
        s.add(r, a, 1.0)
        s.add(r, b, -n)
        s.add(a, r, 1.0)
        s.add(b, r, -n)


@register
class SpeedSensor(_Rotational):
    """Measures the angular velocity of a flange (against the reference) as a signal, in rad/s."""

    type_id = "rotational.speed_sensor"
    label = "Speed Sensor"
    PORTS = (("a", "rotational"),)
    NUM_OUTPUTS = 1

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.across(nodes[0])]


@register
class AngleSensor(_Rotational):
    """Measures the angle of a flange (the integral of its speed) as a signal, in rad. *phi0*: the angle at
    the start."""

    type_id = "rotational.angle_sensor"
    label = "Angle Sensor"
    PORTS = (("a", "rotational"),)
    NUM_OUTPUTS = 1
    PARAMS = (Param("phi0", 0.0, ParamKind.FLOAT, "Angle at the start", "rad"),)

    def physical_states(self) -> Array:
        return np.array([float(self.params["phi0"])])

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([sol.across(nodes[0])])

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[0])]


@register
class TorqueSensor(_Rotational):
    """Measures the torque transmitted through it from ``a`` to ``b`` (a stiff shaft between the two)."""

    type_id = "rotational.torque_sensor"
    label = "Torque Sensor"
    NUM_OUTPUTS = 1
    N_BRANCHES = 1

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], nodes[1], 0.0)

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.through(branches[0])]


# ---------------------------------------------------------------------------- thermal


class _Thermal(PhysicalBlock):
    category = THERMAL
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (("a", "thermal"), ("b", "thermal"))


@register
class ThermalMass(_Thermal):
    """A body that stores heat; its temperature is a state:

    $$ m\\,c\\,\\frac{dT}{dt} = \\sum Q, \\qquad T(0) = T_0 $$

    For example the engine block, the coolant, or a power transistor with its heat sink.
    """

    type_id = "thermal.mass"
    label = "Thermal Mass"
    N_BRANCHES = 1
    PORTS = (("a", "thermal"),)
    PARAMS = (
        Param("C", 1000.0, ParamKind.FLOAT, "Heat capacity m·c", "J/K"),
        Param("T0", 20.0, ParamKind.FLOAT, "Initial temperature", "°C"),
    )

    def validate_params(self) -> None:
        _positive(self, "C")

    def physical_states(self) -> Array:
        return np.array([float(self.params["T0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], GROUND, float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([sol.through(branches[0]) / self.params["C"]])


@register
class ThermalResistance(_Thermal):
    """Heat conduction or convection between two ports: $Q = (T_a - T_b) / R$, with $R = 1/(h A)$ for convection
    (heat transfer coefficient *h*, area *A*)."""

    type_id = "thermal.resistance"
    label = "Thermal Resistance"
    PARAMS = (Param("R", 0.1, ParamKind.FLOAT, "Thermal resistance", "K/W"),)

    def validate_params(self) -> None:
        _positive(self, "R")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.conductance(nodes[0], nodes[1], 1.0 / self.params["R"])


@register
class HeatSource(_Thermal):
    """Heat flowing into a port: the parameter *Q* or the input signal (e.g. a heater, or the losses of a
    component computed elsewhere)."""

    type_id = "thermal.heat_source"
    label = "Heat Source"
    PORTS = (("a", "thermal"),)
    PARAMS = (
        Param("Q", 100.0, ParamKind.FLOAT, "Heat flow (when not controlled)", "W"),
        Param("controlled", False, ParamKind.BOOL, "The heat flow comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["heat flow"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        q = u[0] if self.params["controlled"] else float(self.params["Q"])
        s.flow(GROUND, nodes[0], q)


@register
class TemperatureSource(_Thermal):
    """Holds a port at a temperature, whatever the heat flow: the ambient air, a coolant at a fixed
    temperature. The parameter *T* or the input signal."""

    type_id = "thermal.temperature_source"
    label = "Temperature Source"
    N_BRANCHES = 1
    PORTS = (("a", "thermal"),)
    PARAMS = (
        Param("T", 20.0, ParamKind.FLOAT, "Temperature (when not controlled)", "°C"),
        Param("controlled", False, ParamKind.BOOL, "The temperature comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["temperature"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        temp = u[0] if self.params["controlled"] else float(self.params["T"])
        s.effort(branches[0], nodes[0], GROUND, temp)


@register
class TemperatureSensor(_Thermal):
    """Measures the temperature of a port as a signal, in °C."""

    type_id = "thermal.temperature_sensor"
    label = "Temperature Sensor"
    PORTS = (("a", "thermal"),)
    NUM_OUTPUTS = 1

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.across(nodes[0])]


@register
class HeatFlowSensor(_Thermal):
    """Measures the heat flowing through it from ``a`` to ``b`` as a signal, in W."""

    type_id = "thermal.heat_flow_sensor"
    label = "Heat Flow Sensor"
    NUM_OUTPUTS = 1
    N_BRANCHES = 1

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], nodes[1], 0.0)

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.through(branches[0])]
