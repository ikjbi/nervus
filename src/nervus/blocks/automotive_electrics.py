"""Automotive electrical components: solenoids and injectors, relays, glow plugs and the alternator."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from nervus.blocks.electrical import _positive
from nervus.blocks.registry import register
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array
from nervus.physical.network import GROUND, PhysicalBlock, Solution, Stamper

CATEGORY = "Automotive Electrics"
COIL = (("p", "electrical"), ("n", "electrical"))


def _armature(i: float, x: float, pull: float, drop: float) -> float:
    """Where the armature moves to: pulled in above the pull-in current, released below the drop-out current,
    and in between it stays where it is (hysteresis)."""
    if abs(i) >= pull:
        return 1.0
    if abs(i) <= drop:
        return 0.0
    return 1.0 if x > 0.5 else 0.0


class _Coil(PhysicalBlock):
    """A coil (R, L) with an armature that pulls in and drops out. States: coil current, armature position."""

    category = CATEGORY
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = COIL
    COIL_PARAMS = (
        Param("R", 12.0, ParamKind.FLOAT, "Coil resistance", "Ω"),
        Param("L", 0.01, ParamKind.FLOAT, "Coil inductance", "H"),
        Param("I_pull", 0.6, ParamKind.FLOAT, "Pull-in current", "A"),
        Param("I_drop", 0.3, ParamKind.FLOAT, "Drop-out current", "A"),
        Param("tau", 0.5e-3, ParamKind.FLOAT, "Armature travel time constant", "s"),
    )

    def validate_params(self) -> None:
        _positive(self, "R", "L", "tau")
        if not 0 <= self.params["I_drop"] < self.params["I_pull"]:
            raise ParameterError("I_drop must be below I_pull")

    def physical_states(self) -> Array:
        return np.zeros(2)

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.flow(nodes[0], nodes[1], float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        p = self.params
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        target = _armature(float(x[0]), float(x[1]), p["I_pull"], p["I_drop"])
        return np.array([(v - p["R"] * x[0]) / p["L"], (target - x[1]) / p["tau"]])


@register
class Solenoid(_Coil):
    """A solenoid (an actuator coil with an armature): the coil current builds up with τ = L/R; above the
    pull-in current the armature moves in, below the drop-out current it is released:

    $$ L\\,\\frac{di}{dt} = v - R\\,i, \\qquad \\tau\\,\\frac{dx}{dt} = x_{target} - x $$

    Output: the armature position x (0 out, 1 in). For example a canister purge valve or a starter solenoid.
    """

    type_id = "automotive.solenoid"
    label = "Solenoid"
    NUM_OUTPUTS = 1
    PARAMS = _Coil.COIL_PARAMS

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[1])]


@register
class FuelInjector(_Coil):
    """A solenoid fuel injector: the needle opens when the coil current passes the pull-in current, so the
    injector opens a little after the ECU switches it on (the *opening delay*, which the ECU compensates with
    the battery voltage) and closes after the current has decayed. Outputs: needle lift (0..1) and fuel flow
    (lift × static flow, g/s). Typical port injector: R = 12 Ω, L = 10 mH, 3.5 g/s."""

    type_id = "automotive.injector"
    label = "Fuel Injector"
    NUM_OUTPUTS = 2
    PARAMS = (*_Coil.COIL_PARAMS, Param("static_flow", 3.5, ParamKind.FLOAT, "Flow when fully open", "g/s"))

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[1]), float(x[1]) * self.params["static_flow"]]


@register
class Relay(_Coil):
    """A relay: a coil (``p``, ``n``) and a normally-open contact (``a``, ``b``) that closes while the armature
    is pulled in. Output: 1 while the contact is closed. For example the main relay, the fuel pump relay or a
    starter relay."""

    type_id = "automotive.relay"
    label = "Relay"
    NUM_OUTPUTS = 1
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (*COIL, ("a", "electrical"), ("b", "electrical"))
    PARAMS = (
        Param("R", 80.0, ParamKind.FLOAT, "Coil resistance", "Ω"),
        Param("L", 0.1, ParamKind.FLOAT, "Coil inductance", "H"),
        Param("I_pull", 0.08, ParamKind.FLOAT, "Pull-in current", "A"),
        Param("I_drop", 0.03, ParamKind.FLOAT, "Drop-out current", "A"),
        Param("tau", 2e-3, ParamKind.FLOAT, "Armature travel time constant", "s"),
        Param("R_contact", 5e-3, ParamKind.FLOAT, "Contact resistance when closed", "Ω"),
    )

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.flow(nodes[0], nodes[1], float(x[0]))
        closed = x[1] > 0.5
        s.conductance(nodes[2], nodes[3], 1.0 / self.params["R_contact"] if closed else 1e-9)

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [1.0 if x[1] > 0.5 else 0.0]


@register
class GlowPlug(PhysicalBlock):
    """A diesel glow plug: a heater whose resistance rises with its temperature, which limits its current as it
    heats up (self-regulating):

    $$ R(T) = R_0\\,(1 + \\alpha\\,(T - 20)), \\qquad C\\,\\frac{dT}{dt} = \\frac{v^2}{R(T)} - \\frac{T - T_{case}}{R_{th}} $$

    Ports: ``p``, ``n`` (electrical) and ``case`` (thermal: the cylinder head). Output: the tip temperature.
    """

    type_id = "automotive.glow_plug"
    label = "Glow Plug"
    category = CATEGORY
    NUM_OUTPUTS = 1
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (*COIL, ("case", "thermal"))
    PARAMS = (
        Param("R0", 0.5, ParamKind.FLOAT, "Resistance at 20 °C", "Ω"),
        Param("alpha", 0.006, ParamKind.FLOAT, "Temperature coefficient", "1/K"),
        Param("C", 3.0, ParamKind.FLOAT, "Heat capacity of the tip", "J/K"),
        Param("R_th", 25.0, ParamKind.FLOAT, "Thermal resistance to the cylinder head", "K/W"),
        Param("T0", 20.0, ParamKind.FLOAT, "Initial temperature", "°C"),
    )

    def validate_params(self) -> None:
        _positive(self, "R0", "C", "R_th")

    def physical_states(self) -> Array:
        return np.array([float(self.params["T0"])])

    def _r(self, temp: float) -> float:
        return max(1e-3, self.params["R0"] * (1 + self.params["alpha"] * (temp - 20.0)))

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        temp = float(x[0])
        s.conductance(nodes[0], nodes[1], 1.0 / self._r(temp))
        g = 1.0 / self.params["R_th"]  # heat from the tip (at the state temperature) into the case
        s.conductance(nodes[2], GROUND, g)
        s.flow(GROUND, nodes[2], g * temp)

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        temp = float(x[0])
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        loss = (temp - sol.across(nodes[2])) / self.params["R_th"]
        return np.array([(v * v / self._r(temp) - loss) / self.params["C"]])

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[0])]


@register
class Alternator(PhysicalBlock):
    """An alternator with its voltage regulator, driven by the engine through a belt:

    $$ \\tau_r\\,\\frac{dI}{dt} = \\min(\\max(K\\,(V_{set} - v),\\ 0),\\ I_{max}(n)) - I $$

    $$ \\tau_{shaft} = \\frac{v\\,I}{\\eta\\,\\omega} $$

    It delivers current *I* out of ``p`` to hold *V_set*; at low speed it can deliver less (zero below the
    cut-in speed, *I_rated* from *rated_rpm*). The current it delivers loads the engine: the torque on
    ``shaft`` (the crankshaft; *ratio* is the pulley ratio) is the electrical power divided by the efficiency.
    Output: the current I.
    """

    type_id = "automotive.alternator"
    label = "Alternator"
    category = CATEGORY
    NONLINEAR = True
    NUM_OUTPUTS = 1
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (*COIL, ("shaft", "rotational"))
    PARAMS = (
        Param("V_set", 14.2, ParamKind.FLOAT, "Regulated voltage", "V"),
        Param("I_rated", 120.0, ParamKind.FLOAT, "Maximum current at rated speed", "A"),
        Param("cut_in_rpm", 1000.0, ParamKind.FLOAT, "Alternator speed where it starts to deliver", "rpm"),
        Param("rated_rpm", 6000.0, ParamKind.FLOAT, "Alternator speed for the full current", "rpm"),
        Param("ratio", 2.5, ParamKind.FLOAT, "Pulley ratio (alternator speed / engine speed)"),
        Param("K", 50.0, ParamKind.FLOAT, "Regulator gain", "A/V"),
        Param("tau_r", 0.05, ParamKind.FLOAT, "Regulator and field time constant", "s"),
        Param("efficiency", 0.6, ParamKind.FLOAT, "Efficiency"),
    )

    def validate_params(self) -> None:
        _positive(self, "V_set", "I_rated", "ratio", "K", "tau_r", "efficiency")
        if not self.params["rated_rpm"] > self.params["cut_in_rpm"]:
            raise ParameterError("rated_rpm must be above cut_in_rpm")

    def physical_states(self) -> Array:
        return np.zeros(1)

    def _i_max(self, w_engine: float) -> float:
        p = self.params
        rpm = abs(w_engine) * p["ratio"] * 60 / (2 * np.pi)
        return p["I_rated"] * float(np.clip((rpm - p["cut_in_rpm"]) / (p["rated_rpm"] - p["cut_in_rpm"]), 0, 1))

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        i = float(x[0])
        s.flow(nodes[1], nodes[0], i)  # out of p into the vehicle's electrical system
        v = s.across_guess(nodes[0]) - s.across_guess(nodes[1])
        w = s.across_guess(nodes[2])
        if abs(w) > 1.0:  # the electrical power, taken from the crankshaft
            s.flow(nodes[2], GROUND, v * i / (self.params["efficiency"] * w))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        p = self.params
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        target = min(max(p["K"] * (p["V_set"] - v), 0.0), self._i_max(sol.across(nodes[2])))
        return np.array([(target - x[0]) / p["tau_r"]])

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[0])]
