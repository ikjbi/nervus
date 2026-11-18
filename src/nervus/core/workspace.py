"""The model workspace: named, tunable parameters ("calibration data").

ECU software is code plus calibration. In Nervus, block parameters can refer to workspace variables by name
(``Gain(gain="Kp")``), so the same model runs with different calibrations. A *parameter set* is a file of
variable values that can be saved, loaded and swapped, e.g. one per engine variant.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.errors import ModelError, ParameterError
from nervus.core.expressions import UnknownNameError, format_value, parse_value

PARAMETER_SET_FORMAT = "nervus-parameters"
PARAMETER_SET_EXTENSION = ".nervcal"


def _normalize(value: Any) -> Any:
    """Store numbers as float, arrays as nested lists of floats, expressions as str."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | np.floating | np.integer):
        return float(value)
    arr = np.asarray(value, dtype=np.float64)
    return float(arr) if arr.ndim == 0 else arr.tolist()


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf" if value < 0 else "nan"
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@dataclass
class Variable:
    """A workspace variable. ``value`` is a number, a (nested) list, or an expression string like ``"Kp/Ti"``."""

    name: str
    value: Any
    description: str = ""
    unit: str = ""
    min: float | None = None
    max: float | None = None

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ParameterError(f"invalid variable name {self.name!r}: use letters, digits and _")
        self.value = _normalize(self.value)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "value": _jsonable(self.value)}
        for k in ("description", "unit"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        for k in ("min", "max"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Variable:
        value = d["value"]
        if isinstance(value, str) and value in ("inf", "-inf", "nan"):
            value = float(value)
        return cls(
            name=str(d["name"]),
            value=value,
            description=str(d.get("description", "")),
            unit=str(d.get("unit", "")),
            min=d.get("min"),
            max=d.get("max"),
        )

    @property
    def display_value(self) -> str:
        return self.value if isinstance(self.value, str) else format_value(self.value)


@dataclass
class Workspace:
    """Ordered collection of variables. Behaves like a dict of name -> value."""

    _vars: dict[str, Variable] = field(default_factory=dict)

    # ------------------------------------------------------------------ dict-like access

    def __getitem__(self, name: str) -> Any:
        return self.namespace()[name]

    def __setitem__(self, name: str, value: Any) -> None:
        if name in self._vars:
            self._vars[name].value = _normalize(value)
        else:
            self._vars[name] = Variable(name, value)

    def __delitem__(self, name: str) -> None:
        del self._vars[name]

    def __contains__(self, name: object) -> bool:
        return name in self._vars

    def __iter__(self) -> Iterator[str]:
        return iter(self._vars)

    def __len__(self) -> int:
        return len(self._vars)

    @property
    def variables(self) -> list[Variable]:
        return list(self._vars.values())

    def variable(self, name: str) -> Variable:
        try:
            return self._vars[name]
        except KeyError:
            raise KeyError(f"no workspace variable named {name!r}") from None

    def add(self, var: Variable) -> Variable:
        self._vars[var.name] = var
        return var

    def replace(self, old_name: str, var: Variable) -> None:
        """Replace ``old_name`` by ``var`` (possibly renamed), keeping its position."""
        if var.name != old_name and var.name in self._vars:
            raise ParameterError(f"a variable named {var.name!r} already exists")
        self._vars = {(var.name if k == old_name else k): (var if k == old_name else v) for k, v in self._vars.items()}

    def insert(self, index: int, var: Variable) -> None:
        """Add ``var`` at position ``index`` (used to undo a delete)."""
        items = [v for v in self._vars.values() if v.name != var.name]
        items.insert(max(0, min(index, len(items))), var)
        self._vars = {v.name: v for v in items}

    def rename(self, old: str, new: str) -> None:
        if new in self._vars and new != old:
            raise ParameterError(f"a variable named {new!r} already exists")
        var = self._vars[old]
        Variable(new, 0.0)  # validates the name
        var.name = new
        self._vars = {(new if k == old else k): v for k, v in self._vars.items()}

    def copy(self) -> Workspace:
        return Workspace({k: Variable(**{**v.__dict__}) for k, v in self._vars.items()})

    # ------------------------------------------------------------------ evaluation

    def namespace(self, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Evaluate all variables (expressions may use variables defined before them).

        ``overrides`` replaces values by name (e.g. for a parameter sweep). Raises :class:`ModelError` if a
        variable cannot be evaluated.
        """
        overrides = dict(overrides or {})
        unknown = set(overrides) - set(self._vars)
        if unknown:
            raise ModelError(f"unknown workspace variable(s) in overrides: {', '.join(sorted(unknown))}")
        ns: dict[str, Any] = {}
        for name, var in self._vars.items():
            value = _normalize(overrides[name]) if name in overrides else var.value
            if isinstance(value, str):
                try:
                    value = parse_value(value, ns)
                except UnknownNameError as exc:
                    raise ModelError(f"workspace variable {name!r}: {exc} (define it above {name!r})") from exc
                except ValueError as exc:
                    raise ModelError(f"workspace variable {name!r}: {exc}") from exc
            if isinstance(value, np.ndarray):
                value = value.tolist()
            ns[name] = value
        return ns

    def check_ranges(self, ns: Mapping[str, Any] | None = None) -> list[str]:
        """Messages for variables whose value is outside [min, max]."""
        ns = ns if ns is not None else self.namespace()
        problems = []
        for name, var in self._vars.items():
            arr = np.asarray(ns[name], dtype=float)
            if var.min is not None and np.any(arr < var.min):
                problems.append(f"{name} is below its minimum {var.min:g}")
            if var.max is not None and np.any(arr > var.max):
                problems.append(f"{name} is above its maximum {var.max:g}")
        return problems

    # ------------------------------------------------------------------ parameter sets

    def values(self) -> dict[str, Any]:
        """The raw stored values (numbers, lists or expression strings), by name."""
        return {k: v.value for k, v in self._vars.items()}

    def apply(self, values: Mapping[str, Any], create_missing: bool = False) -> None:
        """Set several variables at once (e.g. from a parameter set). Unknown names are an error unless
        ``create_missing``."""
        unknown = [k for k in values if k not in self._vars]
        if unknown and not create_missing:
            raise ParameterError(f"the model has no variable(s) {', '.join(unknown)}")
        for k, v in values.items():
            self[k] = v

    def to_list(self) -> list[dict[str, Any]]:
        return [v.to_dict() for v in self._vars.values()]

    @classmethod
    def from_list(cls, items: list[Mapping[str, Any]]) -> Workspace:
        ws = cls()
        for d in items:
            ws.add(Variable.from_dict(d))
        return ws


@dataclass
class ParameterSet:
    """A named set of variable values, saved separately from the model (a "calibration")."""

    name: str
    values: dict[str, Any]
    description: str = ""

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(PARAMETER_SET_EXTENSION)
        data = {
            "format": PARAMETER_SET_FORMAT,
            "schema_version": 1,
            "name": self.name,
            "description": self.description,
            "values": {k: _jsonable(_normalize(v)) for k, v in self.values.items()},
        }
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> ParameterSet:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelError(f"cannot read parameter set {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != PARAMETER_SET_FORMAT:
            raise ModelError(f"{path} is not a Nervus parameter set")
        values = {
            k: (float(v) if isinstance(v, str) and v in ("inf", "-inf", "nan") else v)
            for k, v in dict(data.get("values", {})).items()
        }
        return cls(str(data.get("name", Path(path).stem)), values, str(data.get("description", "")))

    @classmethod
    def from_workspace(cls, ws: Workspace, name: str, names: list[str] | None = None) -> ParameterSet:
        vals = ws.values()
        return cls(name, {k: vals[k] for k in (names or list(vals))})
