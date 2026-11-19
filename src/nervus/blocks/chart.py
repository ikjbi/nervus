"""State machine (chart) block: modes and sequences, like a small Stateflow chart.

A chart is written in a short text language::

    input rpm, key
    output mode = 0, fuel = 0
    local tries = 0

    state off
      entry: mode = 0; fuel = 0

    state cranking
      entry: mode = 1; tries = tries + 1
      during: fuel = 1

    state running
      entry: mode = 2; fuel = 1

    transition off -> cranking: key > 0.5
    transition cranking -> running: rpm > 600
    transition cranking -> off: after(300) / fuel = 0
    transition running -> off: key < 0.5 or rpm < 300

The first state is the initial one (or write ``initial NAME``). Every sample period the chart:

1. checks the transitions leaving the active state, **in the order they are written**. The first whose guard
   is true fires: the source's ``exit`` actions run, then the transition's action (after ``/``), then the
   target's ``entry`` actions;
2. if no transition fires, runs the active state's ``during`` actions.

Guards and actions use Python-like expressions: ``+ - * / **``, comparisons, ``and or not``, ``abs min max
sqrt exp log sin cos`` and the constants ``pi`` and ``e``. ``after(n)`` is true when the state has been active for at
least *n* sample periods, and ``t_in_state`` is the time in seconds since the state was entered.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.expressions import parse_value
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e, "true": 1.0, "false": 0.0, "True": 1.0, "False": 0.0}
_ALLOWED = (
    ast.Expression,
    ast.Module,
    ast.Assign,
    ast.AugAssign,
    ast.Expr,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.IfExp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

DEFAULT_CHART = """# A two-state example: switch on above 1, off below 0 (hysteresis)
input u
output y = 0

state low
  entry: y = 0

state high
  entry: y = 1

