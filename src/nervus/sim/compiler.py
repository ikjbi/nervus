"""Turn a :class:`Diagram` into a :class:`CompiledModel` that can be executed.

Compilation:

1. checks the diagram structure (every input connected, valid ports),
2. propagates signal widths through the diagram,
3. configures each block with its resolved widths,
4. sorts blocks into execution order so each direct-feedthrough block runs after the blocks driving it,
   and reports algebraic loops,
5. resolves inherited sample times,
6. allocates the continuous and discrete state vectors.

The compiled model is also the starting point for code generation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from nervus.core.block import Block, Width
from nervus.core.datatypes import DOUBLE, DataType
from nervus.core.diagram import Diagram, Severity
from nervus.core.errors import AlgebraicLoopError, ModelError, SimulationError
from nervus.core.sample_time import CONSTANT, CONTINUOUS, SampleTime
from nervus.core.types import EMPTY, Array, as_signal
from nervus.sim.flatten import flatten


class Kind(Enum):
    """How often a block's outputs are recomputed."""

    CONSTANT = "constant"  # once, at initialisation
    CONTINUOUS = "continuous"  # at every evaluation
    DISCRETE = "discrete"  # at the block's sample hits, held in between


@dataclass
class CompiledModel:
    diagram: Diagram
    blocks: list[Block]
    """Blocks in execution order (subsystems flattened)."""
    names: list[str]
    """Full path name of each block, e.g. ``"controller/pid"``."""
    origin: list[Block]
    """The diagram block each compiled block came from (the In/Out block for subsystem ports)."""
    inputs: list[list[tuple[int, int]]]
    """For each block, for each input port: (index of driving block, output port)."""
    in_widths: list[list[int]]
    out_widths: list[list[int]]
    feedthrough: list[bool]
    sample_times: list[SampleTime]
    kinds: list[Kind]
    rates: list[SampleTime]
    """Distinct discrete sample times, fastest first."""
    rate_index: list[int]
    """For each block, the index into ``rates`` (or -1 if not discrete)."""
    xc_slices: list[slice]
    xc0: Array
    xd0: list[Array]
    out_types: list[list[DataType]] = field(default_factory=list)
    """Data type of each block output."""
    enable: list[list[tuple[int, int]]] = field(default_factory=list)
    """Enable signals gating each block (enabled subsystems); empty = always runs."""
    reset_on_enable: list[bool] = field(default_factory=list)
    trigger: list[list[tuple[int, int, str]]] = field(default_factory=list)
    """Trigger signals and edges gating each block (triggered subsystems); empty = always runs."""
    xd: list[Array] = field(default_factory=list)
    y: list[list[Array]] = field(default_factory=list)
    _validated: bool = False

    @property
    def n_continuous_states(self) -> int:
        return int(self.xc0.size)

    def index_of(self, block: Block | str) -> int:
        if isinstance(block, str):
            if block in self.names:
                return self.names.index(block)
            raise KeyError(block)
        for i, b in enumerate(self.origin):
            if b is block:
                return i
        raise KeyError(block.name)

    # ------------------------------------------------------------------ execution

    def reset(self) -> None:
        """Set all states back to their initial values and clear the output buffers."""
        self.xd = [x.copy() for x in self.xd0]
        self.y = [[np.zeros(w) for w in ws] for ws in self.out_widths]
        self._validated = False
        # Precomputed execution tables for the hot loops (one tuple per block).
        self._plan = [
            (i, b, self.kinds[i], self.rate_index[i], self.xc_slices[i], self.inputs[i])
            for i, b in enumerate(self.blocks)
        ]
        # Outputs that must be converted to a non-double data type: (block, [(port, type)], rounding, overflow)
        self._quantize = {
            i: ([(p, t) for p, t in enumerate(ts) if not t.is_double], *self.blocks[i].quantization())
            for i, ts in enumerate(self.out_types)
            if any(not t.is_double for t in ts)
        }
        self._cont_states = [(i, b, sl, self.inputs[i]) for i, b, _k, _r, sl, _inp in self._plan if sl.stop > sl.start]
        from nervus.core.block import Block as _Block

        self._zc_blocks = [
            (i, b, sl, self.inputs[i])
            for i, b, kind, _r, sl, _inp in self._plan
            if kind is Kind.CONTINUOUS and type(b).zero_crossings is not _Block.zero_crossings
        ]
        self.n_zero_crossings = -1  # determined on first evaluation
        self._jumpers = [
            (i, b, sl, self.inputs[i])
            for i, b, _k, _r, sl, _inp in self._plan
            if sl.stop > sl.start and type(b).major_step is not _Block.major_step
        ]
        self._enabled = [True] * len(self.blocks)  # the block ran at its last execution
        self._en_prev = [True] * len(self.blocks)  # its enable was on at its last execution
        self._trig_prev: list[list[float | None]] = [[None] * len(tr) for tr in self.trigger]
        self._monitors = [(i, b, self.inputs[i]) for i, b, *_ in self._plan if hasattr(b, "check_major")]

    def _u(self, i: int) -> list[Array]:
        y = self.y
        return [y[s][p] for s, p in self.inputs[i]]

    def _gate(self, i: int) -> bool:
        """Decide whether gated block ``i`` runs at this execution (enabled and/or triggered subsystems)."""
        y = self.y
        on = all(y[s][p][0] > 0 for s, p in self.enable[i])
        if on and not self._en_prev[i] and self.reset_on_enable[i]:
            self.xd[i] = self.xd0[i].copy()  # enabled again: reset states
        self._en_prev[i] = on
        prev = self._trig_prev[i]
        for k, (s, p, edge) in enumerate(self.trigger[i]):
            now = float(y[s][p][0])
            before = prev[k]
            prev[k] = now
            if before is None:  # first execution: only remember the value
                on = False
                continue
            rising = before <= 0 < now
            falling = before > 0 >= now
            fired = rising if edge == "rising" else falling if edge == "falling" else rising or falling
            on = on and fired
        return on

    def eval_outputs(self, t: float, xc: Array, hits: frozenset[int] | None, init: bool = False) -> None:
        """Compute block outputs at time ``t``.

        ``hits`` is the set of discrete rates that have a sample hit now (``None`` during minor solver steps,
        when discrete outputs are held). ``init`` forces every block, including constant ones, to compute.
        """
        y, xd = self.y, self.xd
        validated = self._validated
        constant, discrete = Kind.CONSTANT, Kind.DISCRETE
        gates = [bool(e or tr) for e, tr in zip(self.enable, self.trigger, strict=True)]
        for i, b, kind, rate, sl, inputs in self._plan:
            if not init:
                if kind is constant:
                    continue
                if kind is discrete and (hits is None or rate not in hits):
                    continue
            if gates[i] and kind is not constant:
                # Enabled/triggered subsystems: decided when the block executes at a major step (including the
                # first one), and kept during solver stages (like Simulink, and like the generated code).
                if hits is not None:
                    self._enabled[i] = self._gate(i)
                elif init:
                    continue  # not decided yet: keep the initial outputs
                if not self._enabled[i]:
                    continue  # disabled or not triggered: outputs held
            try:
                out = b.outputs(t, [y[s][p] for s, p in inputs], xc[sl], xd[i])
            except Exception as exc:
                name = self.names[i]
                raise SimulationError(f"{name}: error computing outputs at t={t:g}: {exc}", (name,)) from exc
            if not validated:
                out = self._check_outputs(i, out)
            q = self._quantize.get(i)
            if q is not None:
                out = list(out)
                ports, rounding, overflow = q
                for p, dtype in ports:
                    out[p] = dtype.quantize(out[p], rounding, overflow)
            y[i] = out
        self._validated = True

    def _check_outputs(self, i: int, out: Sequence[Array]) -> list[Array]:
        name = self.names[i]
        if len(out) != len(self.out_widths[i]):
            raise SimulationError(
                f"{name}: outputs() returned {len(out)} signals, expected {len(self.out_widths[i])}",
                (name,),
            )
        checked = []
        for k, (o, w) in enumerate(zip(out, self.out_widths[i], strict=True)):
            arr = as_signal(o)
            if arr.size != w:
                raise SimulationError(f"{name}: output {k} has width {arr.size}, expected {w}", (name,))
            checked.append(arr)
        return checked

    def derivatives(self, t: float, xc: Array) -> Array:
        """dxc/dt for the whole model. Evaluates outputs first (with discrete outputs held)."""
        self.eval_outputs(t, xc, None)
        dx = np.empty_like(xc)
        y, xd = self.y, self.xd
        for i, b, sl, inputs in self._cont_states:
            if (self.enable[i] or self.trigger[i]) and not self._enabled[i]:
                dx[sl] = 0.0  # disabled subsystem: continuous states hold
                continue
            try:
                dx[sl] = b.derivatives(t, [y[s][p] for s, p in inputs], xc[sl], xd[i])
            except Exception as exc:
                name = self.names[i]
                raise SimulationError(f"{name}: error computing derivatives at t={t:g}: {exc}", (name,)) from exc
        return dx

    def start_coverage(self, cov: Any) -> None:
        """Register the decision outcomes of every block with a :class:`nervus.coverage.Coverage`."""
        from nervus.core.block import Block as _Block

        self._coverage = cov
        self._cov_blocks = []
        for i, b in enumerate(self.blocks):
            if type(b).coverage_outcomes is _Block.coverage_outcomes:
                continue
            outcomes = b.coverage_outcomes()
            if outcomes:
                cov.register(self.names[i], b.label or b.type_id, outcomes)
                self._cov_blocks.append((i, b, self.inputs[i]))

    def collect_coverage(self, t: float, hits: frozenset[int] | None) -> None:
        """Record outcomes at a major step (discrete blocks only when they executed)."""
        cov = getattr(self, "_coverage", None)
        if cov is None:
            return
        for i, b, inputs in self._cov_blocks:
            if self.kinds[i] is Kind.DISCRETE and (hits is None or self.rate_index[i] not in hits):
                continue
            u = [self.y[s][p] for s, p in inputs]
            cov.hit(self.names[i], b.coverage_hits(t, u, self.y[i], self.xd[i]))

    def check_monitors(self, t: float) -> bool:
        """Run Stop Simulation / Assertion blocks at a major step. Returns True if the run should stop."""
        stop = False
        for i, b, inputs in self._monitors:
            verdict = b.check_major(t, [self.y[s][p] for s, p in inputs])
            if verdict == "stop":
                stop = True
            elif verdict and verdict.startswith("error:"):
                raise SimulationError(f"{self.names[i]}: {verdict[6:]}", (self.names[i],))
        return stop

    @property
    def has_zero_crossings(self) -> bool:
        return bool(self._zc_blocks)

    def apply_major_step(self, t: float, xc: Array, probe: float | None = None) -> tuple[Array, bool]:
        """Let blocks change their continuous state at a major step (e.g. an integrator reset).

        ``probe``: right after a zero crossing the signals sit exactly on zero; decide with the inputs a tiny
        step ``probe`` later (the side the signal is moving to)."""
        if not self._jumpers:
            return xc, False
        if probe:
            dx = self.derivatives(t, xc) if xc.size else xc
            self.eval_outputs(t + probe, xc + probe * dx, None)
        changed = False
        y = self.y
        for i, b, sl, inputs in self._jumpers:
            new = b.major_step(t, [y[s][p] for s, p in inputs], xc[sl], self.xd[i])
            if new is not None and not np.array_equal(new, xc[sl]):
                if not changed:
                    xc = xc.copy()
                xc[sl] = new
                changed = True
        if probe:
            self.eval_outputs(t, xc, None)
        return xc, changed

    def zero_crossing_values(self, t: float, xc: Array) -> Array:
        """All zero-crossing signals at (t, xc), with discrete outputs held. Infinite limits are ignored."""
        self.eval_outputs(t, xc, None)
        y, xd = self.y, self.xd
        parts = []
        for i, b, sl, inputs in self._zc_blocks:
            z = b.zero_crossings(t, [y[s][p] for s, p in inputs], xc[sl], xd[i])
            if z is not None:
                parts.append(np.asarray(z, dtype=float).ravel())
        values = np.concatenate(parts) if parts else EMPTY
        return np.where(np.isfinite(values), values, np.sign(values))

    def zero_crossing_names(self, t: float, xc: Array) -> list[str]:
        """Which block each zero-crossing signal belongs to (for messages)."""
        self.eval_outputs(t, xc, None)
        names = []
        for i, b, sl, inputs in self._zc_blocks:
            z = b.zero_crossings(t, [self.y[s][p] for s, p in inputs], xc[sl], self.xd[i])
            if z is not None:
                names.extend([self.names[i]] * np.asarray(z).size)
        return names

    def update(self, t: float, xc: Array, hits: frozenset[int]) -> None:
        """Advance the discrete states of every block that has a sample hit now."""
        new: list[tuple[int, Array]] = []
        for i, b in enumerate(self.blocks):
            if (self.enable[i] or self.trigger[i]) and not self._enabled[i]:
                continue  # disabled subsystem: discrete states hold
            if self.kinds[i] is Kind.DISCRETE and self.rate_index[i] in hits and self.xd[i].size:
                try:
                    new.append((i, as_signal(b.update(t, self._u(i), xc[self.xc_slices[i]], self.xd[i]))))
                except Exception as exc:
                    name = self.names[i]
                    raise SimulationError(f"{name}: error updating state at t={t:g}: {exc}", (name,)) from exc
        # Apply after all updates so every block saw the same inputs.
        for i, x in new:
            if x.size != self.xd[i].size:
                raise SimulationError(f"{self.names[i]}: update() changed the state size")
            self.xd[i] = x

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        pts: set[float] = set()
        for b in self.blocks:
            pts.update(p for p in b.breakpoints(t_start, t_final) if t_start < p <= t_final)
        return sorted(pts)


