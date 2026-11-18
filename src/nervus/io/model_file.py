"""Reading and writing model files.

A model file is UTF-8 JSON with the extension ``.nervus``::

    {
      "format": "nervus-model",
      "schema_version": 1,
      "name": "first_order",
      "meta": {},
      "settings": {"t_start": 0.0, "t_final": 10.0, "solver": "auto", ...},
      "blocks": [
        {"name": "u", "type": "sources.step", "params": {"time": 1.0, ...}, "meta": {"position": [0, 0]}}
      ],
      "connections": [
        {"src": "u", "src_port": 0, "dst": "sum", "dst_port": 0}
      ]
    }

Blocks are referred to by their stable ``type_id``. Every parameter is written out, including defaults, so a
file means the same thing even if a default changes later. Output is deterministic (stable ordering,
2-space indent), which keeps git diffs small and readable.

When the format changes, ``SCHEMA_VERSION`` goes up and a function is added to ``MIGRATIONS`` that upgrades a
file from the previous version, so old files keep loading.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nervus.blocks  # noqa: F401  (registers the standard blocks)
from nervus.blocks.registry import get_block_class
from nervus.core.diagram import Diagram
from nervus.core.errors import ModelError, ParameterError
from nervus.core.settings import SimulationSettings

FORMAT = "nervus-model"
SCHEMA_VERSION = 1
FILE_EXTENSION = ".nervus"

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
"""``MIGRATIONS[n]`` upgrades a version-``n`` document to version ``n + 1``."""


def to_dict(diagram: Diagram) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "name": diagram.name,
        "meta": diagram.meta,
        "settings": diagram.settings.to_dict(),
        "blocks": [
            {
                "name": b.name,
                "type": b.type_id,
                "params": b.params_jsonable(),
                **({"meta": b.meta} if b.meta else {}),
            }
            for b in diagram.blocks
        ],
        "connections": [
            {"src": c.src.name, "src_port": c.src_port, "dst": c.dst.name, "dst_port": c.dst_port}
            for c in diagram.connections
        ],
    }


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a model document to the current schema version."""
    version = data.get("schema_version")
    if not isinstance(version, int):
        raise ModelError("model file has no valid schema_version")
    if version > SCHEMA_VERSION:
        raise ModelError(
            f"model file uses schema version {version}, but this version of Nervus only supports up to "
            f"{SCHEMA_VERSION}. Please upgrade Nervus."
        )
    while version < SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise ModelError(f"no migration from schema version {version}")
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


def from_dict(data: dict[str, Any]) -> Diagram:
    if data.get("format") != FORMAT:
        raise ModelError("not a Nervus model file (missing 'format': 'nervus-model')")
    data = migrate(dict(data))
    d = Diagram(str(data.get("name", "untitled")))
    d.meta = dict(data.get("meta", {}))
    try:
        d.settings = SimulationSettings.from_dict(dict(data.get("settings", {})))
    except (TypeError, ValueError) as exc:
        raise ModelError(f"invalid simulation settings: {exc}") from exc
    for entry in data.get("blocks", []):
        name = entry.get("name", "")
        try:
            cls = get_block_class(entry["type"])
        except KeyError as exc:
            raise ModelError(f"block {name!r}: {exc.args[0]}", (name,)) from exc
        try:
            block = cls(name, **entry.get("params", {}))
        except ParameterError as exc:
            raise ModelError(f"block {name!r}: {exc}", (name,)) from exc
        block.meta = dict(entry.get("meta", {}))
        d.add(block)
    for c in data.get("connections", []):
        try:
            src, dst = d.block(c["src"]), d.block(c["dst"])
            d.connect((src, int(c["src_port"])), (dst, int(c["dst_port"])))
        except (KeyError, IndexError) as exc:
            raise ModelError(f"invalid connection {c}: {exc}") from exc
    return d


def dumps(diagram: Diagram) -> str:
    return json.dumps(to_dict(diagram), indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def loads(text: str) -> Diagram:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelError("model file must contain a JSON object")
    return from_dict(data)


def save(diagram: Diagram, path: str | Path) -> Path:
    """Save ``diagram`` to ``path`` (the ``.nervus`` extension is added if missing). Returns the path."""
    p = Path(path)
    if not p.suffix:
        p = p.with_suffix(FILE_EXTENSION)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(dumps(diagram), encoding="utf-8")
    tmp.replace(p)  # atomic: never leave a half-written model file
    return p


def load(path: str | Path) -> Diagram:
    return loads(Path(path).read_text(encoding="utf-8"))