transition low -> high: u > 1
transition high -> low: u < 0
"""


@dataclass
class ChartState:
    name: str
    entry: list[ast.stmt] = field(default_factory=list)
    during: list[ast.stmt] = field(default_factory=list)
    exit: list[ast.stmt] = field(default_factory=list)
    entry_src: str = ""
    during_src: str = ""
    exit_src: str = ""


@dataclass
class ChartTransition:
    source: int
    target: int
    guard: ast.expr
    action: list[ast.stmt]
    guard_src: str
    action_src: str


@dataclass
class ChartSpec:
    inputs: list[str]
    outputs: list[tuple[str, float]]
    locals: list[tuple[str, float]]
    states: list[ChartState]
    transitions: list[ChartTransition]
    initial: int

    @property
    def variables(self) -> list[str]:
        return [n for n, _ in self.outputs] + [n for n, _ in self.locals]


def _check_ast(node: ast.AST, names: set[str], assignable: set[str], where: str) -> None:
    for sub in ast.walk(node):
        if not isinstance(sub, _ALLOWED):
            raise ParameterError(f"{where}: '{type(sub).__name__}' is not allowed in charts")
        if isinstance(sub, ast.Call):
            if not isinstance(sub.func, ast.Name) or (sub.func.id not in _FUNCS and sub.func.id != "after"):
                raise ParameterError(f"{where}: only {', '.join([*_FUNCS, 'after'])} can be called")
            if sub.keywords:
                raise ParameterError(f"{where}: keyword arguments are not supported")
        known = names | set(_FUNCS) | set(_CONSTS) | {"after"}
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id not in known:
            raise ParameterError(f"{where}: unknown name '{sub.id}'")
        if isinstance(sub, ast.Assign):
            if len(sub.targets) != 1 or not isinstance(sub.targets[0], ast.Name):
                raise ParameterError(f"{where}: assign one variable at a time, e.g. 'y = 1'")
            if sub.targets[0].id not in assignable:
                raise ParameterError(f"{where}: '{sub.targets[0].id}' is not an output or local variable")
        if isinstance(sub, ast.AugAssign) and (not isinstance(sub.target, ast.Name) or sub.target.id not in assignable):
            raise ParameterError(f"{where}: can only update outputs and locals")


def _parse_actions(text: str, names: set[str], assignable: set[str], where: str) -> list[ast.stmt]:
    text = text.strip()
    if not text:
        return []
    try:
        mod = ast.parse("\n".join(part.strip() for part in text.split(";")), mode="exec")
    except SyntaxError as exc:
        raise ParameterError(f"{where}: syntax error in '{text}'") from exc
    _check_ast(mod, names, assignable, where)
    for stmt in mod.body:
        if not isinstance(stmt, ast.Assign | ast.AugAssign):
            raise ParameterError(f"{where}: actions must be assignments like 'y = 1'")
    return mod.body


def _parse_vars(text: str, where: str, with_init: bool) -> list[tuple[str, float]]:
    out = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        name, _, init = part.partition("=")
        name = name.strip()
        if not name.isidentifier():
            raise ParameterError(f"{where}: invalid name '{name}'")
        try:
            value = float(parse_value(init)) if init.strip() else 0.0
        except (ValueError, TypeError) as exc:
            raise ParameterError(f"{where}: invalid initial value '{init.strip()}'") from exc
        if init.strip() and not with_init:
            raise ParameterError(f"{where}: inputs have no initial value")
        out.append((name, value))
    return out


def parse_chart(text: str) -> ChartSpec:
    """Parse the chart language (see the module docstring). Raises :class:`ParameterError` with the line."""
    inputs: list[str] = []
    outputs: list[tuple[str, float]] = []
    locals_: list[tuple[str, float]] = []
    states: list[ChartState] = []
    raw_transitions: list[tuple[int, str, str, str, str]] = []
    initial_name: str | None = None
    current: ChartState | None = None
    pending: list[tuple[ChartState, str, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        where = f"line {lineno}"
        stripped = line.strip()
        indented = line[0] in " \t"
        keyword, _, rest = stripped.partition(" ")
        if indented and current is not None and re.match(r"^(entry|during|exit)\s*:", stripped):
            kind, _, actions = stripped.partition(":")
            pending.append((current, kind.strip(), actions, lineno))
            continue
        current = None
        if keyword == "input":
            inputs += [n for n, _ in _parse_vars(rest, where, with_init=False)]
        elif keyword == "output":
            outputs += _parse_vars(rest, where, with_init=True)
        elif keyword == "local":
            locals_ += _parse_vars(rest, where, with_init=True)
        elif keyword == "state":
            name = rest.strip()
            if not name.isidentifier():
                raise ParameterError(f"{where}: invalid state name '{name}'")
            if any(s.name == name for s in states):
                raise ParameterError(f"{where}: state '{name}' is defined twice")
            current = ChartState(name)
            states.append(current)
        elif keyword == "initial":
            initial_name = rest.strip()
        elif keyword == "transition":
            m = re.match(r"^(\w+)\s*->\s*(\w+)\s*:(.*)$", rest.strip())
            if not m:
                raise ParameterError(f"{where}: write 'transition A -> B: guard' (optionally '/ action')")
            guard, _, action = m.group(3).partition("/")
            raw_transitions.append((lineno, m.group(1), m.group(2), guard.strip(), action.strip()))
        else:
            raise ParameterError(f"{where}: expected input, output, local, state, initial or transition")
    if not states:
        raise ParameterError("a chart needs at least one state")
    names = set(inputs) | {n for n, _ in outputs} | {n for n, _ in locals_} | {"t_in_state"}
    assignable = {n for n, _ in outputs} | {n for n, _ in locals_}
    dupes = [n for n in names if [*inputs, *(o for o, _ in outputs), *(v for v, _ in locals_)].count(n) > 1]
    if dupes:
        raise ParameterError(f"names used twice: {', '.join(sorted(set(dupes)))}")
    for state, kind, actions, lineno in pending:
        setattr(state, kind, _parse_actions(actions, names, assignable, f"line {lineno}"))
        setattr(state, f"{kind}_src", actions.strip())
    index = {s.name: k for k, s in enumerate(states)}
    transitions = []
    for lineno, a, b, guard, action in raw_transitions:
        for sname in (a, b):
            if sname not in index:
                raise ParameterError(f"line {lineno}: unknown state '{sname}'")
        try:
            g = ast.parse(guard or "True", mode="eval")
        except SyntaxError as exc:
            raise ParameterError(f"line {lineno}: syntax error in guard '{guard}'") from exc
        _check_ast(g, names, assignable, f"line {lineno}")
        transitions.append(
            ChartTransition(
                index[a],
                index[b],
                g.body,
                _parse_actions(action, names, assignable, f"line {lineno}"),
                guard or "true",
                action,
            )
        )
    if initial_name is not None and initial_name not in index:
        raise ParameterError(f"initial state '{initial_name}' does not exist")
    return ChartSpec(inputs, outputs, locals_, states, transitions, index[initial_name] if initial_name else 0)


class _Interpreter:
    """Executes parsed chart code on a dictionary of variables (compiled once to Python code objects)."""

    def __init__(self, spec: ChartSpec) -> None:
        self.spec = spec

        def comp_stmts(stmts: list[ast.stmt]) -> Any:
            mod = ast.Module(body=stmts, type_ignores=[])
            return compile(ast.fix_missing_locations(mod), "<chart>", "exec") if stmts else None

        self.entry = [comp_stmts(s.entry) for s in spec.states]
        self.during = [comp_stmts(s.during) for s in spec.states]
        self.exit = [comp_stmts(s.exit) for s in spec.states]
        self.guards = [
            compile(ast.fix_missing_locations(ast.Expression(t.guard)), "<chart>", "eval") for t in spec.transitions
        ]
        self.actions = [comp_stmts(t.action) for t in spec.transitions]
        self.outgoing: list[list[int]] = [[] for _ in spec.states]
        for k, t in enumerate(spec.transitions):
            self.outgoing[t.source].append(k)

    @staticmethod
    def _run(code: Any, env: dict[str, Any]) -> None:
        if code is not None:
            exec(code, {"__builtins__": {}}, env)

    def step(self, active: int, ticks: int, env: dict[str, Any], period: float) -> tuple[int, int]:
        elapsed = ticks + 1  # periods since the state was entered (one has passed at the first step after entry)
        env["t_in_state"] = elapsed * period
        env["after"] = lambda n: elapsed >= n
        for k in self.outgoing[active]:
            if eval(self.guards[k], {"__builtins__": {}}, env):
                target = self.spec.transitions[k].target
                self._run(self.exit[active], env)
                self._run(self.actions[k], env)
                self._run(self.entry[target], env)
                return target, 0
        self._run(self.during[active], env)
        return active, ticks + 1

    def enter_initial(self, env: dict[str, Any]) -> None:
        env["t_in_state"] = 0.0
        env["after"] = lambda n: n <= 0
        self._run(self.entry[self.spec.initial], env)


@register
class StateChart(Block):
    """A state machine (chart) for operating modes, sequences and fault handling, like Simulink's Stateflow.

    ![An engine operating-mode chart](figures/chart_engine_modes.png)

    The chart is written in a short text language in *definition*:

    ```
    input rpm, key
    output mode = 0, fuel = 0

    state off
      entry: mode = 0; fuel = 0
    state cranking
      entry: mode = 1
      during: fuel = 1
    state running
      entry: mode = 2

    transition off -> cranking: key > 0.5
    transition cranking -> running: rpm > 600
    transition cranking -> off: after(300) / fuel = 0
    transition running -> off: key < 0.5 or rpm < 300
    ```

    Inputs and outputs become the block's ports, in the order they are declared; with *state_output* an extra
    last output gives the active state's number (0, 1, ... in the order the states are written). Every sample
    period the transitions leaving the active state are checked in the order written; the first true guard
    fires (exit → transition action → entry). Otherwise the state's *during* actions run. ``after(n)`` is true
    after *n* periods in the state, and ``t_in_state`` is the time in the state in seconds.

    The chart runs at a discrete rate, and can be generated as C code.
    """

    type_id = "charts.state_chart"
    label = "State Chart"
    category = "State Machines"
    TYPE_RULE = "double"
    PARAMS = (
        Param("definition", DEFAULT_CHART, ParamKind.CODE, "The chart: inputs, outputs, states and transitions"),
        Param("state_output", True, ParamKind.BOOL, "Add an output with the number of the active state"),
        Param("sample_time", -1.0, ParamKind.SAMPLE_TIME, "Sample period (-1 = inherit)", "s"),
    )

    def validate_params(self) -> None:
        self.spec = parse_chart(self.params["definition"])
        self._interp = _Interpreter(self.spec)

    def num_inputs(self) -> int:
        return len(self.spec.inputs)

    def num_outputs(self) -> int:
        return len(self.spec.outputs) + (1 if self.params["state_output"] else 0)

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        bad = [self.spec.inputs[k] for k, w in enumerate(in_widths) if w != 1]
        if bad:
            raise ValueError(f"chart inputs must be scalar: {', '.join(bad)}")

    # discrete state layout: [active state, ticks in state, outputs..., locals...]

    def _env(self, u: Sequence[Array], xd: Array) -> dict[str, Any]:
        env: dict[str, Any] = {n: float(u[k][0]) for k, n in enumerate(self.spec.inputs)}
        env.update(_FUNCS)
        env.update(_CONSTS)
        for k, name in enumerate(self.spec.variables):
            env[name] = float(xd[2 + k])
        return env

    def initial_discrete_state(self) -> Array:
        env: dict[str, Any] = dict(_FUNCS)
        env.update(_CONSTS)
        env.update({n: 0.0 for n in self.spec.inputs})
        for name, init in self.spec.outputs + self.spec.locals:
            env[name] = init
        self._interp.enter_initial(env)
        return np.array([float(self.spec.initial), 0.0, *[float(env[n]) for n in self.spec.variables]])

    def _step(self, u: Sequence[Array], xd: Array) -> Array:
        env = self._env(u, xd)
        active, ticks = self._interp.step(int(xd[0]), int(xd[1]), env, self.period())
        return np.array([float(active), float(ticks), *[float(env[n]) for n in self.spec.variables]])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        nxt = self._step(u, xd)
        outs = [np.array([nxt[2 + k]]) for k in range(len(self.spec.outputs))]
        if self.params["state_output"]:
            outs.append(np.array([nxt[0]]))
        return outs

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return self._step(u, xd)
