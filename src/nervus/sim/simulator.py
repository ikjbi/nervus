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
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from nervus.core.diagram import Diagram
from nervus.core.errors import SimulationError
from nervus.core.sample_time import SampleTime
from nervus.core.types import Array
from nervus.sim.compiler import CompiledModel, Kind, compile_diagram
from nervus.sim.result import SimResult, SimStats
from nervus.solvers import FIXED_STEP_METHODS, VARIABLE_STEP_METHODS, integrate_variable


@dataclass
class SolverOptions:
    """Solver settings.

    ``solver``: ``"auto"`` (RK45), a fixed-step method (``"euler"``, ``"rk4"``) or a variable-step method
    (``"RK45"``, ``"RK23"``, ``"DOP853"``, ``"Radau"``, ``"BDF"``, ``"LSODA"``).
    ``step``: fixed step size; defaults to the fastest discrete rate, or (t_final - t_start)/1000.
    ``max_step``: largest step a variable-step solver may take; defaults to (t_final - t_start)/50.
    """

    solver: str = "auto"
    step: float | None = None
    max_step: float | None = None
    rtol: float = 1e-6
    atol: float = 1e-8

    @property
    def method(self) -> str:
        return "RK45" if self.solver == "auto" else self.solver

    @property
    def is_fixed_step(self) -> bool:
        return self.method in FIXED_STEP_METHODS

    def validate(self) -> None:
        if self.method not in FIXED_STEP_METHODS and self.method not in VARIABLE_STEP_METHODS:
            valid = ", ".join(["auto", *FIXED_STEP_METHODS, *VARIABLE_STEP_METHODS])
            raise ValueError(f"unknown solver {self.solver!r}; choose one of {valid}")
        if self.step is not None and self.step <= 0:
            raise ValueError("step must be > 0")
        if self.max_step is not None and self.max_step <= 0:
            raise ValueError("max_step must be > 0")


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
        for i, b in enumerate(m.blocks):
            for p, w in enumerate(m.out_widths[i]):
                rows = self.data[i][p]
                signals[f"{b.name}:{p}"] = np.vstack(rows) if rows else np.zeros((0, w))
        input_keys = {b.name: [f"{m.blocks[s].name}:{p}" for s, p in m.inputs[i]] for i, b in enumerate(m.blocks)}
        aliases: dict[str, str] = {}
        for b in m.blocks:
            for alias, port in b.result_aliases().items():
                aliases[alias] = input_keys[b.name][port]
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
    t_final: float,
    *,
    t_start: float = 0.0,
    solver: str = "auto",
    step: float | None = None,
    max_step: float | None = None,
    rtol: float = 1e-6,
    atol: float = 1e-8,
    options: SolverOptions | None = None,
    progress: Callable[[float], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> SimResult:
    """Simulate ``diagram`` from ``t_start`` to ``t_final`` and return the logged signals.

    Solver settings may be passed as keyword arguments or as a :class:`SolverOptions` object.
    ``progress(t)`` is called after each major step; if ``should_stop()`` returns true the run ends early.
    """
    opts = options or SolverOptions(solver=solver, step=step, max_step=max_step, rtol=rtol, atol=atol)
    opts.validate()
    if t_final < t_start:
        raise ValueError("t_final must be >= t_start")
    model = diagram if isinstance(diagram, CompiledModel) else compile_diagram(diagram)
    model.reset()
    wall0 = time.perf_counter()
    log = _Logger(model)
    if opts.is_fixed_step:
        h, n_major, stopped = _run_fixed(model, opts, t_start, t_final, log, progress, should_stop)
    else:
        h = None
        n_major, stopped = _run_variable(model, opts, t_start, t_final, log, progress, should_stop)
    stats = SimStats(opts.method, h, len(log.t), n_major, time.perf_counter() - wall0, stopped)
    return log.result(stats)


def _run_fixed(
    model: CompiledModel,
    opts: SolverOptions,
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
    opts: SolverOptions,
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
