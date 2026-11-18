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
from nervus.core.errors import SimulationError
from nervus.core.sample_time import SampleTime
from nervus.core.settings import SimulationSettings
from nervus.core.types import Array
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
    progress: Callable[[float], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SimResult:
    """Simulate ``diagram`` and return the logged signals.

    Settings come from ``settings`` if given, otherwise from ``diagram.settings``; keyword arguments override
    individual values. ``params`` overrides workspace variables for this run, e.g. ``params={"Kp": 2.0}``.
    ``progress(t)`` is called after each major step; if ``should_stop()`` returns true the run ends early (used
    by the GUI's Stop button).
    """
    if isinstance(diagram, CompiledModel):
        if params:
            raise ValueError("params cannot be used with an already compiled model; pass the Diagram instead")
        model = diagram
    else:
        model = compile_diagram(diagram, params)
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
    if opts.is_fixed_step:
        h, n_major, stopped = _run_fixed(model, opts, t0, tf, log, progress, should_stop)
    else:
        h = None
        n_major, stopped = _run_variable(model, opts, t0, tf, log, progress, should_stop)
    stats = SimStats(opts.method, h, len(log.t), n_major, time.perf_counter() - wall0, stopped)
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
) -> tuple[int, bool]:
    span = tf - t0
    max_step = opts.max_step or (span / 50 if span > 0 else 1.0)
    sched = _RateScheduler(model.rates, t0)
    breakpoints = model.breakpoints(t0, tf)
    bp_iter = 0
    # A model where everything is discrete or constant only needs to run at its sample hits.
    purely_discrete = bool(model.rates) and all(k is not Kind.CONTINUOUS for k in model.kinds)
    x = model.xc0.copy()
    t = t0
    first = True
    n_major = 0
    while True:
        hits = sched.hits(t)
        model.eval_outputs(t, x, hits, init=first)
        first = False
        log.record(t)
        n_major += 1
        if progress:
            progress(t)
        if t >= tf - _tol(tf):
            return n_major, False
        if should_stop and should_stop():
            return n_major, True
        model.update(t, x, hits)
        sched.advance(hits)

        while bp_iter < len(breakpoints) and breakpoints[bp_iter] <= t + _tol(t):
            bp_iter += 1
        next_bp = breakpoints[bp_iter] if bp_iter < len(breakpoints) else math.inf
        t_next = min(sched.next_time(), next_bp, tf)
        if x.size == 0:
            t = t_next if purely_discrete else min(t_next, t + max_step)
            continue

        # Evaluate just left of a breakpoint so the discontinuity happens at the major step, not inside
        # the last solver stage.
        t_eval_max = t_next - _tol(t_next) if t_next == next_bp else t_next

        def f(tt: float, xx: Array, _cap: float = t_eval_max) -> Array:
            return model.derivatives(min(tt, _cap), xx)

        ts, ys = integrate_variable(f, t, t_next, x, opts.method, opts.rtol, opts.atol, max_step)
        for j in range(1, len(ts) - 1):
            model.eval_outputs(float(ts[j]), ys[:, j], None)
            log.record(float(ts[j]))
        x = ys[:, -1].copy()
        t = t_next
