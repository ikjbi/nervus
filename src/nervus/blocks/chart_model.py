"""An editable form of a chart, for the graphical chart editor: states, transitions and their positions.

The chart language (see :mod:`nervus.blocks.chart`) stays the one definition of a chart: :func:`from_text` reads it
into an :class:`EditableChart` of plain strings, the editor changes that, and :meth:`EditableChart.to_text` writes
the language again (checked with :func:`~nervus.blocks.chart.parse_chart`). Comments in the text are not kept.

Each state's box is stored by name in the block's ``meta["chart_layout"]``: ``{name: [x, y, w, h]}``, relative to
the box of the enclosing state; :func:`auto_layout` places the states that have no box yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nervus.blocks.chart import parse_chart

STATE_W, STATE_H = 150.0, 80.0
"""Size of a new state's box."""
GAP = 70.0
PAD, HEADER = 20.0, 34.0
"""Space inside a composite state around its children, and above them for its name and actions."""


@dataclass
class EState:
    name: str
    parent: str | None = None
    entry: str = ""
    during: str = ""
    exit: str = ""
    parallel: bool = False
    history: bool = False
    initial: str | None = None
    """The child entered by default (composite states)."""


@dataclass
class ETransition:
    source: str
    target: str
    guard: str = ""
    action: str = ""

    def label(self) -> str:
        guard = "" if self.guard in ("", "true", "True") else self.guard
        return guard + (f" / {self.action}" if self.action else "")


@dataclass
class EditableChart:
    inputs: list[str] = field(default_factory=list)
    outputs: list[tuple[str, str]] = field(default_factory=list)
    """(name, initial value as written)."""
    locals: list[tuple[str, str]] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    states: list[EState] = field(default_factory=list)
    transitions: list[ETransition] = field(default_factory=list)
    """In priority order: the first whose guard is true fires."""
    initial: str | None = None
    """The top-level state entered first."""
    layout: dict[str, list[float]] = field(default_factory=dict)

    # ------------------------------------------------------------------ queries

    def state(self, name: str) -> EState:
        return next(s for s in self.states if s.name == name)

    def children(self, name: str | None) -> list[EState]:
        return [s for s in self.states if s.parent == name]

    def descendants(self, name: str) -> list[str]:
        out: list[str] = []
        for c in self.children(name):
            out += [c.name, *self.descendants(c.name)]
        return out

    def initial_of(self, parent: str | None) -> str | None:
        kids = self.children(parent)
        if not kids:
            return None
        chosen = self.initial if parent is None else self.state(parent).initial
        return chosen if chosen in {k.name for k in kids} else kids[0].name

    def outgoing(self, name: str) -> list[ETransition]:
        return [t for t in self.transitions if t.source == name]

    def priority(self, t: ETransition) -> int:
        """1 for the transition checked first among those leaving the same state."""
        return self.outgoing(t.source).index(t) + 1

    def unique_name(self, base: str = "state") -> str:
        names = {s.name for s in self.states}
        k = 1
        while f"{base}{k}" in names:
            k += 1
        return f"{base}{k}"

    # ------------------------------------------------------------------ edits

    def add_state(self, name: str | None = None, parent: str | None = None, at: tuple[float, float] | None = None,
                  entry: str = "") -> EState:  # fmt: skip
        st = EState(name or self.unique_name(), parent, entry=entry)
        self.states.append(st)
        if at is not None:
            self.layout[st.name] = [at[0], at[1], STATE_W, STATE_H]
        else:
            auto_layout(self)
        if parent is not None:
            _grow_to_fit(self, parent)
        return st

    def rename_state(self, old: str, new: str) -> None:
        if not new.isidentifier():
            raise ValueError(f"'{new}' is not a valid state name (letters, digits and _)")
        if any(s.name == new for s in self.states):
            raise ValueError(f"there is already a state '{new}'")
        for s in self.states:
            if s.name == old:
                s.name = new
            if s.parent == old:
                s.parent = new
            if s.initial == old:
                s.initial = new
        for t in self.transitions:
            t.source = new if t.source == old else t.source
            t.target = new if t.target == old else t.target
        if self.initial == old:
            self.initial = new
        if old in self.layout:
            self.layout[new] = self.layout.pop(old)

    def remove_state(self, name: str) -> None:
        """Remove a state, its children and every transition to or from them."""
        gone = {name, *self.descendants(name)}
        self.states = [s for s in self.states if s.name not in gone]
        self.transitions = [t for t in self.transitions if t.source not in gone and t.target not in gone]
        for s in self.states:
            if s.initial in gone:
                s.initial = None
        if self.initial in gone:
            self.initial = None
        for n in gone:
            self.layout.pop(n, None)

    def move_priority(self, t: ETransition, delta: int) -> None:
        """Check ``t`` earlier (``delta`` = -1) or later (+1) among the transitions leaving its state."""
        same = self.outgoing(t.source)
        k = same.index(t)
        j = min(max(k + delta, 0), len(same) - 1)
        if j == k:
            return
        a, b = self.transitions.index(same[k]), self.transitions.index(same[j])
        self.transitions[a], self.transitions[b] = self.transitions[b], self.transitions[a]

    # ------------------------------------------------------------------ text

    def to_text(self) -> str:
        """The chart language for this chart; raises ``ParameterError`` if it is not a valid chart."""
        lines: list[str] = []
        for kw, items in (("input", self.inputs), ("param", self.params), ("event", self.events)):
            if items:
                lines.append(f"{kw} {', '.join(items)}")
        for kw, pairs in (("output", self.outputs), ("local", self.locals)):
            if pairs:
                lines.append(f"{kw} {', '.join(f'{n} = {v}' if v not in ('', '0', '0.0') else n for n, v in pairs)}")
        if self.initial is not None and self.states and self.initial != self.children(None)[0].name:
            lines.append(f"initial {self.initial}")

        def write(st: EState, depth: int) -> None:
            pad = "  " * depth
            lines.append("")
            lines.append(f"{pad}state {st.name}{' parallel' if st.parallel else ''}")
            for kind in ("entry", "during", "exit"):
                text = getattr(st, kind).strip()
                if text:
                    lines.append(f"{pad}  {kind}: {text}")
            kids = self.children(st.name)
            if st.history:
                lines.append(f"{pad}  history")
            if kids and st.initial is not None and st.initial != kids[0].name:
                lines.append(f"{pad}  initial {st.initial}")
            for c in kids:
                write(c, depth + 1)

        for st in self.children(None):
            write(st, 0)
        if self.transitions:
            lines.append("")
        for t in self.transitions:
            guard = t.guard.strip() or "true"
            lines.append(
                f"transition {t.source} -> {t.target}: {guard}" + (f" / {t.action.strip()}" if t.action.strip() else "")
            )
        text = "\n".join(lines).lstrip("\n") + "\n"
        parse_chart(text)  # raises with the line number if something is wrong
        return text


