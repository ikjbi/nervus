"""Lookup tables: 1-D curves and 2-D maps, the core of ECU calibration (fuel, ignition, boost, ...)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from nervus.blocks.registry import register
from nervus.core.block import Block, Width, broadcast_widths
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind, output_type_param
from nervus.core.types import Array

CATEGORY = "Lookup Tables"
INTERPOLATION = ("linear", "nearest", "flat")
EXTRAPOLATION = ("clip", "linear")


def _check_breakpoints(bp: Array, name: str) -> None:
    if bp.ndim != 1 or bp.size < 2:
        raise ParameterError(f"{name} must be a vector with at least 2 points")
    if np.any(np.diff(bp) <= 0):
        raise ParameterError(f"{name} must be strictly increasing")


def locate(x: Array, bp: Array, interpolation: str, extrapolation: str) -> tuple[npt.NDArray[np.intp], Array]:
    """For each x, the index ``i`` of the interval [bp[i], bp[i+1]] and the fraction ``f`` within it.

    ``f`` follows the interpolation mode (0/1 for ``nearest``, 0 for ``flat``) and the extrapolation mode
    (clamped to [0, 1] for ``clip``). This is also exactly what generated C code computes.
    """
    n = bp.size
    i = np.clip(np.searchsorted(bp, x, side="right") - 1, 0, n - 2)
    f = (x - bp[i]) / (bp[i + 1] - bp[i])
    if extrapolation == "clip":
        f = np.clip(f, 0.0, 1.0)
    if interpolation == "nearest":
        f = (
            np.where(f >= 0.5, 1.0, 0.0)
            if extrapolation == "clip"
            else np.asarray(np.round(np.clip(f, 0.0, 1.0)), dtype=np.float64)
        )
    elif interpolation == "flat":
        f = np.where(f >= 1.0, 1.0, 0.0) if extrapolation == "clip" else np.where(x >= bp[-1], 1.0, 0.0)
    return i, f


@register
class Lookup1D(Block):
    """1-D lookup table (a calibration *curve*): maps the input through a table of points.

    ![1-D lookup table interpolation](figures/lookup_1d.png)

    For an input between breakpoints $x_i$ and $x_{i+1}$ with linear interpolation:

    $$ y = t_i + \\frac{u - x_i}{x_{i+1} - x_i}\\,(t_{i+1} - t_i) $$

    - *interpolation*: ``linear``; ``nearest`` (closest point); ``flat`` (value of the breakpoint at or
      below the input, a staircase).
    - *extrapolation*: ``clip`` holds the end values; ``linear`` extends the first/last segment.

    Each element of a vector input is looked up separately.
    """

    type_id = "lookup.table_1d"
    label = "1-D Lookup Table"
    category = CATEGORY
    PARAMS = (
        Param("breakpoints", [0.0, 1.0, 2.0], ParamKind.ARRAY, "Input values (strictly increasing)"),
        Param("table", [0.0, 1.0, 4.0], ParamKind.ARRAY, "Output value at each breakpoint"),
        Param("interpolation", "linear", ParamKind.CHOICE, "Between breakpoints", choices=INTERPOLATION),
        Param("extrapolation", "clip", ParamKind.CHOICE, "Outside the breakpoints", choices=EXTRAPOLATION),
        output_type_param("double"),
    )

    def _data(self) -> tuple[Array, Array]:
        bp = np.asarray(self.params["breakpoints"], dtype=float).ravel()
        tab = np.asarray(self.params["table"], dtype=float).ravel()
        return bp, tab

    def validate_params(self) -> None:
        bp, tab = self._data()
        _check_breakpoints(bp, "breakpoints")
        if tab.size != bp.size:
            raise ParameterError(f"table has {tab.size} values but there are {bp.size} breakpoints")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        bp, tab = self._data()
        i, f = locate(u[0], bp, self.params["interpolation"], self.params["extrapolation"])
        return [tab[i] + f * (tab[i + 1] - tab[i])]

    def coverage_outcomes(self) -> list[str]:
        bp, _ = self._data()
        return ["below range", *[f"[{bp[k]:g}, {bp[k + 1]:g}]" for k in range(bp.size - 1)], "above range"]

    def coverage_hits(self, t: float, u: Sequence[Array], y: Sequence[Array], xd: Array) -> list[str]:
        bp, _ = self._data()
        names = self.coverage_outcomes()
        hits = set()
        for x in np.atleast_1d(u[0]):
            if x < bp[0]:
                hits.add(names[0])
            elif x > bp[-1]:
                hits.add(names[-1])
            else:
                k = min(int(np.searchsorted(bp, x, side="right")) - 1, bp.size - 2)
                hits.add(names[1 + k])
        return sorted(hits)


@register
class Lookup2D(Block):
    """2-D lookup table (a calibration *map*), e.g. ignition advance over engine speed and load.

    ![2-D lookup table](figures/lookup_2d.png)

    Input 0 selects the **row** (``row_breakpoints``) and input 1 the **column** (``column_breakpoints``).
    ``table`` has one row per row breakpoint and one column per column breakpoint. With linear interpolation
    the result is bilinear between the four surrounding points:

    $$ y = (1-f_r)(1-f_c)\\,T_{i,j} + (1-f_r) f_c\\,T_{i,j+1} + f_r (1-f_c)\\,T_{i+1,j} + f_r f_c\\,T_{i+1,j+1} $$

    where $f_r$ and $f_c$ are the fractions within the row and column intervals. Interpolation and
    extrapolation work as in the 1-D table.
    """

    type_id = "lookup.table_2d"
    label = "2-D Lookup Table"
    category = CATEGORY
    NUM_INPUTS = 2
    PARAMS = (
        Param("row_breakpoints", [0.0, 1.0], ParamKind.ARRAY, "Breakpoints for input 0 (rows)"),
        Param("column_breakpoints", [0.0, 1.0], ParamKind.ARRAY, "Breakpoints for input 1 (columns)"),
        Param("table", [[0.0, 1.0], [1.0, 2.0]], ParamKind.ARRAY, "Table: rows × columns"),
        Param("interpolation", "linear", ParamKind.CHOICE, "Between breakpoints", choices=("linear", "nearest")),
        Param("extrapolation", "clip", ParamKind.CHOICE, "Outside the breakpoints", choices=EXTRAPOLATION),
        output_type_param("double"),
    )

    def _data(self) -> tuple[Array, Array, Array]:
        r = np.asarray(self.params["row_breakpoints"], dtype=float).ravel()
        c = np.asarray(self.params["column_breakpoints"], dtype=float).ravel()
        tab = np.atleast_2d(np.asarray(self.params["table"], dtype=float))
        return r, c, tab

    def validate_params(self) -> None:
        r, c, tab = self._data()
        _check_breakpoints(r, "row_breakpoints")
        _check_breakpoints(c, "column_breakpoints")
        if tab.shape != (r.size, c.size):
            raise ParameterError(f"table must be {r.size}×{c.size} (rows × columns), got {tab.shape[0]}×{tab.shape[1]}")

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [broadcast_widths(in_widths)]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        r, c, tab = self._data()
        w = self.out_widths[0]
        x0, x1 = np.broadcast_to(u[0], (w,)), np.broadcast_to(u[1], (w,))
        interp, extrap = self.params["interpolation"], self.params["extrapolation"]
        i, fr = locate(x0, r, interp, extrap)
        j, fc = locate(x1, c, interp, extrap)
        y = (
            (1 - fr) * (1 - fc) * tab[i, j]
            + (1 - fr) * fc * tab[i, j + 1]
            + fr * (1 - fc) * tab[i + 1, j]
            + fr * fc * tab[i + 1, j + 1]
        )
        return [np.asarray(y, dtype=float)]