# ---------------------------------------------------------------------------- compile


def compile_diagram(
    diagram: Diagram, params: dict[str, Any] | None = None, default_rate: SampleTime | None = None
) -> CompiledModel:
    """Compile ``diagram``. Raises :class:`ModelError` describing the first problem found.

    ``params`` overrides workspace variables for this compilation (e.g. one point of a parameter sweep).
    Block parameter expressions are re-evaluated every time a diagram is compiled. ``default_rate`` is the
    rate of blocks that inherit theirs and are in no task (used to compile the inside of an atomic subsystem).
    """
    errors = [i for i in diagram.check() if i.severity is Severity.ERROR]
    if not errors:
        diagram.resolve_parameters(params)
    if errors:
        if len(errors) == 1:
            raise ModelError(errors[0].message, errors[0].blocks)
        involved = tuple(dict.fromkeys(b for e in errors for b in e.blocks))
        raise ModelError(
            f"{len(errors)} problems in the diagram:\n" + "\n".join(f"  - {e.message}" for e in errors),
            involved,
        )

    graph = flatten(diagram)
    blocks = graph.blocks
    names = graph.names
    inputs: list[list[tuple[int, int]]] = []
    for i, row in enumerate(graph.inputs):
        if any(r is None for r in row):
            port = row.index(None)
            raise ModelError(f"input {port} of {names[i]!r} is not connected", (names[i],))
        inputs.append([r for r in row if r is not None])

    out_w = _propagate_widths(blocks, inputs, names)
    in_w = [[out_w[s][p] for s, p in row] for row in inputs]

    for i, b in enumerate(blocks):
        try:
            b.configure(list(in_w[i]), list(out_w[i]))
        except (ValueError, TypeError) as exc:
            raise ModelError(f"{names[i]}: {exc}", (names[i],)) from exc

    out_t = _propagate_types(blocks, inputs, names)
    feedthrough = [b.direct_feedthrough() for b in blocks]
    gating = [[*e, *[(s, p) for s, p, _ in tr]] for e, tr in zip(graph.enable, graph.trigger, strict=True)]
    order = _sort(blocks, inputs, feedthrough, names, gating)

    # Re-index everything into execution order.
    pos = {old: new for new, old in enumerate(order)}
    blocks = [blocks[i] for i in order]
    names = [names[i] for i in order]
    origin = [graph.origin[i] for i in order]
    inputs = [[(pos[s], p) for s, p in inputs[i]] for i in order]
    in_w = [in_w[i] for i in order]
    out_w = [out_w[i] for i in order]
    out_t = [out_t[i] for i in order]
    enable = [[(pos[s], p) for s, p in graph.enable[i]] for i in order]
    reset_on_enable = [graph.reset_on_enable[i] for i in order]
    trigger = [[(pos[s], p, e) for s, p, e in graph.trigger[i]] for i in order]
    feedthrough = [feedthrough[i] for i in order]

    task_rate = [graph.task_rate[i] if graph.task_rate[i] is not None else default_rate for i in order]
    sample_times = _resolve_sample_times(blocks, inputs, task_rate)
    for b, st in zip(blocks, sample_times, strict=True):
        b.resolved_sample_time = st

    xc_parts: list[Array] = []
    xc_slices: list[slice] = []
    xd0: list[Array] = []
    n = 0
    for b, name, st, triggered, rate in zip(blocks, names, sample_times, trigger, task_rate, strict=True):
        xc = as_signal(b.initial_continuous_state())
        xd = as_signal(b.initial_discrete_state())
        if xc.size and rate is not None and rate.is_discrete:
            raise ModelError(
                f"{name}: blocks with continuous states cannot be inside a subsystem with a discrete sample time "
                f"({rate}); use a discrete equivalent (e.g. Discrete-Time Integrator)",
                (name,),
            )
        if xc.size and triggered:
            raise ModelError(
                f"{name}: blocks with continuous states cannot be inside a triggered subsystem "
                "(use a discrete equivalent)",
                (name,),
            )
        if xc.size and not st.is_continuous:
            raise ModelError(
                f"{name}: blocks with continuous states must have a continuous sample time",
                (name,),
            )
        if xd.size and not st.is_discrete:
            raise ModelError(
                f"{name}: this block has discrete states, so it needs a discrete sample time "
                f"(resolved to {st}). Set its 'sample_time' parameter to a period > 0, or drive it from a "
                "discrete block.",
                (name,),
            )
        xc_slices.append(slice(n, n + xc.size))
        n += xc.size
        xc_parts.append(xc)
        xd0.append(xd)

    rates = sorted({st for st in sample_times if st.is_discrete}, key=lambda s: (s.period, s.offset))
    rate_of = {st: k for k, st in enumerate(rates)}
    kinds = [
        Kind.CONSTANT if st.is_constant else Kind.DISCRETE if st.is_discrete else Kind.CONTINUOUS for st in sample_times
    ]

    model = CompiledModel(
        diagram=diagram,
        blocks=blocks,
        names=names,
        origin=origin,
        inputs=inputs,
        in_widths=in_w,
        out_widths=out_w,
        feedthrough=feedthrough,
        sample_times=sample_times,
        kinds=kinds,
        rates=rates,
        rate_index=[rate_of.get(st, -1) for st in sample_times],
        xc_slices=xc_slices,
        xc0=np.concatenate(xc_parts) if xc_parts else EMPTY,
        xd0=xd0,
        out_types=out_t,
        enable=enable,
        reset_on_enable=reset_on_enable,
        trigger=trigger,
    )
    model.reset()
    return model


