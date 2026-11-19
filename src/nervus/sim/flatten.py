"""Flatten a hierarchical diagram (with subsystems) into one graph of leaf blocks.

The In and Out blocks inside a subsystem become identity "port proxy" nodes, so the subsystem boundary
disappears but every signal keeps a name (``"controller/In1"``). Top-level In/Out blocks stay as they are:
they are the model's external inputs and outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

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
    enable: list[list[tuple[int, int]]] = field(default_factory=list)
    """For each node, the enable signals (source node, port) of enclosing enabled subsystems (all must be > 0)."""
    reset_on_enable: list[bool] = field(default_factory=list)
    """For each node: reset its discrete state when an enclosing subsystem is enabled again."""
    task_rate: list[Any] = field(default_factory=list)
    """For each node, the sample time of the innermost enclosing subsystem that has one (or None)."""
    trigger: list[list[tuple[int, int, str]]] = field(default_factory=list)
    """For each node, the trigger signals (source node, port, edge) of enclosing triggered subsystems."""
    links: list[tuple[int, str, int, str]] = field(default_factory=list)
    """Physical links between ports of physical blocks: (node, port, node, port)."""


def flatten(diagram: Diagram) -> FlatGraph:
    g = FlatGraph()
    _add(diagram, "", g, top=True)
    _physical_networks(g)
    return g


def _new_node(g: FlatGraph, block: Block, name: str, inputs: list[tuple[int, int] | None], like: int) -> int:
    g.blocks.append(block)
    g.inputs.append(inputs)
    g.names.append(name)
    g.origin.append(block)
    g.enable.append(list(g.enable[like]))
    g.reset_on_enable.append(g.reset_on_enable[like])
    g.trigger.append(list(g.trigger[like]))
    g.task_rate.append(g.task_rate[like])
    return len(g.blocks) - 1


def _physical_networks(g: FlatGraph) -> None:
    """Replace the physical blocks by one core node (the states) and one algebraic node per network; each
    physical block becomes a tap that passes on its sensor outputs under its own name."""
    from nervus.physical.network import NetworkAlgebraic, NetworkCore, NetworkTap, PhysicalBlock, build_networks

    if not any(isinstance(b, PhysicalBlock) for b in g.blocks):
        return
    for net, members in build_networks(g.blocks, g.names, g.links):
        try:
            net.derivatives(net.x0, np.zeros(net.n_inputs))  # a trial solve: is the network well posed?
            net.classify_outputs()
        except Exception as exc:  # e.g. a singular network
            raise ModelError(str(exc), tuple(g.names[i] for i in members)) from exc
        instant = set(net.instant_outputs)
        state_outputs = [k for k in range(net.n_outputs) if k not in instant]
        sig_inputs: list[tuple[int, int] | None] = [src for i in members for src in g.inputs[i]]
        prefix = g.names[members[0]].rpartition("/")[0]
        base = f"{prefix}/{net.name}" if prefix else net.name
        core = _new_node(g, NetworkCore(net, state_outputs), base, list(sig_inputs), members[0])
        alg = None
        if net.instant_outputs:
            alg = _new_node(g, NetworkAlgebraic(net), base + ":instant", [(core, 0), *sig_inputs], members[0])
        where = {k: (core, 1 + j) for j, k in enumerate(state_outputs)}
        if alg is not None:
            where.update({k: (alg, j) for j, k in enumerate(net.instant_outputs)})
        for m in net.members:
            i = next(i for i in members if g.names[i] == m.path)
            n_out = m.outputs.stop - m.outputs.start
            g.blocks[i] = NetworkTap(m.path, n_out)
            taps: list[tuple[int, int] | None] = [where[k] for k in range(m.outputs.start, m.outputs.stop)]
            g.inputs[i] = taps


def _add(diagram: Diagram, prefix: str, g: FlatGraph, top: bool) -> dict[int, int]:
    """Add the nodes of ``diagram``; returns block id -> node index for this level (subsystems excluded)."""
    node: dict[int, int] = {}
    subs: dict[int, tuple[Subsystem, dict[int, int]]] = {}
    spans: dict[int, range] = {}
    for b in diagram.blocks:
        name = prefix + b.name
        if isinstance(b, Subsystem):
            try:
                b.validate_ports()
            except ParameterError as exc:
                raise ModelError(f"{name}: {exc}", (name,)) from exc
            first = len(g.blocks)
            subs[id(b)] = (b, _add(b.system, name + "/", g, top=False))
            spans[id(b)] = range(first, len(g.blocks))
            rate = b.sample_time()
            if not rate.is_inherited:
                for k in spans[id(b)]:
                    if g.task_rate[k] is None:  # an inner subsystem's own rate wins
                        g.task_rate[k] = rate
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
        g.enable.append([])
        g.reset_on_enable.append(False)
        g.trigger.append([])
        g.task_rate.append(None)
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
        if isinstance(c.dst, Subsystem) and c.dst_port == c.dst.trigger_index:
            s_node, s_port = source(c.src, c.src_port)  # the trigger input gates every block inside
            for k in spans[id(c.dst)]:
                g.trigger[k].append((s_node, s_port, str(c.dst.params["trigger"])))
            continue
        if isinstance(c.dst, Subsystem) and c.dst_port == c.dst.enable_index:
            src = source(c.src, c.src_port)  # the enable input gates every block inside
            reset = c.dst.params["when_enabled"] == "reset"
            for k in spans[id(c.dst)]:
                g.enable[k].append(src)
                g.reset_on_enable[k] = g.reset_on_enable[k] or reset
            continue
        d_node, d_port = dest(c.dst, c.dst_port)
        g.inputs[d_node][d_port] = source(c.src, c.src_port)

    def end(b: Block, port: str) -> tuple[int, str]:
        if isinstance(b, Subsystem):  # a physical port of a subsystem: its Connection Port block inside
            sub, inner = subs[id(b)]
            cp = next(c for c in sub.connection_ports() if c.name == port)
            return inner[id(cp)], "a"
        return node[id(b)], port

    for link in diagram.links:
        g.links.append((*end(link.a, link.a_port), *end(link.b, link.b_port)))
    return node
