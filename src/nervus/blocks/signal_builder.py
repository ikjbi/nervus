"""Signal Builder: piecewise-linear test signals, grouped into scenarios, drawn in the signal editor.

The signals are written in a short text format (the block's *definition*); the graphical signal editor (double-click
the block) edits the same text::

    # A tip-in and a release of the pedal
    group tip_in
      pedal: 0 0, 1 0, 1 80, 6 80, 6 0, 10 0
      brake: 0 0
    group panic_stop
      pedal: 0 30, 2 30, 2 0
      brake: 0 0, 2 0, 2.2 100, 10 100

Each line under ``group NAME`` is one signal: ``name: t v, t v, ...`` (times in seconds, increasing). Between two
points the signal is a straight line; two points at the same time make a jump (a step); after the last point the last
value is held. Every group has the same signals, in the same order: they are the block's outputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import CONTINUOUS
from nervus.core.types import Array

DEFAULT_SIGNALS = """# Two scenarios for a throttle test: a tip-in, and a slow ramp
group tip_in
  pedal: 0 0, 1 0, 1 80, 6 80, 6 0, 10 0
group ramp
  pedal: 0 0, 2 0, 8 100, 10 100
"""


@dataclass
class Signal:
    name: str
    times: list[float]
    values: list[float]

    def value(self, t: float) -> float:
        """The value at ``t``: linear between points, the later value at a jump, held before and after."""
        times = self.times
        k = int(np.searchsorted(times, t, side="right"))
        if k == 0:
            return self.values[0]
        if k == len(times):
            return self.values[-1]
        t0, t1 = times[k - 1], times[k]
        v0, v1 = self.values[k - 1], self.values[k]
        return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    def check(self, where: str) -> None:
        if not self.times:
            raise ParameterError(f"{where}: signal '{self.name}' has no points")
        diffs = np.diff(self.times)
        if np.any(diffs < 0):
            raise ParameterError(f"{where}: the times of '{self.name}' must increase")
        if np.any((diffs[1:] == 0) & (diffs[:-1] == 0)):
            raise ParameterError(f"{where}: '{self.name}' has three points at the same time (a jump needs two)")


@dataclass
class SignalGroup:
    name: str
    signals: list[Signal] = field(default_factory=list)

    def signal(self, name: str) -> Signal:
        return next(s for s in self.signals if s.name == name)


def _number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise ParameterError(f"{where}: '{text}' is not a number") from None


def parse_signals(text: str) -> list[SignalGroup]:
    """Read the signal text (see the module docstring); raises :class:`ParameterError` with the line."""
    groups: list[SignalGroup] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        where = f"line {lineno}"
        if line.startswith("group ") or line == "group":
            name = line[5:].strip()
            if not name.isidentifier():
                raise ParameterError(f"{where}: write 'group NAME' (letters, digits and _)")
            if any(g.name == name for g in groups):
                raise ParameterError(f"{where}: group '{name}' is defined twice")
            groups.append(SignalGroup(name))
            continue
        name, colon, points = line.partition(":")
        name = name.strip()
        if not colon or not name.isidentifier():
            raise ParameterError(f"{where}: write 'name: t v, t v, ...' (e.g. pedal: 0 0, 1 80)")
        if not groups:
            groups.append(SignalGroup("group1"))
        group = groups[-1]
        if any(s.name == name for s in group.signals):
            raise ParameterError(f"{where}: signal '{name}' is defined twice in group '{group.name}'")
        times, values = [], []
        for pair in (p.strip() for p in points.split(",")):
            words = pair.split()
            if len(words) != 2:
                raise ParameterError(f"{where}: each point is 'time value', separated by commas; got '{pair}'")
            times.append(_number(words[0], where))
            values.append(_number(words[1], where))
        sig = Signal(name, times, values)
        sig.check(where)
        group.signals.append(sig)
    if not groups or not groups[0].signals:
        raise ParameterError("define at least one signal, e.g. 'pedal: 0 0, 1 80'")
    names = [s.name for s in groups[0].signals]
    for g in groups[1:]:
        if [s.name for s in g.signals] != names:
            raise ParameterError(f"group '{g.name}' must have the signals {', '.join(names)} (in this order), "
                                 f"like group '{groups[0].name}'")  # fmt: skip
    return groups


def _fmt(v: float) -> str:
    return f"{v:.10g}"


def signals_to_text(groups: list[SignalGroup]) -> str:
    """The text for ``groups``; checked by parsing it again."""
    lines = []
    for g in groups:
        lines.append(f"group {g.name}")
        for s in g.signals:
            points = ", ".join(f"{_fmt(t)} {_fmt(v)}" for t, v in zip(s.times, s.values, strict=True))
            lines.append(f"  {s.name}: {points}")
    text = "\n".join(lines) + "\n"
    parse_signals(text)
    return text


@register
class SignalBuilder(Block):
    """Test signals drawn as lines: one output per signal, several **groups** (scenarios) to choose from.

    Double-click the block to draw the signals in the **signal editor**: drag a point, double-click to add one,
    select it and press Delete to remove it. The *group* chooses the scenario the simulation uses, e.g. a tip-in
    or a panic stop.

    The signals are stored as text in *definition*, one line per signal: ``pedal: 0 0, 1 0, 1 80, 10 80`` (pairs of
    time and value). Two points at the same time make a jump; after the last point the value is held. Variable-step
    solvers stop exactly at every point, so jumps are sharp.
    """

    type_id = "sources.signal_builder"
    label = "Signal Builder"
    category = "Sources"
    NUM_INPUTS = 0
    DEFAULT_SAMPLE_TIME = CONTINUOUS
    PARAMS = (
        Param("definition", DEFAULT_SIGNALS, ParamKind.CODE, "The signals: groups of 'name: t v, t v, ...' lines",
              hint="Double-click the block to draw the signals. As text: 'group NAME', then one line per signal, "
              "e.g. 'pedal: 0 0, 1 0, 1 80, 10 80' (time value pairs; two points at the same time make a jump)."),
        Param("group", "", ParamKind.STR, "The group (scenario) to play; empty = the first",
              hint="The name of a group in the definition, e.g. tip_in."),
    )  # fmt: skip

    def groups(self) -> list[SignalGroup]:
        return parse_signals(str(self.params["definition"]))

    def active_group(self) -> SignalGroup:
        groups = self.groups()
        name = str(self.params["group"]).strip()
        if not name:
            return groups[0]
        for g in groups:
            if g.name == name:
                return g
        raise ParameterError(f"no group '{name}'; the groups are {', '.join(g.name for g in groups)}")

    def validate_params(self) -> None:
        self.active_group()

    def suggestions(self, param: str) -> list[str]:
        if param == "group":
            try:
                return [g.name for g in self.groups()]
            except ParameterError:
                return []
        return []

    def signal_names(self) -> list[str]:
        try:
            return [s.name for s in self.groups()[0].signals]
        except ParameterError:
            return []

    def num_outputs(self) -> int:
        return max(1, len(self.signal_names()))

    def output_names(self) -> list[str]:
        return self.signal_names()

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        self._signals = self.active_group().signals

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([s.value(t)]) for s in self._signals]

    def breakpoints(self, t_start: float, t_final: float) -> list[float]:
        return sorted({t for s in self.active_group().signals for t in s.times if t_start <= t <= t_final})
