"""Model Advisor: static checks for modelling practices that matter in ECU software.

These are not errors (the model compiles and simulates), but they are common sources of bugs or of code
that is hard to review. Run it from the editor (Analysis → Model Advisor) or from Python::

    from nervus.advisor import advise
    for f in advise(model):
        print(f)
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import numpy as np

from nervus.core.block import Block
from nervus.core.diagram import Diagram
from nervus.core.errors import NervusError
from nervus.core.expressions import names_in


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # "warning" or "info"
    message: str
    blocks: tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f" [{', '.join(self.blocks)}]" if self.blocks else ""
        return f"{self.severity.upper():7s} {self.rule}: {self.message}{where}"


RULES: dict[str, tuple[str, Callable[[Diagram, dict[str, object]], Iterator[Finding]]]] = {}


def rule(
    rule_id: str, description: str
) -> Callable[[Callable[..., Iterator[Finding]]], Callable[..., Iterator[Finding]]]:
    def deco(fn: Callable[..., Iterator[Finding]]) -> Callable[..., Iterator[Finding]]:
        RULES[rule_id] = (description, fn)
        return fn

    return deco


def _types(diagram: Diagram) -> dict[str, object]:
    """Compiled facts used by several rules (empty if the model does not compile)."""
    from nervus.sim.compiler import compile_diagram

    try:
        m = compile_diagram(diagram)
    except NervusError:
        return {}
    in_types = {}
    in_kinds = {}
    for i, name in enumerate(m.names):
        in_types[name] = [m.out_types[s][p] for s, p in m.inputs[i]]
        in_kinds[name] = [(m.kinds[s], m.blocks[s]) for s, _p in m.inputs[i]]
    return {"model": m, "in_types": in_types, "in_kinds": in_kinds}


@rule("float-equality", "== or != on floating-point signals")
def _float_equality(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    in_types: dict[str, list[object]] = facts.get("in_types", {})  # type: ignore[assignment]
    for path, b in d.walk():
        if b.type_id in ("logic.relational", "logic.compare_to_constant") and b.params["operator"] in ("==", "!="):
            types = in_types.get(path, [])
            if not types or any(not (t.is_integer or t.kind == "boolean") for t in types):  # type: ignore[attr-defined]
                yield Finding(
                    "float-equality",
                    "warning",
                    f"'{b.params['operator']}' on a floating-point signal is fragile: rounding makes exact "
                    "equality unlikely. Compare with a tolerance, or convert to an integer type first.",
                    (path,),
                )


@rule("division", "Product blocks that divide (division by zero)")
def _division(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for path, b in d.walk():
        if b.type_id == "math.product" and "/" in b.params["ops"]:
            yield Finding(
                "division",
                "info",
                "this block divides; make sure the divisor can never be zero (e.g. "
                "limit it with a Saturation or MinMax).",
                (path,),
            )


@rule("chart-unreachable", "chart states that can never be entered")
def _chart_unreachable(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for path, b in d.walk():
        spec = getattr(b, "spec", None)
        if b.type_id != "charts.state_chart" or spec is None:
            continue
        targets = {t.target for t in spec.transitions} | {spec.initial}
        for k, s in enumerate(spec.states):
            if k not in targets:
                yield Finding(
                    "chart-unreachable",
                    "warning",
                    f"state '{s.name}' has no incoming transition and is not the initial state, so it is never active.",
                    (path,),
                )


@rule("chart-shadowed", "chart transitions after an unconditional one")
def _chart_shadowed(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for path, b in d.walk():
        spec = getattr(b, "spec", None)
        if b.type_id != "charts.state_chart" or spec is None:
            continue
        seen_true: set[int] = set()
        for t in spec.transitions:
            if t.source in seen_true:
                yield Finding(
                    "chart-shadowed",
                    "warning",
                    f"transition {spec.states[t.source].name} -> {spec.states[t.target].name} comes after an "
                    "always-true transition from the same state and can never fire.",
                    (path,),
                )
            if t.guard_src.strip().lower() in ("true", "1"):
                seen_true.add(t.source)


@rule("antiwindup", "PI controllers with output limits but no anti-windup")
def _antiwindup(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for path, b in d.walk():
        if b.type_id in ("control.pid", "control.discrete_pid"):
            p = b.params
            limited = np.isfinite(p["upper"]) or np.isfinite(p["lower"])
            if p["I"] != 0 and limited and p["anti_windup"] == "none":
                yield Finding(
                    "antiwindup",
                    "warning",
                    "the output is limited but anti_windup is 'none': the integral "
                    "term winds up while saturated and causes overshoot. Use 'clamping'.",
                    (path,),
                )
            if p["I"] != 0 and not limited:
                yield Finding(
                    "antiwindup",
                    "info",
                    "the controller has an integral term but no output limits; real "
                    "actuators saturate, so model the limits.",
                    (path,),
                )


@rule("implicit-sampling", "discrete blocks reading continuous signals directly")
def _implicit_sampling(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    from nervus.sim.compiler import Kind

    in_kinds: dict[str, list[tuple[object, Block]]] = facts.get("in_kinds", {})  # type: ignore[assignment]
    m = facts.get("model")
    if m is None:
        return
    for i, name in enumerate(m.names):  # type: ignore[attr-defined]
        b = m.blocks[i]  # type: ignore[attr-defined]
        if m.kinds[i] is not Kind.DISCRETE or b.type_id == "discrete.zero_order_hold":  # type: ignore[attr-defined]
            continue
        if any(
            k is Kind.CONTINUOUS and src.type_id not in ("ports.inport", "sources.constant")
            for k, src in in_kinds.get(name, [])
        ):
            yield Finding(
                "implicit-sampling",
                "info",
                "a discrete block reads a continuous-time signal directly; put a "
                "Zero-Order Hold in front so the sampling is explicit (as on the ECU).",
                (name,),
            )


@rule("workspace-docs", "workspace variables without unit or description")
def _workspace_docs(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for v in d.workspace.variables:
        if not v.unit or not v.description:
            missing = " and ".join(x for x, ok in (("a unit", v.unit), ("a description", v.description)) if not ok)
            yield Finding(
                "workspace-docs",
                "info",
                f"workspace variable '{v.name}' has no {missing}; calibration engineers see these in the A2L file.",
            )


@rule("workspace-unused", "workspace variables that no block uses")
def _workspace_unused(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    used: set[str] = set()
    for _path, b in d.walk():
        for expr in b.expressions.values():
            used |= names_in(expr)
    for v in d.workspace.variables:
        if isinstance(v.value, str):
            used |= names_in(v.value)
    for v in d.workspace.variables:
        if v.name not in used:
            yield Finding("workspace-unused", "info", f"workspace variable '{v.name}' is not used by any block.")


@rule("lookup-extrapolation", "lookup tables that extrapolate linearly")
def _lookup_extrapolation(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    for path, b in d.walk():
        if b.type_id in ("lookup.table_1d", "lookup.table_2d") and b.params["extrapolation"] == "linear":
            yield Finding(
                "lookup-extrapolation",
                "info",
                "linear extrapolation can give values far outside the "
                "calibrated table; 'clip' is the usual choice in ECU maps.",
                (path,),
            )


@rule("default-names", "blocks in subsystems with default names")
def _default_names(d: Diagram, facts: dict[str, object]) -> Iterator[Finding]:
    import re

    for path, b in d.walk():
        if (
            "/" in path
            and b.label
            and re.fullmatch(re.escape(b.label.replace(" ", "")) + r"\d*", b.name.replace(" ", ""))
        ):
            yield Finding(
                "default-names",
                "info",
                f"'{b.name}' has a default name; descriptive names make generated code and reviews easier to follow.",
                (path,),
            )


def advise(diagram: Diagram, rules: list[str] | None = None) -> list[Finding]:
    """Run the Model Advisor rules (all by default) and return the findings, warnings first."""
    facts = _types(diagram)
    findings: list[Finding] = []
    for rule_id, (_desc, fn) in RULES.items():
        if rules is None or rule_id in rules:
            findings.extend(fn(diagram, facts))
    return sorted(findings, key=lambda f: (f.severity != "warning", f.rule))