def _propagate_widths(blocks: list[Block], inputs: list[list[tuple[int, int]]], names: list[str]) -> list[list[int]]:
    out_w: list[list[Width]] = [[None] * b.num_outputs() for b in blocks]
    max_iter = 2 * len(blocks) + 5
    for _ in range(max_iter):
        changed = False
        for i, b in enumerate(blocks):
            in_w = [out_w[s][p] for s, p in inputs[i]]
            try:
                new = list(b.output_widths(in_w))
            except (ValueError, TypeError) as exc:
                raise ModelError(f"{names[i]}: {exc}", (names[i],)) from exc
            if len(new) != b.num_outputs():
                raise ModelError(f"{names[i]}: output_widths() returned the wrong number of widths", (names[i],))
            if new != out_w[i]:
                out_w[i] = new
                changed = True
        if not changed:
            break
    else:
        raise ModelError("signal widths did not settle; check vector sizes in feedback loops")
    unresolved = [n for n, ws in zip(names, out_w, strict=True) if any(w is None for w in ws)]
    if unresolved:
        raise ModelError("could not determine the signal width of: " + ", ".join(unresolved), tuple(unresolved))
    for n, ws in zip(names, out_w, strict=True):
        for w in ws:
            if w is not None and w < 1:
                raise ModelError(f"{n}: invalid output width {w}", (n,))
    return [[int(w) for w in ws if w is not None] for ws in out_w]


