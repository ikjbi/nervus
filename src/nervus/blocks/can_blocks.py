"""CAN Pack and CAN Unpack: convert between CAN frame bytes and physical signal values using a DBC file."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from nervus.blocks.registry import register
from nervus.can import CanMessage, load_dbc, pack, unpack
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "CAN"


@lru_cache(maxsize=32)
def _cached_dbc(path: str, mtime: float) -> dict[str, CanMessage]:
    return load_dbc(path)


class _CanBlock(Block):
    category = CATEGORY
    PARAMS = (
        Param("dbc_file", "", ParamKind.STR, "DBC file (relative paths are relative to the model file)"),
        Param("message", "", ParamKind.STR, "Message name in the DBC file"),
        Param("signals", "", ParamKind.STR, "Signals to use, comma separated (empty = all, in DBC order)"),
    )

    def _path(self) -> Path:
        p = Path(self.params["dbc_file"])
        root = self.diagram.root if self.diagram is not None else None
        source = getattr(root, "source_path", None)
        if not p.is_absolute() and source is not None:
            candidate = Path(source).parent / p
            if candidate.exists():
                return candidate
        return p

    def message(self) -> CanMessage:
        if not self.params["dbc_file"]:
            raise ParameterError("choose a DBC file")
        path = self._path()
        if not path.exists():
            raise ParameterError(f"DBC file not found: {path}")
        messages = _cached_dbc(str(path.resolve()), path.stat().st_mtime)
        name = self.params["message"]
        if name not in messages:
            raise ParameterError(f"message {name!r} not in {path.name}; messages: {', '.join(messages)}")
        return messages[name]

    def selected(self) -> list[Any]:
        try:
            msg = self.message()
        except ParameterError:
            return []
        wanted = [s.strip() for s in self.params["signals"].split(",") if s.strip()]
        if not wanted:
            return list(msg.signals)
        missing = [w for w in wanted if w not in {s.name for s in msg.signals}]
        if missing:
            raise ParameterError(f"signals not in {msg.name}: {', '.join(missing)}")
        return [msg.signal(w) for w in wanted]

    def suggestions(self, param: str) -> list[str]:
        if param == "message" and self.params["dbc_file"]:
            path = self._path()
            if path.exists():
                try:
                    return list(_cached_dbc(str(path.resolve()), path.stat().st_mtime))
                except ParameterError:
                    return []
        if param == "signals":
            try:
                return [", ".join(s.name for s in self.message().signals)]
            except ParameterError:
                return []
        return []

    def validate_params(self) -> None:
        if self.params["dbc_file"] and self.params["message"] and self.diagram is not None:
            self.selected()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        try:
            self._msg = self.message()
            self._signals = self.selected()
        except ParameterError as exc:
            raise ValueError(str(exc)) from exc


@register
class CanUnpack(_CanBlock):
    """Decodes a CAN frame: the input is the 8 data bytes (a vector of width 8), and there is one output per
    signal, in physical units (``raw · factor + offset`` from the DBC file).

    ![Decoding a CAN frame](figures/can_frame.png)

    Intel (little-endian) and Motorola (big-endian) byte order, signed and unsigned signals are supported. The
    block can be generated as C code.
    """

    type_id = "can.unpack"
    label = "CAN Unpack"
    TYPE_RULE = "double"

    def num_outputs(self) -> int:
        return max(1, len(self.selected()))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] != 8:
            raise ValueError("the input must be the 8 data bytes of the frame (width 8)")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([unpack(s, u[0])]) for s in self._signals]


@register
class CanPack(_CanBlock):
    """Encodes a CAN frame: one input per signal (physical units), output = the 8 data bytes (``uint8``).

    Values are converted to the raw integer with rounding to nearest and saturated to the bit field, exactly
    as the generated C code does. Signals that are not selected are sent as 0.
    """

    type_id = "can.pack"
    label = "CAN Pack"

    def num_inputs(self) -> int:
        return max(1, len(self.selected()))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [8]

    def output_types(self, in_types: list[Any]) -> list[Any]:
        from nervus.core.datatypes import parse_datatype

        return [parse_datatype("uint8")]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        values = {s.name: float(v[0]) for s, v in zip(self._signals, u, strict=True)}
        return [pack(self._msg, values)]
