"""Stateflow charts as Nervus State Charts: the chart XML of an ``.slx`` (or of an R2019b+ ``.mdl``) in the chart
language of :mod:`nervus.blocks.chart`.

    from nervus.stateflow import convert_chart
    result = convert_chart(xml_text)
    print(result.definition)   # the chart language
    print(result.notes)        # what was approximated or left out

A Stateflow chart is stored as ``simulink/stateflow/chart_<id>.xml``: nested ``<state>`` elements (``OR_STATE``
inside an exclusive parent, ``AND_STATE`` inside a parallel one), ``<transition>`` elements from one ``SSID`` to
another (a default transition has no source), ``<junction>`` elements, and ``<data>`` and ``<event>`` elements with
their scope. The translation:

- states keep their names (made unique where two parents have children with the same name), their ``entry``,
  ``during`` and ``exit`` actions and their positions; a parallel chart becomes one parallel top state;
- transitions keep their order (Stateflow's execution order); a path through connective junctions becomes one
  transition per way through, with the guards joined by ``and`` and the actions in order;
- the labels ``event[condition]{condition action}/transition action`` become ``guard / action``;
  ``after(n, sec)`` becomes ``t_in_state >= n``, ``after(n, tick)`` ``after(n)``;
- MATLAB (``~=``, ``&&``, ``~``, ``%``) and C (``!=``, ``||``, ``!``, ``x++``, ``//``) action language both work;
- a default transition's action runs in the enclosing state's entry action; at the chart's top level its constant
  assignments become initial values;
- ``first_sample: enter`` gives Stateflow's start (the first sample only enters the chart), unless the chart
  executes at initialization.

What the chart language does not have (graphical and MATLAB functions, input events, inner transitions, vectors) is
listed in the notes; the rest of the chart is still imported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from nervus.blocks.chart import parse_chart
from nervus.core.errors import NervusError, ParameterError

_KEYWORDS = {"entry": "entry", "en": "entry", "during": "during", "du": "during", "exit": "exit", "ex": "exit"}
_FUNCS = {"abs", "min", "max", "sqrt", "exp", "log", "sin", "cos", "floor", "ceil"}


@dataclass
class ChartImport:
    definition: str
    """The chart language."""
    sample_time: float
    """-1 to inherit."""
    layout: dict[str, list[float]] = field(default_factory=dict)
    """State boxes, relative to the enclosing state (the State Chart block's ``chart_layout``)."""
    notes: list[str] = field(default_factory=list)
    """What was approximated or not imported."""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class _State:
    ssid: str
    name: str
    parent: str | None
    kind: str
    """OR_STATE, AND_STATE, FUNC_STATE, GROUP_STATE (a box)."""
    parallel: bool
    order: int
    position: list[float]
    actions: dict[str, list[str]] = field(default_factory=lambda: {"entry": [], "during": [], "exit": []})
    history: bool = False
    initial: str | None = None


@dataclass
class _Transition:
    ssid: str
    src: str | None
    dst: str
    label: str
    order: int
    owner: str | None = None
    """The state the transition is drawn in (``None``: the chart): Stateflow leaves and enters every state below it."""


def _p(el: ET.Element, name: str, default: str = "") -> str:
    for p in el.findall("P"):
        if p.get("Name") == name:
            return p.text or ""
    return default


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", text)]


# ---------------------------------------------------------------------------- expressions and actions


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return "\n".join(re.split(r"%|//", line, maxsplit=1)[0] for line in text.splitlines())


def _split_top(text: str, seps: str) -> list[str]:
    """Split at any of ``seps`` outside parentheses and brackets."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch in seps and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _call_args(text: str, start: int) -> tuple[list[str], int]:
    """The arguments of the call whose '(' is at ``start``, and the index after its ')'."""
    depth = 0
    for k in range(start, len(text)):
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                return [a.strip() for a in _split_top(text[start + 1 : k], ",")], k + 1
    raise ValueError(f"unbalanced parentheses in '{text}'")


def _temporal(text: str, notes: list[str], where: str) -> str:
    """``after(n, sec)`` and the other temporal operators in the chart language."""
    out, k = "", 0
    for m in re.finditer(r"\b(after|before|at|every|duration|temporalCount|elapsed|count)\s*\(", text):
        if m.start() < k:
            continue
        args, end = _call_args(text, m.end() - 1)
        op = m.group(1)
        unit = args[1] if len(args) > 1 else "tick"
        scale = {"sec": "", "msec": " / 1000", "usec": " / 1000000"}.get(unit)
        factor = {"sec": 1.0, "msec": 1e-3, "usec": 1e-6}.get(unit)
        try:
            n = f"{float(args[0]) * factor:g}" if factor is not None else ""
        except ValueError:  # an expression: kept, scaled
            simple = re.fullmatch(r"[\w.]+", args[0]) is not None
            n = args[0] if simple and not scale else f"({args[0]}){scale}" if scale else f"({args[0]})"
        if op == "after" and scale is not None:
            rep = f"t_in_state >= {n}"
        elif op == "after" and unit == "tick":
            rep = f"after({args[0]})"
        elif op == "before" and scale is not None:
            rep = f"t_in_state < {n}"
        elif op == "before" and unit == "tick":
            rep = f"(not after({args[0]}))"
        elif op in ("temporalCount", "elapsed") and (args[0] if args else "") in ("sec", ""):
            rep = "t_in_state"
        else:
            notes.append(f"{where}: {text[m.start() : end]} is not supported (taken as false)")
            rep = "0"
        out += text[k : m.start()] + rep
        k = end
    return out + text[k:]


def expression(text: str, notes: list[str], where: str) -> str:
    """A Stateflow expression (MATLAB or C action language) in the chart language."""
    s = _temporal(_strip_comments(text).strip(), notes, where)
    s = s.replace("&&", " and ").replace("||", " or ").replace("~=", "!=")
    s = re.sub(r"!(?!=)", " not ", s)
    s = re.sub(r"~(?!=)", " not ", s)
    s = re.sub(r"(?<![=!<>])&(?!&)", " and ", s)
    s = re.sub(r"(?<!\|)\|(?!\|)", " or ", s)
    s = s.replace("^", "**").replace(".*", "*").replace("./", "/")
    s = re.sub(r"\bmod\s*\(", "_mod(", s)
    while "_mod(" in s:  # mod(a, b) -> ((a) % (b)), as MATLAB's mod (the sign of b)
        k = s.index("_mod(")
        args, end = _call_args(s, k + 4)
        s = s[:k] + f"(({args[0]}) % ({args[1]}))" + s[end:]
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", s):
        name = m.group(1)
        if name not in _FUNCS and name not in ("after", "send", "and", "or", "not"):
            notes.append(f"{where}: the function {name}() is not supported")
    return re.sub(r"\s+", " ", s).strip()


def actions(text: str, notes: list[str], where: str, events: set[str]) -> list[str]:
    """Statements (``;``, ``,`` or new lines between them) in the chart language."""
    out = []
    for raw in _split_top(_strip_comments(text).replace("\n", ";"), ";,"):
        st = raw.strip()
        if not st:
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*)\s*(\+\+|--)", st)
        if m:
            out.append(f"{m.group(1)} {'+' if m.group(2) == '++' else '-'}= 1")
            continue
        m = re.fullmatch(r"send\s*\(\s*([A-Za-z_]\w*)\s*\)", st)
        if m or st in events:
            out.append(f"send({m.group(1) if m else st})")
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*)\s*([-+*/]?=)(?!=)\s*(.+)", st, flags=re.S)
        if m:
            out.append(f"{m.group(1)} {m.group(2)} {expression(m.group(3), notes, where)}")
            continue
        notes.append(f"{where}: the statement '{st}' is not supported (left out)")
    return out


def _state_label(label: str, notes: list[str]) -> tuple[str, dict[str, list[str]], list[str]]:
    """The name, the actions by kind (as Stateflow text) and the unsupported parts of a state's label."""
    text = _strip_comments(label)
    m = re.match(r"\s*([A-Za-z_]\w*)\s*/?", text)
    if not m:
        raise NervusError(f"a state without a name: {label!r}")
    name, rest = m.group(1), text[m.end() :]
    found: dict[str, list[str]] = {"entry": [], "during": [], "exit": []}
    other: list[str] = []
    pattern = re.compile(r"(?:(?<=[\s;,])|^)((?:entry|en|during|du|exit|ex|on\s+[^:]+|bind)"
                         r"(?:\s*,\s*(?:entry|en|during|du|exit|ex))*)\s*:")  # fmt: skip
    marks = list(pattern.finditer(rest))
    if marks and rest[: marks[0].start()].strip():  # actions before the first keyword are entry actions
        found["entry"].append(rest[: marks[0].start()])
    if not marks and rest.strip():
        found["entry"].append(rest)
    for k, mk in enumerate(marks):
        body = rest[mk.end() : marks[k + 1].start() if k + 1 < len(marks) else len(rest)]
        kinds = [w.strip() for w in mk.group(1).split(",")]
        for kind in kinds:
            if kind in _KEYWORDS:
                found[_KEYWORDS[kind]].append(body)
            else:
                other.append(f"{kind}: {body.strip()}")
    return name, found, other


def _transition_label(label: str, notes: list[str], where: str, events: set[str]) -> tuple[str, list[str]]:
    """``trigger[condition]{condition action}/transition action`` as (guard, actions)."""
    text = _strip_comments(label).strip()
    k, depth = 0, 0
    while k < len(text):  # the trigger: up to the first [, { or / outside parentheses
        ch = text[k]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and ch in "[{/":
            break
        k += 1
    trigger, rest = text[:k].strip(), text[k:]
    guards = []
    if trigger:
        for part in _split_top(trigger, "|"):
            part = part.strip()
            if re.fullmatch(r"[A-Za-z_]\w*", part) and part not in events:
                notes.append(f"{where}: the event '{part}' is not a local event of the chart (taken as false)")
                guards.append("0")
            else:
                guards.append(expression(part, notes, where))
        guards = [" or ".join(f"({g})" for g in guards) if len(guards) > 1 else guards[0]]
    m = re.match(r"\s*\[(.*?)\]\s*(?=\{|/|$)", rest, flags=re.S)
    if m:
        guards.append(expression(m.group(1), notes, where))
        rest = rest[m.end() :]
    acts: list[str] = []
    m = re.match(r"\s*\{(.*?)\}\s*(?=/|$)", rest, flags=re.S)
    if m:
        acts += actions(m.group(1), notes, where, events)
        rest = rest[m.end() :]
    rest = rest.strip()
    if rest.startswith("/"):
        body = rest[1:].strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        acts += actions(body, notes, where, events)
    elif rest:
        notes.append(f"{where}: could not read '{rest}' in the label '{label}'")
    guard = " and ".join(f"({g})" if " or " in g else g for g in guards)
    return guard, acts


# ---------------------------------------------------------------------------- the chart


def convert_chart(xml: str | bytes, name: str = "chart") -> ChartImport:
    """The State Chart definition for a Stateflow ``chart_<id>.xml``. Raises :class:`NervusError` if the chart
    cannot be made into a valid chart (the notes say what was left out otherwise)."""
    root = ET.fromstring(xml)
    if root.tag != "chart":
        raise NervusError("not a Stateflow chart")
    chart_name = _p(root, "name", name)
    notes: list[str] = []
    sample = _p(root, "sampleTime", "-1").strip()
    update = _p(root, "updateMethod", "INHERITED")
    sample_time = -1.0
    if update == "DISCRETE":
        nums = _numbers(sample)
        sample_time = nums[0] if nums else -1.0
        if not nums:
            notes.append(f"sample time '{sample}' is not a number: the chart inherits its rate")
    elif update == "CONTINUOUS":
        notes.append("a continuous-time chart runs at a discrete rate in Nervus (set the block's sample time)")

    states: dict[str, _State] = {}
    transitions: list[_Transition] = []
    junctions: dict[str, str] = {}  # SSID -> parent state SSID ("" at the chart)
    history: set[str] = set()
    data: list[tuple[str, str, str, str, int]] = []  # name, scope, initial value, type, port
    events: dict[str, str] = {}
    parallel_chart = _p(root, "decomposition") == "SET_CHART"

    def walk(el: ET.Element, parent: str | None) -> None:
        children = el.find("Children")
        if children is None:
            return
        for k, c in enumerate(children):
            ssid = c.get("SSID", "")
            if c.tag == "state":
                kind = _p(c, "type", "OR_STATE")
                st = _State(ssid, "", parent, kind, _p(c, "decomposition") == "SET_STATE",
                            int(_numbers(_p(c, "executionOrder", "0"))[0] if _p(c, "executionOrder") else k),
                            _numbers(_p(c, "position", "0 0 100 60"))[:4])  # fmt: skip
                label = _p(c, "labelString", "")
                if kind == "FUNC_STATE":
                    fn = label.split("\n")[0].strip()
                    notes.append(f"function '{fn}' is not imported (graphical, MATLAB and Simulink functions)")
                    continue
                if kind == "GROUP_STATE":
                    notes.append(f"the box '{label.splitlines()[0] if label else ssid}' is not kept: its states are "
                                 "imported into its parent")  # fmt: skip
                    walk(c, parent)
                    continue
                try:
                    st.name, found, other = _state_label(label, notes)
                except NervusError as exc:
                    notes.append(str(exc))
                    continue
                st.actions = found
                for o in other:
                    notes.append(f"state {st.name}: '{o}' is not supported")
                states[ssid] = st
                walk(c, ssid)
            elif c.tag == "transition":
                src = c.find("src")
                dst = c.find("dst")
                src_id = _p(src, "SSID") if src is not None else ""
                dst_id = _p(dst, "SSID") if dst is not None else ""
                if not dst_id:
                    continue
                order = _numbers(_p(c, "executionOrder", "0"))
                transitions.append(_Transition(ssid, src_id or None, dst_id, _p(c, "labelString", ""),
                                               int(order[0]) if order else 0, parent))  # fmt: skip
            elif c.tag == "junction":
                if _p(c, "type") == "HISTORY_JUNCTION":
                    if parent is not None:
                        history.add(parent)
                else:
                    junctions[ssid] = parent or ""
            elif c.tag == "data":
                scope = _p(c, "scope", "LOCAL_DATA")
                props = c.find("props")
                init = ""
                size = ""
                if props is not None:
                    init = _p(props, "initialValue", "")
                    arr = props.find("array")
                    size = _p(arr, "size", "") if arr is not None else ""
                if size.strip() not in ("", "-1", "1", "[1 1]", "1 1"):
                    notes.append(f"data '{c.get('name')}' is a vector or matrix ({size}): Nervus charts use scalars")
                dtype = _p(c, "dataType", "double")
                port = _numbers(_p(c, "port", ""))
                data.append((c.get("name", ""), scope, init, dtype, int(port[0]) if port else 0))
            elif c.tag == "event":
                events[c.get("name", "")] = _p(c, "scope", "LOCAL_EVENT")
            elif c.tag in ("target", "subviewS"):
                continue
            else:
                walk(c, parent)

    walk(root, None)
    if not states:
        raise NervusError(f"chart '{chart_name}' has no states (a flow chart without states is not imported)")
    for h in history:
        if h in states:
            states[h].history = True

    local_events = {n for n, sc in events.items() if sc == "LOCAL_EVENT"}
    for n, sc in events.items():
        if sc != "LOCAL_EVENT":
            notes.append(f"event '{n}' ({sc.lower().replace('_', ' ')}) is not supported: Nervus charts run at "
                         "their sample time")  # fmt: skip

    # unique, valid names (Stateflow allows the same name under different parents)
    taken: set[str] = set()
    for st in sorted(states.values(), key=lambda s: _depth(states, s.ssid)):
        base = st.name
        if base in taken:
            parent = states[st.parent].name if st.parent in states else chart_name
            new = f"{parent}_{base}"
            k = 2
            while new in taken:
                new = f"{parent}_{base}_{k}"
                k += 1
            notes.append(f"state '{base}' in '{parent}' renamed to '{new}' (state names must be unique in Nervus)")
            st.name = new
        taken.add(st.name)

    # data
    inputs = sorted([(port, k, n) for k, (n, sc, *_r, port) in enumerate(data) if sc == "INPUT_DATA"])
    outputs = sorted([(port, k, n, init) for k, (n, sc, init, _t, port) in enumerate(data) if sc == "OUTPUT_DATA"])
    locals_ = [(n, init) for n, sc, init, *_r in data if sc in ("LOCAL_DATA", "CONSTANT_DATA")]
    params = [n for n, sc, *_r in data if sc == "PARAMETER_DATA"]
    for n, sc, _i, dtype, _p2 in data:
        if sc in ("DATA_STORE_MEMORY_DATA", "TEMPORARY_DATA", "IMPORTED_DATA", "EXPORTED_DATA"):
            notes.append(f"data '{n}' ({sc.lower().replace('_', ' ')}) is not supported")
        if dtype not in ("double", "Inherit: Same as Simulink", "") and sc != "PARAMETER_DATA":
            notes.append(f"data '{n}' is {dtype} in Stateflow and computed as double in Nervus")
    initial_values: dict[str, str] = {}
    for n, init in [(o[2], o[3]) for o in outputs] + locals_:
        initial_values[n] = _initial(init, n, notes)

    # transitions, with paths through junctions resolved
    out_of: dict[str, list[_Transition]] = {}
    for t in transitions:
        if t.src is not None:
            out_of.setdefault(t.src, []).append(t)
    for ts in out_of.values():
        ts.sort(key=lambda t: t.order)

    def paths(t: _Transition, depth: int = 0) -> list[tuple[str, list[str], list[str], str | None]]:
        """(destination, guards, actions, the outermost state the segments are drawn in) for each way."""
        where = f"transition {_describe(states, t)}"
        guard, acts = _transition_label(t.label, notes, where, local_events)
        if t.dst in states:
            return [(t.dst, [guard] if guard else [], acts, t.owner)]
        if t.dst not in junctions:
            notes.append(f"{where}: its destination {t.dst} is not imported")
            return []
        if depth > 30:
            raise NervusError("a loop through junctions (flow-chart loops are not imported)")
        nxt = out_of.get(t.dst, [])
        if not nxt:
            notes.append(f"{where}: ends at a junction (a flow-chart path without a state) and is left out")
        out = []
        for t2 in nxt:
            for dst, g2, a2, own in paths(t2, depth + 1):
                outer = t.owner if _depth(states, t.owner) < _depth(states, own) else own
                out.append((dst, ([guard] if guard else []) + g2, acts + a2, outer))
        return out

    lines_t: list[str] = []
    entry_extra: dict[str, list[str]] = {}
    top_default_actions: list[str] = []
    top_initial: str | None = None
    for t in transitions:
        if t.src is not None:
            continue
        where = f"the default transition into {_describe(states, t)}"
        ways = paths(t)
        if not ways:
            continue
        dst, guards, acts, _own = ways[0]
        if len(ways) > 1 or guards:
            notes.append(f"{where}: a conditional default path is not supported; the first way is taken")
        owner = states[dst].parent
        if owner is None:
            top_initial = dst
            top_default_actions += acts
        else:
            states[owner].initial = dst
            entry_extra.setdefault(owner, []).extend(acts)
    for src_id in sorted(out_of, key=lambda s: _depth(states, s) if s in states else 0):
        if src_id not in states:
            continue
        for t in out_of[src_id]:
            for dst, guards, acts, owner in paths(t):
                within = _within(states, src_id, dst, owner)
                if _is_ancestor(states, src_id, dst):
                    notes.append(f"transition {_describe(states, t)}: an inner transition; Nervus leaves and "
                                 f"enters '{states[src_id].name}' again")  # fmt: skip
                g = " and ".join(f"({x})" if (" or " in x and len(guards) > 1) else x for x in guards) or "true"
                act = "; ".join(acts)
                scope = f" within {within}" if within else ""
                lines_t.append(f"transition {states[src_id].name} -> {states[dst].name}{scope}: {g}"
                               + (f" / {act}" if act else ""))  # fmt: skip

    # top-level default actions: constant assignments become initial values
    for a in top_default_actions:
        m = re.fullmatch(r"(\w+) = (-?[\d.eE+-]+)", a)
        if m and m.group(1) in initial_values:
            initial_values[m.group(1)] = m.group(2)
        else:
            notes.append(f"the chart's default transition action '{a}' is not imported (only constant initial "
                         "values are)")  # fmt: skip

    # the text
    lines: list[str] = [f"# Imported from the Stateflow chart '{chart_name}'"]
    if inputs:
        lines.append("input " + ", ".join(n for *_r, n in inputs))
    if outputs:
        lines.append("output " + ", ".join(_decl(n, initial_values[n]) for *_r, n, _i in outputs))
    if locals_:
        lines.append("local " + ", ".join(_decl(n, initial_values[n]) for n, _i in locals_))
    if params:
        lines.append("param " + ", ".join(params))
    if local_events:
        lines.append("event " + ", ".join(n for n in events if n in local_events))
    if _p(root, "executeAtInitialization", "0") != "1":
        lines.append("first_sample: enter")
    top_states = [s for s in states.values() if s.parent is None]
    synthetic = None
    if parallel_chart:
        synthetic = re.sub(r"\W", "_", chart_name) or "chart"
        while synthetic in taken:
            synthetic += "_"
    elif top_initial is not None and top_initial in states and _first(states, None) != top_initial:
        lines.append(f"initial {states[top_initial].name}")

    def write(st: _State, depth: int) -> None:
        pad = "  " * depth
        lines.append("")
        lines.append(f"{pad}state {st.name}{' parallel' if st.parallel else ''}")
        for kind in ("entry", "during", "exit"):
            stmts: list[str] = []
            for body in st.actions[kind]:
                stmts += actions(body, notes, f"state {st.name} {kind}", local_events)
            if kind == "entry":
                stmts += entry_extra.get(st.ssid, [])
            if stmts:
                lines.append(f"{pad}  {kind}: {'; '.join(stmts)}")
        if st.history:
            lines.append(f"{pad}  history")
        kids = _children(states, st.ssid)
        if kids and st.initial is not None and kids[0].ssid != st.initial and not st.parallel:
            lines.append(f"{pad}  initial {states[st.initial].name}")
        for c in kids:
            write(c, depth + 1)

    if synthetic:
        lines.append("")
        lines.append(f"state {synthetic} parallel")
        for st in sorted(top_states, key=lambda s: s.order):
            write(st, 1)
    else:
        for st in _children(states, None):
            write(st, 0)
    if lines_t:
        lines.append("")
        lines += lines_t
    text = "\n".join(lines) + "\n"
    try:
        parse_chart(text)
    except ParameterError as exc:
        raise NervusError(f"the imported chart '{chart_name}' is not valid: {exc}\n{text}") from exc

    layout = _layout(states, synthetic)
    return ChartImport(text, sample_time, layout, notes, [n for *_r, n in inputs], [o[2] for o in outputs])


def _initial(init: str, name: str, notes: list[str]) -> str:
    init = init.strip()
    if not init:
        return "0"
    try:
        float(init)
        return init
    except ValueError:
        if init in ("true", "false"):
            return "1" if init == "true" else "0"
        notes.append(f"the initial value '{init}' of '{name}' is not a number: 0 is used")
        return "0"


def _decl(name: str, init: str) -> str:
    return f"{name} = {init}" if init not in ("", "0", "0.0") else name


def _ancestors(states: dict[str, _State], ssid: str) -> list[str | None]:
    """The states containing ``ssid`` (innermost first), then ``None`` for the chart."""
    out: list[str | None] = []
    p = states[ssid].parent
    while p is not None:
        out.append(p)
        p = states[p].parent
    return [*out, None]


def _within(states: dict[str, _State], src: str, dst: str, owner: str | None) -> str:
    """``chart`` or the name of the state the transition belongs to, if it is above the innermost state containing
    both ends (else '': the default scope). In a parallel chart, a transition drawn at the top leaves every region
    and enters them again."""
    anc_d = _ancestors(states, dst)
    lca = next(x for x in _ancestors(states, src) if x in anc_d)
    if owner is not None and owner not in states:
        return ""
    if owner == lca or owner not in (*_ancestors(states, src), None) or owner not in anc_d:
        return ""
    return "chart" if owner is None else states[owner].name


def _depth(states: dict[str, _State], ssid: str | None) -> int:
    d = 0
    while ssid in states and states[ssid].parent is not None:
        ssid = states[ssid].parent
        d += 1
    return d


def _is_ancestor(states: dict[str, _State], a: str, b: str) -> bool:
    p = states[b].parent
    while p is not None:
        if p == a:
            return True
        p = states[p].parent
    return False


def _children(states: dict[str, _State], parent: str | None) -> list[_State]:
    """In the order Stateflow runs them: by execution order for parallel states, else as stored with the
    default (initial) state first."""
    kids = [s for s in states.values() if s.parent == parent]
    if any(s.kind == "AND_STATE" for s in kids):
        return sorted(kids, key=lambda s: s.order)
    init = states[parent].initial if parent is not None and parent in states else None
    return sorted(kids, key=lambda s: 0 if s.ssid == init else 1)


def _first(states: dict[str, _State], parent: str | None) -> str | None:
    kids = _children(states, parent)
    return kids[0].ssid if kids else None


def _describe(states: dict[str, _State], t: _Transition) -> str:
    def nm(x: str | None) -> str:
        return states[x].name if x in states else ("default" if x is None else f"junction {x}")

    return f"{nm(t.src)} -> {nm(t.dst)}" + (f" [{t.label.strip()}]" if t.label.strip() else "")


def _layout(states: dict[str, _State], synthetic: str | None) -> dict[str, list[float]]:
    """Boxes relative to the enclosing state, with the chart's top-left at (0, 0)."""
    if not states:
        return {}
    x0 = min(s.position[0] for s in states.values() if len(s.position) == 4)
    y0 = min(s.position[1] for s in states.values() if len(s.position) == 4)
    pad = 20.0 if synthetic else 0.0
    out: dict[str, list[float]] = {}
    for s in states.values():
        if len(s.position) != 4:
            continue
        x, y, w, h = s.position
        if s.parent in states and len(states[s.parent].position) == 4:
            px, py = states[s.parent].position[:2]
            out[s.name] = [x - px, y - py, w, h]
        else:
            out[s.name] = [x - x0 + pad, y - y0 + pad + (34.0 if synthetic else 0.0), w, h]
    if synthetic:
        tops = [out[s.name] for s in states.values() if s.parent is None and s.name in out]
        if tops:
            out[synthetic] = [0.0, 0.0, max(r[0] + r[2] for r in tops) + pad, max(r[1] + r[3] for r in tops) + pad]
    return out