def from_text(text: str, layout: dict[str, list[float]] | None = None) -> EditableChart:
    """Read a chart definition; raises ``ParameterError`` if it is not valid."""
    spec = parse_chart(text)
    names = [s.name for s in spec.states]
    inits = _initial_values(text)
    chart = EditableChart(
        inputs=list(spec.inputs),
        outputs=[(n, inits.get(n, _fmt(v))) for n, v in spec.outputs],
        locals=[(n, inits.get(n, _fmt(v))) for n, v in spec.locals],
        params=list(spec.params),
        events=list(spec.events),
        initial=names[spec.initial],
    )
    for st in spec.states:
        chart.states.append(EState(st.name, None if st.parent is None else names[st.parent], st.entry_src,
                                   st.during_src, st.exit_src, st.parallel, st.history,
                                   None if st.initial is None else names[st.initial]))  # fmt: skip
    for t in spec.transitions:
        guard = "" if t.guard_src in ("true", "True") else t.guard_src
        chart.transitions.append(ETransition(names[t.source], names[t.target], guard, t.action_src))
    chart.layout = {k: list(map(float, v)) for k, v in (layout or {}).items() if k in names and len(v) == 4}
    auto_layout(chart)
    return chart


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _initial_values(text: str) -> dict[str, str]:
    """Initial values of outputs and locals as written (e.g. ``idle_normal`` stays a name, not its value)."""
    out = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        kw, _, rest = line.partition(" ")
        if kw in ("output", "local"):
            for part in rest.split(","):
                name, eq, init = part.partition("=")
                if eq and name.strip():
                    out[name.strip()] = init.strip()
    return out


