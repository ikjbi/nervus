"""Electrical components: circuits are drawn with physical links and solved by nodal analysis.

Every circuit needs an **Electrical Reference** (ground, 0 V). Voltages are in V, currents in A; the current of
a component is counted from its ``p`` (+) port through the component to its ``n`` (−) port.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from nervus.blocks.registry import register
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array
from nervus.physical.network import GROUND, PhysicalBlock, Solution, Stamper

CATEGORY = "Electrical"
TWO_PINS = (("p", "electrical"), ("n", "electrical"))


class _Electrical(PhysicalBlock):
    category = CATEGORY
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = TWO_PINS


def _positive(block: PhysicalBlock, *names: str) -> None:
    for n in names:
        if not block.params[n] > 0:
            raise ParameterError(f"{n} must be > 0")


@register
class ElectricalReference(_Electrical):
    """Ground: the node it is linked to is at 0 V. Every circuit needs one."""

    type_id = "electrical.reference"
    label = "Electrical Reference"
    PORTS = (("p", "electrical"),)
    REFERENCE = True


@register
class Resistor(_Electrical):
    """An ideal resistor (Ohm's law):

    $$ v_p - v_n = R\\,i $$
    """

    type_id = "electrical.resistor"
    label = "Resistor"
    PARAMS = (Param("R", 1.0, ParamKind.FLOAT, "Resistance", "Ω"),)

    def validate_params(self) -> None:
        _positive(self, "R")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.conductance(nodes[0], nodes[1], 1.0 / self.params["R"])


@register
class Capacitor(_Electrical):
    """An ideal capacitor; its voltage is a state:

    $$ C\\,\\frac{dv}{dt} = i, \\qquad v = v_p - v_n,\\quad v(0) = v_0 $$
    """

    type_id = "electrical.capacitor"
    label = "Capacitor"
    N_BRANCHES = 1
    PARAMS = (
        Param("C", 1e-6, ParamKind.FLOAT, "Capacitance", "F"),
        Param("v0", 0.0, ParamKind.FLOAT, "Initial voltage", "V"),
    )

    def validate_params(self) -> None:
        _positive(self, "C")

    def physical_states(self) -> Array:
        return np.array([float(self.params["v0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], nodes[1], float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([sol.through(branches[0]) / self.params["C"]])


@register
class Inductor(_Electrical):
    """An ideal inductor; its current is a state:

    $$ L\\,\\frac{di}{dt} = v_p - v_n, \\qquad i(0) = i_0 $$
    """

    type_id = "electrical.inductor"
    label = "Inductor"
    PARAMS = (
        Param("L", 1e-3, ParamKind.FLOAT, "Inductance", "H"),
        Param("i0", 0.0, ParamKind.FLOAT, "Initial current", "A"),
    )

    def validate_params(self) -> None:
        _positive(self, "L")

    def physical_states(self) -> Array:
        return np.array([float(self.params["i0"])])

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.flow(nodes[0], nodes[1], float(x[0]))

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([(sol.across(nodes[0]) - sol.across(nodes[1])) / self.params["L"]])


@register
class VoltageSource(_Electrical):
    """An ideal voltage source: $v_p - v_n = V$. With *controlled* on, the voltage is the input signal (e.g. from
    a controller); otherwise it is the parameter *V* (a battery, a supply)."""

    type_id = "electrical.voltage_source"
    label = "Voltage Source"
    N_BRANCHES = 1
    PARAMS = (
        Param("V", 12.0, ParamKind.FLOAT, "Voltage (when not controlled)", "V"),
        Param("controlled", False, ParamKind.BOOL, "The voltage comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["voltage"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        v = u[0] if self.params["controlled"] else float(self.params["V"])
        s.effort(branches[0], nodes[0], nodes[1], v)


@register
class CurrentSource(_Electrical):
    """An ideal current source: the current *I* flows out of its ``p`` port into the circuit (and back in at
    ``n``). With *controlled* on, the current is the input signal."""

    type_id = "electrical.current_source"
    label = "Current Source"
    PARAMS = (
        Param("I", 1.0, ParamKind.FLOAT, "Current (when not controlled)", "A"),
        Param("controlled", False, ParamKind.BOOL, "The current comes from the input signal"),
    )

    def num_inputs(self) -> int:
        return 1 if self.params["controlled"] else 0

    def input_names(self) -> list[str]:
        return ["current"] if self.params["controlled"] else []

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        i = u[0] if self.params["controlled"] else float(self.params["I"])
        s.flow(nodes[1], nodes[0], i)  # inside the source from n to p: out of p into the circuit


@register
class VoltageSensor(_Electrical):
    """Measures the voltage $v_p - v_n$ as a signal (ideal: no current flows into it)."""

    type_id = "electrical.voltage_sensor"
    label = "Voltage Sensor"
    NUM_OUTPUTS = 1

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.across(nodes[0]) - sol.across(nodes[1])]


@register
class CurrentSensor(_Electrical):
    """Measures the current flowing through it from ``p`` to ``n`` as a signal. Put it in series, like an
    ammeter (ideal: no voltage across it)."""

    type_id = "electrical.current_sensor"
    label = "Current Sensor"
    NUM_OUTPUTS = 1
    N_BRANCHES = 1

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        s.effort(branches[0], nodes[0], nodes[1], 0.0)

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [sol.through(branches[0])]


@register
class Switch(_Electrical):
    """A switch controlled by a signal: closed (resistance *R_on*) while the input is ≥ 0.5, open (conductance
    *G_off*) otherwise. Use it for a relay, a transistor driven as a switch, or a fuse."""

    type_id = "electrical.switch"
    label = "Switch"
    PARAMS = (
        Param("R_on", 1e-3, ParamKind.FLOAT, "Resistance when closed", "Ω"),
        Param("G_off", 1e-8, ParamKind.FLOAT, "Conductance when open", "S"),
    )

    def num_inputs(self) -> int:
        return 1

    def input_names(self) -> list[str]:
        return ["closed"]

    def validate_params(self) -> None:
        _positive(self, "R_on", "G_off")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        g = 1.0 / self.params["R_on"] if u[0] >= 0.5 else float(self.params["G_off"])
        s.conductance(nodes[0], nodes[1], g)

    def mode_events(self, sol: Solution, nodes: list[int], branches: list[int], u: Sequence[float]) -> list[float]:
        return [u[0] - 0.5]


@register
class Diode(_Electrical):
    """A piecewise-linear diode: conducts from ``p`` (anode) to ``n`` (cathode) when the voltage exceeds the
    forward voltage *Vf*:

    $$ i = \\begin{cases} (v - V_f) / R_{on} & v > V_f \\\\ G_{off}\\, v & \\text{otherwise} \\end{cases} $$

    For example the freewheeling diode across a relay coil or a motor.
    """

    type_id = "electrical.diode"
    label = "Ideal Diode"
    PARAMS = (
        Param("Vf", 0.6, ParamKind.FLOAT, "Forward voltage", "V"),
        Param("R_on", 0.01, ParamKind.FLOAT, "Resistance when conducting", "Ω"),
        Param("G_off", 1e-8, ParamKind.FLOAT, "Conductance when blocking", "S"),
    )

    def __init__(self, name: str = "", **params: object) -> None:
        super().__init__(name, **params)
        self._on = False  # the conduction mode found at the last solve (a starting guess for the next)

    def validate_params(self) -> None:
        _positive(self, "R_on", "G_off")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        if self._on:
            g = 1.0 / self.params["R_on"]
            s.conductance(nodes[0], nodes[1], g)
            s.flow(nodes[1], nodes[0], g * self.params["Vf"])  # i = g (v - Vf)
        else:
            s.conductance(nodes[0], nodes[1], float(self.params["G_off"]))

    def update_mode(self, sol: Solution, nodes: list[int], branches: list[int]) -> bool:
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        on = v > self.params["Vf"]
        changed = on != self._on
        self._on = on
        return changed

    def mode_events(self, sol: Solution, nodes: list[int], branches: list[int], u: Sequence[float]) -> list[float]:
        return [sol.across(nodes[0]) - sol.across(nodes[1]) - self.params["Vf"]]


@register
class Battery(_Electrical):
    """A battery: open-circuit voltage from its state of charge, and an internal resistance:

    $$ v_p - v_n = \\mathrm{OCV}(SOC) - R_i\\, i_{out}, \\qquad \\frac{dSOC}{dt} = -\\frac{i_{out}}{3600\\, Q} $$

    *Q* is the capacity in Ah, *i_out* the current delivered from ``p``. The OCV is a table over SOC (0..1); the
    default is a 12 V lead-acid battery. Output: the state of charge (0..1).
    """

    type_id = "electrical.battery"
    label = "Battery"
    NUM_OUTPUTS = 1
    PARAMS = (
        Param("capacity", 60.0, ParamKind.FLOAT, "Capacity Q", "Ah"),
        Param("R_internal", 0.01, ParamKind.FLOAT, "Internal resistance", "Ω"),
        Param("soc0", 0.9, ParamKind.FLOAT, "Initial state of charge (0..1)"),
        Param("soc_breakpoints", [0.0, 0.2, 0.5, 0.8, 1.0], ParamKind.ARRAY, "SOC points of the OCV table"),
        Param("ocv", [11.6, 11.9, 12.2, 12.5, 12.8], ParamKind.ARRAY, "Open-circuit voltage at each SOC point", "V"),
    )

    def validate_params(self) -> None:
        _positive(self, "capacity", "R_internal")
        bp, ocv = np.ravel(self.params["soc_breakpoints"]), np.ravel(self.params["ocv"])
        if bp.size != ocv.size or bp.size < 2 or np.any(np.diff(bp) <= 0):
            raise ParameterError("soc_breakpoints must increase, and ocv needs one value per breakpoint")

    def physical_states(self) -> Array:
        return np.array([float(self.params["soc0"])])

    def _ocv(self, soc: float) -> float:
        return float(np.interp(soc, np.ravel(self.params["soc_breakpoints"]), np.ravel(self.params["ocv"])))

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        g = 1.0 / self.params["R_internal"]
        s.conductance(nodes[0], nodes[1], g)
        s.flow(nodes[1], nodes[0], g * self._ocv(float(x[0])))  # Norton equivalent of OCV in series with R

    def _current(self, sol: Solution, nodes: list[int], x: Array) -> float:
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        return (self._ocv(float(x[0])) - v) / self.params["R_internal"]

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        return np.array([-self._current(sol, nodes, x) / (3600.0 * self.params["capacity"])])

    def measure(
        self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]
    ) -> list[float]:
        return [float(x[0])]


@register
class HBridge(_Electrical):
    """An H-bridge driving a motor with PWM, as an average model: the output voltage is the duty cycle times
    the supply voltage, and the supply delivers the same power (no losses):

    $$ v_a - v_b = d\\,(v_+ - v_-), \\qquad i_{supply} = d\\, i_{out}, \\qquad -1 \\le d \\le 1 $$

    A negative duty cycle reverses the motor. Ports: ``supply_p``, ``supply_n`` (the battery) and ``a``, ``b``
    (the motor). Input: the duty cycle (limited to ±1).
    """

    type_id = "electrical.h_bridge"
    label = "H-Bridge (PWM)"
    N_BRANCHES = 1
    PORTS = (("supply_p", "electrical"), ("supply_n", "electrical"), ("a", "electrical"), ("b", "electrical"))

    def num_inputs(self) -> int:
        return 1

    def input_names(self) -> list[str]:
        return ["duty"]

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        d = float(np.clip(u[0], -1.0, 1.0))
        p, n, a, b = nodes
        r = s.branch(branches[0])
        # Output branch: v_a - v_b - d (v_p - v_n) = 0, with its current j from a to b through the bridge.
        s.add(r, a, 1.0)
        s.add(r, b, -1.0)
        s.add(r, p, -d)
        s.add(r, n, d)
        s.add(a, r, 1.0)
        s.add(b, r, -1.0)
        # Supply current from p to n through the bridge: -d·j (power balance).
        s.add(p, r, -d)
        s.add(n, r, d)


@register
class DCMotor(PhysicalBlock):
    """A permanent-magnet DC motor: electrical port ``p``/``n``, mechanical port ``shaft``:

    $$ L\\,\\frac{di}{dt} = v_p - v_n - R\\,i - k\\,\\omega, \\qquad \\tau = k\\,i $$

    *k* is both the torque constant (N·m/A) and the back-EMF constant (V·s/rad). The torque acts on the shaft
    against the reference (the motor housing); add an Inertia for the rotor and a Rotational Damper for its
    friction. The armature current is a state.
    """

    type_id = "electrical.dc_motor"
    label = "DC Motor"
    category = CATEGORY
    PORTS = (("p", "electrical"), ("n", "electrical"), ("shaft", "rotational"))
    PARAMS = (
        Param("R", 1.0, ParamKind.FLOAT, "Armature resistance", "Ω"),
        Param("L", 1e-3, ParamKind.FLOAT, "Armature inductance", "H"),
        Param("k", 0.05, ParamKind.FLOAT, "Torque and back-EMF constant", "N·m/A"),
    )

    def validate_params(self) -> None:
        _positive(self, "R", "L", "k")

    def physical_states(self) -> Array:
        return np.zeros(1)

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        i = float(x[0])
        s.flow(nodes[0], nodes[1], i)  # the armature current through the motor
        s.flow(GROUND, nodes[2], self.params["k"] * i)  # its torque on the shaft

    def rates(self, sol: Solution, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> Array:
        p = self.params
        v = sol.across(nodes[0]) - sol.across(nodes[1])
        w = sol.across(nodes[2])
        return np.array([(v - p["R"] * x[0] - p["k"] * w) / p["L"]])


@register
class VCVS(_Electrical):
    """A voltage-controlled voltage source (SPICE element E): $v_p - v_n = gain\\,(v_{cp} - v_{cn})$. No current
    flows into the control ports."""

    type_id = "electrical.vcvs"
    label = "Voltage-Controlled Voltage Source"
    N_BRANCHES = 1
    PORTS = (("p", "electrical"), ("n", "electrical"), ("cp", "electrical"), ("cn", "electrical"))
    PARAMS = (Param("gain", 1.0, ParamKind.FLOAT, "Voltage gain"),)

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        p, n, cp, cn = nodes
        g, r = float(self.params["gain"]), s.branch(branches[0])
        s.add(r, p, 1.0)
        s.add(r, n, -1.0)
        s.add(r, cp, -g)
        s.add(r, cn, g)
        s.add(p, r, 1.0)
        s.add(n, r, -1.0)


@register
class VCCS(_Electrical):
    """A voltage-controlled current source (SPICE element G): the current $gm\\,(v_{cp} - v_{cn})$ flows from
    ``p`` through the source to ``n``."""

    type_id = "electrical.vccs"
    label = "Voltage-Controlled Current Source"
    PORTS = (("p", "electrical"), ("n", "electrical"), ("cp", "electrical"), ("cn", "electrical"))
    PARAMS = (Param("gm", 1e-3, ParamKind.FLOAT, "Transconductance", "S"),)

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        p, n, cp, cn = nodes
        gm = float(self.params["gm"])
        s.add(p, cp, gm)
        s.add(p, cn, -gm)
        s.add(n, cp, -gm)
        s.add(n, cn, gm)
