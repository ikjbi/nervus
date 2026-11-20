"""The data dictionary: signal objects, with a data type, unit, range and description.

Workspace variables describe **parameters**. Signal objects describe **signals**: a block output is bound to a
signal object by giving it the object's name (``Diagram.name_signal``, or *Name Signal…* on a wire). Then

- the compiler checks that the output has the object's data type (unless the object says ``inherit``);
- the simulation checks the range and reports values outside [min, max] as warnings;
- results can be read by the signal name (``res["engine_speed"]``);
- generated A2L files list the signal as a measurement with its name, unit and limits.

Signal names are model-wide: each may be given to one block output.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from nervus.core.errors import ParameterError

if TYPE_CHECKING:
    from nervus.core.block import Block
    from nervus.core.diagram import Diagram

META_KEY = "signal_names"
"""``block.meta["signal_names"]``: output port (as a string) → signal name."""


@dataclass
class SignalObject:
    name: str
    data_type: str = "inherit"
    """``inherit`` (any type) or a type the output must have, e.g. ``uint16`` or ``fixdt(0,16,3)``."""
    unit: str = ""
    min: float | None = None
    max: float | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ParameterError(f"invalid signal name {self.name!r}: use letters, digits and _")
        self.data_type = (self.data_type or "inherit").strip()
        from nervus.core.datatypes import parse_datatype

        parse_datatype(self.data_type)  # raises ParameterError for an unknown type
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ParameterError(f"signal {self.name!r}: min {self.min:g} is above max {self.max:g}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "data_type": self.data_type}
        for k in ("unit", "min", "max", "description"):
            v = getattr(self, k)
            if v not in ("", None):
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignalObject:
        return cls(str(d["name"]), str(d.get("data_type", "inherit")), str(d.get("unit", "")), d.get("min"),
                   d.get("max"), str(d.get("description", "")))  # fmt: skip

    def range_problems(self, t: np.ndarray, values: np.ndarray) -> list[str]:
        """Messages if ``values`` leave [min, max] (the first time and the extreme value)."""
        out = []
        v = np.asarray(values, dtype=float).reshape(len(t), -1)
        if self.max is not None and np.any(v > self.max):
            k = int(np.argmax(np.any(v > self.max, axis=1)))
            out.append(f"signal {self.name} is above its maximum {self.max:g} from t = {t[k]:g} s "
                       f"(up to {np.max(v):g}{' ' + self.unit if self.unit else ''})")  # fmt: skip
        if self.min is not None and np.any(v < self.min):
            k = int(np.argmax(np.any(v < self.min, axis=1)))
            out.append(f"signal {self.name} is below its minimum {self.min:g} from t = {t[k]:g} s "
                       f"(down to {np.min(v):g}{' ' + self.unit if self.unit else ''})")  # fmt: skip
        return out


@dataclass
class DataDictionary:
    """The signal objects of a model, by name."""

    _objects: dict[str, SignalObject] = field(default_factory=dict)

    def __contains__(self, name: object) -> bool:
        return name in self._objects

    def __iter__(self) -> Iterator[str]:
        return iter(self._objects)

    def __len__(self) -> int:
        return len(self._objects)

    def __getitem__(self, name: str) -> SignalObject:
        try:
            return self._objects[name]
        except KeyError:
            raise KeyError(f"no signal object named {name!r}") from None

    def get(self, name: str, default: SignalObject | None = None) -> SignalObject | None:
        return self._objects.get(name, default)

    @property
    def objects(self) -> list[SignalObject]:
        return list(self._objects.values())

    def add(self, obj: SignalObject) -> SignalObject:
        self._objects[obj.name] = obj
        return obj

    def remove(self, name: str) -> SignalObject:
        return self._objects.pop(name)

    def replace(self, old_name: str, obj: SignalObject, index: int | None = None) -> None:
        """Put ``obj`` in place of ``old_name`` (or add it at ``index``), keeping the order."""
        items = [(k, v) for k, v in self._objects.items() if k != old_name and k != obj.name]
        pos = list(self._objects).index(old_name) if old_name in self._objects else len(items)
        items.insert(pos if index is None else max(0, min(index, len(items))), (obj.name, obj))
        self._objects = dict(items)

    def copy(self) -> DataDictionary:
        return DataDictionary({k: SignalObject(**v.__dict__) for k, v in self._objects.items()})

    def to_list(self) -> list[dict[str, Any]]:
        return [o.to_dict() for o in self._objects.values()]

    @classmethod
    def from_list(cls, items: list[dict[str, Any]]) -> DataDictionary:
        dd = cls()
        for d in items:
            dd.add(SignalObject.from_dict(d))
        return dd


def signal_names(block: Block) -> dict[int, str]:
    """The names given to a block's outputs, by output port."""
    return {int(k): str(v) for k, v in dict(block.meta.get(META_KEY, {})).items()}


def named_signals(diagram: Diagram) -> dict[str, tuple[str, int]]:
    """Every named block output of a model: signal name → (block path, output port)."""
    out: dict[str, tuple[str, int]] = {}
    for path, b in diagram.walk():
        for port, name in signal_names(b).items():
            if name in out:
                other = out[name]
                raise ParameterError(f"signal name {name!r} is used twice: {other[0]}:{other[1]} and {path}:{port}")
            out[name] = (path, port)
    return out