def _propagate_types(
    blocks: list[Block], inputs: list[list[tuple[int, int]]], names: list[str]
) -> list[list[DataType]]:
    """Resolve every output's data type (inherited types flow along the signals, also around loops)."""
    out_t: list[list[DataType | None]] = [[None] * b.num_outputs() for b in blocks]
    for _ in range(2 * len(blocks) + 5):
        changed = False
        for i, b in enumerate(blocks):
            in_t = [out_t[s][p] for s, p in inputs[i]]
            try:
                new = list(b.output_types(in_t))
            except (ValueError, TypeError) as exc:
                raise ModelError(f"{names[i]}: {exc}", (names[i],)) from exc
            if new != out_t[i]:
                out_t[i] = new
                changed = True
        if not changed:
            break
    return [[t if t is not None else DOUBLE for t in ts] for ts in out_t]


def _sort(
    blocks: list[Block],
    inputs: list[list[tuple[int, int]]],
    feedthrough: list[bool],
    names: list[str],
    enable: list[list[tuple[int, int]]] | None = None,
) -> list[int]:
    """Topological sort over direct-feedthrough dependencies (Kahn's algorithm, stable). Blocks in an enabled
    subsystem also depend on its enable signal."""
    n = len(blocks)
    deps: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        if feedthrough[i]:
            deps[i] = {s for s, _ in inputs[i]}
        if enable is not None:
            deps[i] |= {s for s, _ in enable[i]}
    users: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for s in deps[i]:
            users[s].append(i)
    remaining = [len(d) for d in deps]
    ready = [i for i in range(n) if remaining[i] == 0]
    order: list[int] = []
    while ready:
        ready.sort()
        i = ready.pop(0)
        order.append(i)
        for j in users[i]:
            remaining[j] -= 1
            if remaining[j] == 0:
                ready.append(j)
    if len(order) < n:
        cycle = _find_cycle([i for i in range(n) if remaining[i] > 0], deps)
        loop = tuple(names[i] for i in cycle)
        raise AlgebraicLoopError(
            "algebraic loop: " + " -> ".join((*loop, loop[0])) + ". Every feedback loop needs a block "
            "with state, such as an Integrator or Unit Delay, whose output does not depend directly on its input.",
            loop,
        )
    return order


