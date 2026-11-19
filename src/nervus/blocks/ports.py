"""Ports and subsystems: build hierarchical models.

A :class:`Subsystem` contains its own diagram. Its input and output ports are the :class:`Inport` and
:class:`Outport` blocks inside it, numbered by their *port* parameter. At the top level of a model, Inport
blocks are external inputs (with a default *value* for simulation) and Outport blocks are external outputs.
Those top-level ports become the input and output structs of generated C code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.diagram import Diagram
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import CONTINUOUS
from nervus.core.types import Array, as_signal

CATEGORY = "Ports & Subsystems"


@register
class Inport(Block):
    """An input port.

    Inside a subsystem it is the subsystem's input number *port*. At the top level of a model it is an
    external input: during simulation it outputs *value*; in generated C code it is a field of the inputs
    struct.
    """

    type_id = "ports.inport"
    label = "In"
    category = CATEGORY
    NUM_INPUTS = 0
    DEFAULT_SAMPLE_TIME = CONTINUOUS
    PARAMS = (
        Param("port", 1, ParamKind.INT, "Port number (1, 2, ...)", min=1),
        Param("value", 0.0, ParamKind.ARRAY, "Value used when simulating the model on its own (top level)"),
        Param("sample_time", -1.0, ParamKind.SAMPLE_TIME, "Sample time of the external input (-1 = inherit)", "s"),
    )

    def __init__(self, name: str = "", **params: Any) -> None:
        super().__init__(name, **params)
        self.signal: Any = None
        """A :class:`~nervus.core.signals.Signal` driving this (top-level) input during a simulation; set by
        ``simulate(..., inputs=...)``. When ``None`` the block outputs *value*."""

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        if self.signal is not None:
            return [self.signal.width]
        return [as_signal(self.params["value"]).size]

    def sample_time(self) -> Any:
        st = super().sample_time()
        return CONTINUOUS if st.is_inherited else st

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        if self.signal is not None:
            return [self.signal(t)]
        return [as_signal(self.params["value"]).copy()]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        return self.signal.breakpoints() if self.signal is not None else []


@register
class Outport(Block):
    """An output port. Inside a subsystem it is the subsystem's output number *port*; at the top level it is an
    external output of the model (logged in the results, and a field of the outputs struct in generated C)."""

    type_id = "ports.outport"
    label = "Out"
    category = CATEGORY
    NUM_OUTPUTS = 0
    # Feedthrough so the Out block is always ordered after the block driving it; otherwise generated code
    # could copy the output before it is computed (a one-step delay).
    DIRECT_FEEDTHROUGH = True
    LOGS_INPUTS = True
    PARAMS = (Param("port", 1, ParamKind.INT, "Port number (1, 2, ...)", min=1),)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []


def _ports(diagram: Diagram, cls: type[Block]) -> list[Block]:
    ports = sorted((b for b in diagram.blocks if isinstance(b, cls)), key=lambda b: b.params["port"])
    numbers = [b.params["port"] for b in ports]
    if numbers != list(range(1, len(numbers) + 1)):
        kind = "Inport" if cls is Inport else "Outport"
        raise ParameterError(f"{kind} numbers must be 1, 2, ... without gaps or duplicates (got {numbers})")
    return ports


@register
class Subsystem(Block):
    """A block that contains its own diagram. Double-click it in the editor to open it.

    Its inputs and outputs are the In and Out blocks inside, in the order of their *port* numbers. Subsystems
    structure a model the way functions structure code: one subsystem per ECU function (e.g. "idle control",
    "fuel", "ignition"). Parameters inside can use the model workspace.
    """

    type_id = "ports.subsystem"
    label = "Subsystem"
    category = CATEGORY
    PARAMS = ()

    def __init__(self, name: str = "", system: Diagram | None = None, **params: Any) -> None:
        super().__init__(name, **params)
        self.system = system if system is not None else self._default_system()
        self.system.parent = self

    @staticmethod
    def _default_system() -> Diagram:
        d = Diagram("system")
        u = d.add(Inport(port=1), name="In1")
        y = d.add(Outport(port=1), name="Out1")
        u.meta["position"] = [0.0, 0.0]
        y.meta["position"] = [200.0, 0.0]
        d.connect(u, y)
        return d

    def inports(self) -> list[Block]:
        try:
            return _ports(self.system, Inport)
        except ParameterError:
            return sorted((b for b in self.system.blocks if isinstance(b, Inport)), key=lambda b: b.params["port"])

    def outports(self) -> list[Block]:
        try:
            return _ports(self.system, Outport)
        except ParameterError:
            return sorted((b for b in self.system.blocks if isinstance(b, Outport)), key=lambda b: b.params["port"])

    def num_inputs(self) -> int:
        return len(self.inports())

    def num_outputs(self) -> int:
        return len(self.outports())

    def validate_ports(self) -> None:
        _ports(self.system, Inport)
        _ports(self.system, Outport)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        raise RuntimeError("subsystems are flattened before simulation")


class PortProxy(Block):
    """Internal identity block that stands in for an In/Out port of a subsystem in the flattened model."""

    type_id = ""
    label = "port"
    PARAMS = ()

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [u[0]]