# ---------------------------------------------------------------------- layout


def auto_layout(chart: EditableChart) -> None:
    """Give a box to every state that has none.

    The levels are laid out from the innermost out, so a composite state's size (around its children) is known
    before its siblings are placed. Siblings are placed in columns by their distance from the level's initial
    state along the transitions, so a chart reads from left to right. New states next to placed ones go in a row
    below them.
    """
    new = {s.name for s in chart.states if s.name not in chart.layout}
    if not new:
        return
    levels = sorted({s.parent for s in chart.states}, key=lambda p: -1 if p is None else len(_ancestors(chart, p)),
                    reverse=True)  # fmt: skip
    for parent in levels:
        kids = chart.children(parent)
        fresh = [k.name for k in kids if k.name in new]
        for name in fresh:  # a size: the default, or (composite) around its children laid out already
            if name not in chart.layout:
                chart.layout[name] = [0.0, 0.0, STATE_W, _leaf_height(chart, name)]
            if chart.children(name):
                _grow_to_fit(chart, name, recurse=False)
        if fresh:
            x0 = PAD if parent is not None else 0.0
            y0 = (HEADER + PAD) if parent is not None else 0.0
            placed = [chart.layout[k.name] for k in kids if k.name not in new]
            if placed:  # below what is there
                x = x0
                y = max(r[1] + r[3] for r in placed) + V_GAP
                for name in fresh:
                    chart.layout[name][0], chart.layout[name][1] = x, y
                    x += chart.layout[name][2] + H_GAP
            else:
                _layered(chart, parent, fresh, x0, y0)
        if parent is not None and parent in chart.layout:
            _grow_to_fit(chart, parent, recurse=False)


H_GAP, V_GAP = 150.0, 80.0
"""Space between sibling states (room for the transition labels)."""


def _leaf_height(chart: EditableChart, name: str) -> float:
    st = chart.state(name)
    lines = sum(1 for k in ("entry", "during", "exit") if getattr(st, k).strip())
    return max(STATE_H, 40.0 + 16.0 * lines)


def _layered(chart: EditableChart, parent: str | None, names: list[str], x0: float, y0: float) -> None:
    """Columns by the number of transitions from the initial state (breadth first); rows in order of discovery."""
    level = set(names)

    def at_level(state: str) -> str | None:
        while state is not None and state not in level:
            state = chart.state(state).parent  # type: ignore[assignment]
        return state

    edges: dict[str, list[str]] = {n: [] for n in names}
    for t in chart.transitions:
        a, b = at_level(t.source), at_level(t.target)
        if a is not None and b is not None and a != b and b not in edges[a]:
            edges[a].append(b)
    first = chart.initial_of(parent)
    order = [first] if first in level else [names[0]]
    depth = {order[0]: 0}
    for n in order:
        for m in edges[n]:
            if m not in depth:
                depth[m] = depth[n] + 1
                order.append(m)
    for n in names:  # not reachable: one more column
        if n not in depth:
            depth[n] = max(depth.values()) + 1
            order.append(n)
    columns: dict[int, list[str]] = {}
    for n in order:
        columns.setdefault(depth[n], []).append(n)
    x = x0
    for col in sorted(columns):
        y = y0
        for n in columns[col]:
            chart.layout[n][0], chart.layout[n][1] = x, y
            y += chart.layout[n][3] + V_GAP
        x += max(chart.layout[n][2] for n in columns[col]) + H_GAP


def _ancestors(chart: EditableChart, name: str) -> list[str]:
    out = []
    p = chart.state(name).parent
    while p is not None:
        out.append(p)
        p = chart.state(p).parent
    return out


def _grow_to_fit(chart: EditableChart, name: str, recurse: bool = True) -> None:
    kids = [chart.layout[k.name] for k in chart.children(name) if k.name in chart.layout]
    if not kids or name not in chart.layout:
        return
    box = chart.layout[name]
    box[2] = max(box[2], max(r[0] + r[2] for r in kids) + PAD)
    box[3] = max(box[3], max(r[1] + r[3] for r in kids) + PAD)
    parent = chart.state(name).parent
    if recurse and parent is not None:
        _grow_to_fit(chart, parent)