def _find_cycle(candidates: list[int], deps: list[set[int]]) -> list[int]:
    cand = set(candidates)
    start = candidates[0]
    path: list[int] = []
    seen: dict[int, int] = {}
    node = start
    # Follow dependencies; every candidate has at least one dependency inside the candidate set.
    while node not in seen:
        seen[node] = len(path)
        path.append(node)
        node = min(d for d in deps[node] if d in cand)
    cycle = path[seen[node] :]
    cycle.reverse()  # present in signal-flow order
    return cycle


def _resolve_sample_times(
    blocks: list[Block], inputs: list[list[tuple[int, int]]], task_rate: list[SampleTime | None] | None = None
) -> list[SampleTime]:
    """Resolve inherited sample times. Blocks inside an atomic subsystem with its own sample time
    (``task_rate``) take that rate; other inherited blocks take the rate of their inputs."""
    forced = task_rate or [None] * len(blocks)
    sts: list[SampleTime | None] = []
    for b, rate in zip(blocks, forced, strict=True):
        st = b.sample_time()
        if st.is_inherited and rate is not None:
            sts.append(rate)
        elif st.is_inherited:
            sts.append(CONTINUOUS if b.num_inputs() == 0 else None)
        else:
            sts.append(st)
    for _ in range(2 * len(blocks) + 5):
        changed = False
        for i, b in enumerate(blocks):
            if not b.sample_time().is_inherited or b.num_inputs() == 0 or forced[i] is not None:
                continue
            known: set[SampleTime] = set()
            for s, _ in inputs[i]:
                override = blocks[s].output_sample_time()
                src_st = sts[s]
                if override is not None:
                    known.add(override)
                elif src_st is not None:
                    known.add(src_st)
            if not known:
                continue
            new = _combine(known)
            if new != sts[i]:
                sts[i] = new
                changed = True
        if not changed:
            break
    return [st if st is not None else CONTINUOUS for st in sts]


def _combine(times: set[SampleTime]) -> SampleTime:
    non_const = {t for t in times if not t.is_constant}
    if not non_const:
        return CONSTANT
    if len(non_const) == 1:
        return non_const.pop()
    # Mixed continuous / multiple discrete rates: recompute at every evaluation.
    return CONTINUOUS
