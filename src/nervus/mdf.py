"""ASAM MDF4 (``.mf4``) files: the measurement format of INCA, CANape, vehicle loggers and test benches.

    from nervus.mdf import read_mdf, write_mdf
    write_mdf(result, "run.mf4")                 # a simulation result, e.g. to compare in CANape
    rec = read_mdf("drive.mf4", ["n_engine"])    # a vehicle log as a SimResult
    FromWorkspace(time=rec.t, data=rec["n_engine"])

Uses ``asammdf`` (``uv sync --extra mdf``). An MDF file stores channels in **groups**, each with its own time
base (a CAN logger writes every message at its own rate). :func:`read_mdf` puts every channel on one time base:
the times of the group with the most samples, or a fixed *raster*; others are linearly interpolated (and held
before their first and after their last sample).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.errors import NervusError
from nervus.sim.result import SimResult


def _asammdf() -> Any:
    try:
        import asammdf
    except ImportError as exc:
        raise NervusError("MDF4 files need asammdf: uv sync --extra mdf") from exc
    return asammdf


def write_mdf(result: SimResult, path: str | Path, names: Iterable[str] | None = None,
              units: dict[str, str] | None = None, comment: str = "Nervus simulation") -> Path:  # fmt: skip
    """Write signals of a result to an MDF 4.10 file (all on the result's time base). Vector signals become one
    channel per element, ``name[k]``. Returns the path."""
    asammdf = _asammdf()
    units = units or {}
    t = np.asarray(result.t, dtype=float)
    keep = np.concatenate([[True], np.diff(t) > 0])  # MDF time must increase: drop repeated sample instants
    sigs = []
    for name in names if names is not None else result.names():
        data = np.asarray(result[name], dtype=float)
        columns = [(name, data)] if data.ndim == 1 else [(f"{name}[{k}]", data[:, k]) for k in range(data.shape[1])]
        for ch, values in columns:
            sigs.append(asammdf.Signal(values[keep], t[keep], name=ch, unit=units.get(name, "")))
    mdf = asammdf.MDF(version="4.10")
    if sigs:
        mdf.append(sigs, comment=comment)
    p = Path(path)
    if p.suffix.lower() not in (".mf4", ".mdf"):
        p = p.with_suffix(".mf4")
    mdf.save(p, overwrite=True)
    mdf.close()
    return p


def mdf_channels(path: str | Path) -> dict[str, str]:
    """The channel names in a file, with their units (time channels left out)."""
    asammdf = _asammdf()
    with asammdf.MDF(str(path)) as mdf:
        out = {}
        for group in mdf.groups:
            for ch in group.channels:
                if ch.channel_type != 2 and ch.name not in out:  # 2 = master (time) channel
                    out[ch.name] = getattr(ch, "unit", "") or ""
        return out


def read_mdf(path: str | Path, channels: Iterable[str] | None = None, raster: float | None = None) -> SimResult:
    """Read channels (all numeric ones if ``None``) into a :class:`SimResult` on one time base (see the module
    docs). Each channel is a signal named like the channel."""
    asammdf = _asammdf()
    with asammdf.MDF(str(path)) as mdf:
        wanted = list(channels) if channels is not None else list(mdf_channels(path))
        found = {}
        for name in wanted:
            try:
                sig = mdf.get(name)
            except Exception as exc:  # asammdf raises MdfException for missing or ambiguous names
                if channels is not None:
                    raise NervusError(f"{Path(path).name}: no channel {name!r} ({exc})") from exc
                continue
            values = np.asarray(sig.samples)
            if values.dtype.kind not in "biuf" or values.ndim != 1 or len(sig.timestamps) == 0:
                continue  # text, byte arrays, structures
            found[name] = (np.asarray(sig.timestamps, dtype=float), values.astype(float))
    if not found:
        raise NervusError(f"{Path(path).name}: no numeric channels to read")
    if raster:
        lo = min(ts[0] for ts, _ in found.values())
        hi = max(ts[-1] for ts, _ in found.values())
        t = np.arange(lo, hi + raster / 2, raster)
    else:
        t = max((ts for ts, _ in found.values()), key=len)
    signals = {f"{n}:0": np.interp(t, ts, v).reshape(-1, 1) for n, (ts, v) in found.items()}
    return SimResult(t=t, signals=signals)
