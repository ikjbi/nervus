"""Block registry: maps stable ``type_id`` strings to block classes.

Model files refer to blocks by ``type_id``, and the GUI palette is built from the registry.
"""

from __future__ import annotations

from typing import Any, TypeVar

from nervus.core.block import Block

_REGISTRY: dict[str, type[Block]] = {}

T = TypeVar("T", bound=type[Block])


def register(cls: T) -> T:
    """Class decorator that adds a block class to the registry."""
    if not cls.type_id:
        raise ValueError(f"{cls.__name__} has no type_id")
    if cls.type_id in _REGISTRY and _REGISTRY[cls.type_id] is not cls:
        raise ValueError(f"duplicate block type_id {cls.type_id!r}")
    _REGISTRY[cls.type_id] = cls
    return cls


def get_block_class(type_id: str) -> type[Block]:
    try:
        return _REGISTRY[type_id]
    except KeyError:
        raise KeyError(f"unknown block type {type_id!r}") from None


def create_block(type_id: str, name: str = "", **params: Any) -> Block:
    return get_block_class(type_id)(name, **params)


def block_types() -> dict[str, type[Block]]:
    """All registered block classes, keyed by ``type_id``."""
    return dict(_REGISTRY)


def categories() -> dict[str, list[type[Block]]]:
    """Registered block classes grouped by category, for the library browser."""
    out: dict[str, list[type[Block]]] = {}
    for cls in _REGISTRY.values():
        out.setdefault(cls.category or "Other", []).append(cls)
    return out
