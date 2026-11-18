"""Test cases: reproducible simulations with inputs, parameters and pass/fail checks.

A test case is saved with the model. It says *what to run* (input signals for the top-level In blocks,
workspace parameter overrides or a parameter-set file, a stop time) and *what must be true* (checks on the
results). Running it gives pass/fail plus the simulation result for inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nervus.core.errors import ParameterError
from nervus.core.signals import Signal

CHECK_KINDS = {
    "bounds": "signal stays within [lower, upper] (optionally only between t_from and t_to)",
    "final_value": "signal's last value is value ± tolerance",
    "reaches": "signal reaches value (rises above, or falls below for direction=below) before time `before`",
    "max": "signal's maximum is at most value",
    "min": "signal's minimum is at least value",
    "baseline": "signal matches a saved result file (path) within tolerance",
}


@dataclass
class Check:
    """One pass/fail criterion on a simulation result. See ``CHECK_KINDS`` for the kinds and their arguments."""

    kind: str
    signal: str
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CHECK_KINDS:
            raise ParameterError(f"unknown check kind {self.kind!r}; use one of {', '.join(CHECK_KINDS)}")

    def describe(self) -> str:
        a = self.args
        if self.kind == "bounds":
            window = ""
            if "t_from" in a or "t_to" in a:
                window = f" for {a.get('t_from', 0):g} ≤ t ≤ {a.get('t_to', 'end')}"
            return f"{a.get('lower', '-inf')} ≤ {self.signal} ≤ {a.get('upper', 'inf')}{window}"
        if self.kind == "final_value":
            return f"{self.signal}(end) = {a.get('value')} ± {a.get('tolerance', 1e-6)}"
        if self.kind == "reaches":
            word = "falls below" if a.get("direction") == "below" else "reaches"
            return f"{self.signal} {word} {a.get('value')} before t = {a.get('before')}"
        if self.kind == "max":
            return f"max({self.signal}) ≤ {a.get('value')}"
        if self.kind == "min":
            return f"min({self.signal}) ≥ {a.get('value')}"
        return f"{self.signal} matches {a.get('path')} ± {a.get('tolerance', 1e-6)}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "signal": self.signal, **self.args}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Check:
        d = dict(d)
        return cls(d.pop("kind"), d.pop("signal"), d)


@dataclass
class TestCase:
    __test__ = False  # not a pytest test class

    name: str
    description: str = ""
    inputs: dict[str, Signal] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    parameter_set: str = ""
    """Optional path to a ``.nervcal`` file (relative to the model file), applied before ``parameters``."""
    stop_time: float | None = None
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.description:
            d["description"] = self.description
        if self.stop_time is not None:
            d["stop_time"] = self.stop_time
        if self.parameter_set:
            d["parameter_set"] = self.parameter_set
        if self.parameters:
            d["parameters"] = {
                k: (np.asarray(v).tolist() if not isinstance(v, str) else v) for k, v in self.parameters.items()
            }
        d["inputs"] = {k: s.to_dict() for k, s in self.inputs.items()}
        d["checks"] = [c.to_dict() for c in self.checks]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TestCase:
        return cls(
            name=str(d["name"]),
            description=str(d.get("description", "")),
            inputs={k: Signal.from_dict(v) for k, v in dict(d.get("inputs", {})).items()},
            parameters=dict(d.get("parameters", {})),
            parameter_set=str(d.get("parameter_set", "")),
            stop_time=d.get("stop_time"),
            checks=[Check.from_dict(c) for c in d.get("checks", [])],
        )
