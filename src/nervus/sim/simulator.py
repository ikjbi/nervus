"""The simulation loop.

At every *major* time step the simulator

1. computes all block outputs (discrete blocks only at their sample hits; held otherwise),
2. logs them,
3. updates the discrete states of blocks with a sample hit,
4. integrates the continuous states to the next major time.

With a fixed-step solver the major steps are a uniform grid. With a variable-step solver the major steps are
the discrete sample hits and the block breakpoints, and the solver chooses its own steps in between (those
points are logged too).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from typing import Any

import numpy as np

from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError, SimulationError
from nervus.core.sample_time import SampleTime
from nervus.core.settings import SimulationSettings
from nervus.core.types import EMPTY, Array
from nervus.sim.compiler import CompiledModel, Kind, compile_diagram
from nervus.sim.result import SimResult, SimStats
from nervus.solvers import FIXED_STEP_METHODS, integrate_variable


def _tol(t: float) -> float:
    return 1e-9 * max(1.0, abs(t))


class _RateScheduler:
    """Tracks the next sample hit of each discrete rate using integer counters (no drift)."""

    def __init__(self, rates: list[SampleTime], t_start: float) -> None:
        self.rates = rates
        self.counts = [max(0, math.ceil((t_start - r.offset) / r.period - 1e-9)) for r in rates]

    def next_hit(self, k: int) -> float:
        r = self.rates[k]
        return r.offset + self.counts[k] * r.period

    def next_time(self) -> float:
        return min((self.next_hit(k) for k in range(len(self.rates))), default=math.inf)

    def hits(self, t: float) -> frozenset[int]:
        return frozenset(k for k in range(len(self.rates)) if abs(self.next_hit(k) - t) <= _tol(t))

    def advance(self, hits: frozenset[int]) -> None:
        for k in hits:
            self.counts[k] += 1


class _Logger:
    def __init__(self, model: CompiledModel) -> None:
        self.model = model
        self.t: list[float] = []
        self.data: list[list[list[Array]]] = [[[] for _ in ws] for ws in model.out_widths]

    def record(self, t: float) -> None:
        self.t.append(t)
        for i, outs in enumerate(self.model.y):
            for p, y in enumerate(outs):
                self.data[i][p].append(y.copy())

    def result(self, stats: SimStats) -> SimResult:
        m = self.model
        signals: dict[str, Array] = {}
        for i, name in enumerate(m.names):
            for p, w in enumerate(m.out_widths[i]):
                rows = self.data[i][p]
                signals[f"{name}:{p}"] = np.vstack(rows) if rows else np.zeros((0, w))
        input_keys = {name: [f"{m.names[s]}:{p}" for s, p in m.inputs[i]] for i, name in enumerate(m.names)}
        aliases: dict[str, str] = {}
        for name, b in zip(m.names, m.blocks, strict=True):
            for alias, port in b.result_aliases().items():
                aliases[alias] = input_keys[name][port]
        return SimResult(np.asarray(self.t), signals, input_keys, aliases, stats)


def _on_empty_state(ev: Callable[[float, Array], float]) -> Callable[[float, Array], float]:
    def wrapped(t: float, x: Array) -> float:
        return ev(t, x[:0])

    for attr in ("direction", "index"):
        if hasattr(ev, attr):
            setattr(wrapped, attr, getattr(ev, attr))
    return wrapped


class _ZeroCrossings:
    """Zero-crossing events for solve_ivp, plus the frozen discontinuity *modes* of blocks.

    At every major step the branch (mode) of each discontinuous block is frozen, so the equations are smooth
    during integration. Each zero-crossing signal becomes an event; the integration stops exactly where one
    changes sign, and the modes are re-evaluated there.

    A signal that is exactly zero at the start of a step (just crossed) is only allowed to trigger in the
    opposite direction to the one it is leaving in; a tiny probe step tells which way that is. A signal that
    keeps crossing very often (chattering along a discontinuity, a "Zeno" situation) is switched off with a
    warning, and its block reverts to choosing its branch itself.
    """

    MAX_REPEATS = 50

    def __init__(self, model: CompiledModel, span: float, info: dict[str, Any]) -> None:
        self.model = model
        self.span = max(span, 1e-12)
        self.info = info
        self.disabled: set[int] = set()
        self.history: dict[int, list[float]] = {}
        self._key: tuple[float, bytes] | None = None
        self._values = EMPTY
        self._probe = EMPTY
        self.mode_blocks = list(model._zc_blocks)
        self.unfrozen: set[int] = set()
        self.signal_block: list[int] = []
        x0 = model.xc0
        model.eval_outputs(0.0, x0, None, init=True)
        for i, b, sl, inputs in model._zc_blocks:
            z = b.zero_crossings(0.0, [model.y[s][p] for s, p in inputs], x0[sl], model.xd[i])
            self.signal_block.extend([i] * (0 if z is None else np.asarray(z).size))

    def _values_at(self, t: float, x: Array) -> Array:
        key = (t, x.tobytes())
        if key != self._key:
            self._key = key
            self._values = self.model.zero_crossing_values(t, x)
        return self._values

    # ------------------------------------------------------------------ modes

    def unfreeze(self) -> None:
        for _i, b, _sl, _inp in self.mode_blocks:
            b.mode = None

    def freeze(self, t: float, x: Array, probe: bool = True) -> None:
        """Freeze every block's branch for the next integration step, choosing it from a tiny probe step into
        the future (right after a crossing the inputs sit exactly on the boundary)."""
        m = self.model
        self._key = None
        self.unfreeze()
        h = 1e-8 * self.span
        dx = m.derivatives(t, x) if x.size else x
        tp, xp = t + h, x + h * dx
        m.eval_outputs(tp, xp, None)
        modes = []
        for i, b, sl, inputs in self.mode_blocks:
            modes.append(
                None if i in self.unfrozen else b.compute_mode(tp, [m.y[s][p] for s, p in inputs], xp[sl], m.xd[i])
            )
        for (_i, b, _sl, _inp), mode in zip(self.mode_blocks, modes, strict=True):
            b.mode = None if mode is None else np.asarray(mode, dtype=float)
        self._probe = m.zero_crossing_values(tp, xp)
        m.eval_outputs(t, x, None)  # outputs at t with the frozen modes
        self._key = None

    # ------------------------------------------------------------------ events

    def events(self, t0: float, x0: Array, _cap: float) -> list[Callable[[float, Array], float]]:
        g0 = self._values_at(t0, x0)
        evs: list[Callable[[float, Array], float]] = []
        for k in range(g0.size):
            if k in self.disabled:
                continue

            def ev(t: float, x: Array, k: int = k) -> float:
                return float(self._values_at(min(t, _cap), x)[k])

            scale = 1e-9 * max(1.0, abs(float(self._probe[k])) if k < self._probe.size else 1.0)
            if abs(g0[k]) <= scale and k < self._probe.size and self._probe[k] != 0:
                ev.direction = -float(np.sign(self._probe[k]))  # type: ignore[attr-defined]
            ev.index = k  # type: ignore[attr-defined]
            evs.append(ev)
        self._active = evs
        return evs

    def fired(self, event_position: int, t: float, x: Array) -> None:
        k = self._active[event_position].index  # type: ignore[attr-defined]
        self.info["count"] += 1
        hist = self.history.setdefault(k, [])
        hist.append(t)
        if len(hist) >= self.MAX_REPEATS and hist[-1] - hist[-self.MAX_REPEATS] < 0.01 * self.span:
            block = self.signal_block[k] if k < len(self.signal_block) else -1
            for j, owner in enumerate(self.signal_block):
                if owner == block:
                    self.disabled.add(j)
            self.unfrozen.add(block)
            who = self.model.names[block] if block >= 0 else "a block"
            self.info["warnings"].append(
                f"{who}: zero crossings keep repeating near t = {t:.6g} (the system chatters along a "
                "discontinuity); zero-crossing detection was turned off for this block"
            )


def default_fixed_step(model: CompiledModel, t_start: float, t_final: float) -> float:
    span = t_final - t_start
    h0 = span / 1000 if span > 0 else 1.0
    if not model.rates:
        return h0
    # Fundamental rate: the largest step that divides every period and offset.
    values = [Fraction(v).limit_denominator(10**9) for r in model.rates for v in (r.period, r.offset) if v]
    g = values[0]
    for v in values[1:]:
        g = Fraction(
            math.gcd(g.numerator * v.denominator, v.numerator * g.denominator),
            g.denominator * v.denominator,
        )
    fundamental = float(g)
    if model.n_continuous_states == 0:
        return fundamental
    return fundamental / max(1, math.ceil(fundamental / h0 - 1e-9))


def simulate(
    diagram: Diagram | CompiledModel,
    t_final: float | None = None,
    *,
    t_start: float | None = None,
    solver: str | None = None,
    step: float | None = None,
    max_step: float | None = None,
    rtol: float | None = None,
    atol: float | None = None,
    settings: SimulationSettings | None = None,
    params: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    progress: Callable[[float], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SimResult:
    """Simulate ``diagram`` and return the logged signals.

    Settings come from ``settings`` if given, otherwise from ``diagram.settings``; keyword arguments override
    individual values. ``params`` overrides workspace variables for this run, e.g. ``params={"Kp": 2.0}``.
    ``inputs`` drives the model's top-level In blocks, by name: a :class:`~nervus.core.signals.Signal`, a
    number/vector (constant) or a ``(time, values)`` pair.
    ``progress(t)`` is called after each major step; if ``should_stop()`` returns true the run ends early (used
    by the GUI's Stop button).
    """
    if isinstance(diagram, CompiledModel):
        if params or inputs:
            raise ValueError("params/inputs cannot be used with an already compiled model; pass the Diagram")
        return _simulate_compiled(
            diagram, t_final, t_start, solver, step, max_step, rtol, atol, settings, progress, should_stop
        )
    attached = _attach_inputs(diagram, inputs or {})
    try:
        model = compile_diagram(diagram, params)
        return _simulate_compiled(
            model, t_final, t_start, solver, step, max_step, rtol, atol, settings, progress, should_stop
        )
    finally:
        for block in attached:
            block.signal = None


def _attach_inputs(diagram: Diagram, inputs: dict[str, Any]) -> list[Any]:
    from nervus.blocks.ports import Inport
    from nervus.core.signals import Signal

    ports = {b.name: b for b in diagram.blocks if isinstance(b, Inport)}
    unknown = set(inputs) - set(ports)
    if unknown:
        raise ModelError(
            f"no top-level In block named {', '.join(sorted(unknown))}; inputs: {', '.join(ports) or 'none'}"
        )
    attached = []
    for name, value in inputs.items():
        ports[name].signal = Signal.coerce(value)
        attached.append(ports[name])
    return attached


def _simulate_compiled(
    model: CompiledModel,
    t_final: float | None,
    t_start: float | None,
    solver: str | None,
    step: float | None,
    max_step: float | None,
    rtol: float | None,
    atol: float | None,
    settings: SimulationSettings | None,
    progress: Callable[[float], None] | None,
    should_stop: Callable[[], bool] | None,
) -> SimResult:
    base = settings or model.diagram.settings
    overrides: dict[str, Any] = {
        "t_final": t_final,
        "t_start": t_start,
        "solver": solver,
        "step": step,
        "max_step": max_step,
        "rtol": rtol,
        "atol": atol,
    }
    opts = replace(base, **{k: v for k, v in overrides.items() if v is not None})
    opts.validate()
    model.reset()
    wall0 = time.perf_counter()
    log = _Logger(model)
    t0, tf = opts.t_start, opts.t_final
    zc_info: dict[str, Any] = {"count": 0, "warnings": []}
    if opts.is_fixed_step:
        h, n_major, stopped = _run_fixed(model, opts, t0, tf, log, progress, should_stop)
    else:
        h = None
        n_major, stopped = _run_variable(model, opts, t0, tf, log, progress, should_stop, zc_info)
    stats = SimStats(
        opts.method,
        h,
        len(log.t),
        n_major,
        time.perf_counter() - wall0,
        stopped,
        zc_info["count"],
        zc_info["warnings"] or None,
    )
    return log.result(stats)


def _run_fixed(
    model: CompiledModel,
    opts: SimulationSettings,
    t0: float,
    tf: float,
    log: _Logger,
    progress: Callable[[float], None] | None,
    should_stop: Callable[[], bool] | None,
) -> tuple[float, int, bool]:
    h = opts.step or default_fixed_step(model, t0, tf)
    for r in model.rates:
        for name, v in (("period", r.period), ("offset", r.offset)):
            n = v / h
            if abs(n - round(n)) > 1e-6:
                raise SimulationError(
                    f"fixed step {h:g} does not divide the sample time {name} {v:g}; "
                    "choose a step that is an integer fraction of every discrete sample time"
                )
    step_fn = FIXED_STEP_METHODS[opts.method]
    sched = _RateScheduler(model.rates, t0)
    n_steps = math.ceil((tf - t0) / h - 1e-9)
    x = model.xc0.copy()
    stopped = False
    for k in range(n_steps + 1):
        t = min(t0 + k * h, tf)
        hits = sched.hits(t)
        model.eval_outputs(t, x, hits, init=(k == 0))
        log.record(t)
        if progress:
            progress(t)
        if model.check_monitors(t):
            stopped = True
            break
        if k == n_steps:
            break
        if should_stop and should_stop():
            stopped = True
            break
        model.update(t, x, hits)
        sched.advance(hits)
        t_next = min(t0 + (k + 1) * h, tf)
        if x.size:
            x = step_fn(model.derivatives, t, x, t_next - t)
    return h, len(log.t), stopped


def _run_variable(
    model: CompiledModel,
    opts: SimulationSettings,
    t0: float,
    tf: float,
    log: _Logger,
    progress: Callable[[float], None] | None,
    should_stop: Callable[[], bool] | None,
    zc_info: dict[str, Any],
) -> tuple[int, bool]:
    span = tf - t0
    max_step = opts.max_step or (span / 50 if span > 0 else 1.0)
    sched = _RateScheduler(model.rates, t0)
    breakpoints = model.breakpoints(t0, tf)
    bp_iter = 0
    # A model where everything is discrete or constant only needs to run at its sample hits.
    purely_discrete = bool(model.rates) and all(k is not Kind.CONTINUOUS for k in model.kinds)
    zc = _ZeroCrossings(model, span, zc_info) if (opts.zero_crossing and model.has_zero_crossings) else None
    x = model.xc0.copy()
    t = t0
    first = True
    n_major = 0
    while True:
        hits = sched.hits(t)
        if zc is not None:
            zc.unfreeze()
        model.eval_outputs(t, x, hits, init=first)
        first = False
        log.record(t)
        n_major += 1
        if progress:
            progress(t)
        if model.check_monitors(t):
            if zc is not None:
                zc.unfreeze()
            return n_major, True
        if t >= tf - _tol(tf):
            if zc is not None:
                zc.unfreeze()
            return n_major, False
        if should_stop and should_stop():
            if zc is not None:
                zc.unfreeze()
            return n_major, True
        model.update(t, x, hits)
        sched.advance(hits)
        if zc is not None:
            zc.freeze(t, x)

        while bp_iter < len(breakpoints) and breakpoints[bp_iter] <= t + _tol(t):
            bp_iter += 1
        next_bp = breakpoints[bp_iter] if bp_iter < len(breakpoints) else math.inf
        t_next = min(sched.next_time(), next_bp, tf)
        if x.size == 0 and zc is None:
            t = t_next if purely_discrete else min(t_next, t + max_step)
            continue

        # Evaluate just left of a breakpoint so the discontinuity happens at the major step, not inside
        # the last solver stage.
        t_eval_max = t_next - _tol(t_next) if t_next == next_bp else t_next

        def f(tt: float, xx: Array, _cap: float = t_eval_max) -> Array:
            return model.derivatives(min(tt, _cap), xx)

        events = zc.events(t, x, _cap=t_eval_max) if zc is not None else None
        stateless = x.size == 0
        if stateless:
            # No continuous states, but zero crossings to locate: integrate a dummy state so events still work.
            t_next = t_next if purely_discrete else min(t_next, t + max_step)
            events = [_on_empty_state(ev) for ev in events or []]

            def f(tt: float, xx: Array, _cap: float = t_eval_max) -> Array:
                return np.zeros(1)

        x_run = np.zeros(1) if stateless else x
        ts, ys, fired = integrate_variable(f, t, t_next, x_run, opts.method, opts.rtol, opts.atol, max_step, events)
        if stateless:
            ys = ys[:0]
        for j in range(1, len(ts) - 1):
            model.eval_outputs(float(ts[j]), ys[:, j], None)
            log.record(float(ts[j]))
        x = ys[:, -1].copy()
        if fired is not None and zc is not None:
            t = float(ts[-1])
            zc.fired(fired, t, x)
        else:
            t = t_next
