"""Flatten a hierarchical diagram (with subsystems) into one graph of leaf blocks.

The In and Out blocks inside a subsystem become identity "port proxy" nodes, so the subsystem boundary
disappears but every signal keeps a name (``"controller/In1"``). Top-level In/Out blocks stay as they are:
they are the model's external inputs and outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nervus.blocks.ports import Inport, Outport, PortProxy, Subsystem
from nervus.core.block import Block
from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError, ParameterError


@dataclass
class FlatGraph:
    blocks: list[Block] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    """Full path name of each node, e.g. ``"controller/pid"``."""
    inputs: list[list[tuple[int, int] | None]] = field(default_factory=list)
    """For each node, for each input port: (source node, output port)."""
    origin: list[Block] = field(default_factory=list)
    """The block each node came from (the In/Out block for port proxies)."""


def flatten(diagram: Diagram) -> FlatGraph:
    g = FlatGraph()
    _add(diagram, "", g, top=True)
    return g


def _add(diagram: Diagram, prefix: str, g: FlatGraph, top: bool) -> dict[int, int]:
    """Add the nodes of ``diagram``; returns block id -> node index for this level (subsystems excluded)."""
    node: dict[int, int] = {}
    subs: dict[int, tuple[Subsystem, dict[int, int]]] = {}
    for b in diagram.blocks:
        name = prefix + b.name
        if isinstance(b, Subsystem):
            try:
                b.validate_ports()
            except ParameterError as exc:
                raise ModelError(f"{name}: {exc}", (name,)) from exc
            subs[id(b)] = (b, _add(b.system, name + "/", g, top=False))
            continue
        if not top and isinstance(b, Inport | Outport):
            proxy = PortProxy(name)
            g.blocks.append(proxy)
            g.inputs.append([None])
        else:
            g.blocks.append(b)
            g.inputs.append([None] * b.num_inputs())
        g.names.append(name)
        g.origin.append(b)
        node[id(b)] = len(g.blocks) - 1

    def source(b: Block, port: int) -> tuple[int, int]:
        if isinstance(b, Subsystem):
            sub, inner = subs[id(b)]
            return inner[id(sub.outports()[port])], 0
        return node[id(b)], port

    def dest(b: Block, port: int) -> tuple[int, int]:
        if isinstance(b, Subsystem):
            sub, inner = subs[id(b)]
            return inner[id(sub.inports()[port])], 0
        return node[id(b)], port

    for c in diagram.connections:
        d_node, d_port = dest(c.dst, c.dst_port)
        g.inputs[d_node][d_port] = source(c.src, c.src_port)
    if not top:
        # A subsystem's Out block drives the outside; its In blocks are driven from outside (set by the parent).
        pass
    return node
