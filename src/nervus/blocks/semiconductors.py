"""Semiconductor devices with SPICE-like models: diodes, bipolar transistors, MOSFETs and op-amps.

These components are nonlinear. At every solve the network linearizes them around the last iterate (each
becomes conductances plus current sources, the *companion model*) and repeats until the solution converges:
the Newton-Raphson method that SPICE uses. Junction voltages are limited between iterations (SPICE's pnjlim) so
the exponentials do not overshoot.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import ClassVar

import numpy as np

from nervus.blocks.registry import register
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array
from nervus.physical.network import VT, PhysicalBlock, Stamper, exp_junction, junction_limit

CATEGORY = "Semiconductors"
G_DEVICE = 1e-12
"""A tiny conductance across every junction (SPICE's GMIN): it keeps blocked parts of a circuit solvable."""


def _terminal(s: Stamper, node: int, f0: float, jac: dict[int, float], v0: dict[int, float]) -> None:
    """Stamp a terminal current f(v) leaving ``node`` into the device, linearized: f0 + Σ J (v - v0)."""
    if node < 0:
        return
    rest = f0
    for j, g in jac.items():
        s.add(node, j, g)
        rest -= g * v0.get(j, 0.0)
    s.b[node] -= rest


class _Semiconductor(PhysicalBlock):
    category = CATEGORY
    NONLINEAR = True

    def __init__(self, name: str = "", **params: object) -> None:
        super().__init__(name, **params)
        self._v: dict[str, float] = {}  # junction voltages of the last iterate (for the step limiting)


@register
class SemiconductorDiode(_Semiconductor):
    """A diode with the Shockley equation, like SPICE's diode model:

    $$ i = I_s\\left(e^{v/(N V_T)} - 1\\right) - I_{BV}\\, e^{-(v + BV)/(N V_T)} $$

    The second term is the reverse breakdown (a **Zener** diode): set *BV* to the Zener voltage. Ports ``p``
    (anode) and ``n`` (cathode). Typical values:

    | Device | Is [A] | N | BV [V] |
    |---|---|---|---|
    | 1N4148 small-signal | 2.5e-9 | 1.75 | 100 |
    | 1N4007 rectifier | 7e-9 | 1.8 | 1000 |
    | red LED (≈ 1.9 V at 20 mA) | 1e-18 | 1.9 | 5 |
    | Zener 5.1 V | 1e-14 | 1 | 5.1 |
    """

    type_id = "semiconductors.diode"
    label = "Diode"
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (("p", "electrical"), ("n", "electrical"))
    NUM_OUTPUTS = 0
    PARAMS = (
        Param("Is", 1e-14, ParamKind.FLOAT, "Saturation current", "A"),
        Param("N", 1.0, ParamKind.FLOAT, "Emission coefficient"),
        Param("BV", math.inf, ParamKind.FLOAT, "Reverse breakdown voltage (Zener voltage)", "V"),
        Param("IBV", 1e-3, ParamKind.FLOAT, "Current at the breakdown voltage", "A"),
    )

    def validate_params(self) -> None:
        if not (self.params["Is"] > 0 and self.params["N"] > 0 and self.params["BV"] > 0):
            raise ParameterError("Is, N and BV must be > 0")

    def current(self, v: float) -> tuple[float, float]:
        """Current and conductance at the junction voltage ``v``."""
        nvt = self.params["N"] * VT
        i, g = exp_junction(v, self.params["Is"], nvt)
        bv = self.params["BV"]
        if math.isfinite(bv):
            ir, gr = exp_junction(-(v + bv), self.params["IBV"], nvt)
            i -= ir + self.params["IBV"]  # exp_junction subtracts 1·IBV; the breakdown term has no "-1"
            g += gr
        return i + G_DEVICE * v, g + G_DEVICE

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        a, k = nodes
        nvt = self.params["N"] * VT
        vcrit = nvt * math.log(nvt / (math.sqrt(2.0) * self.params["Is"]))
        v = s.across_guess(a) - s.across_guess(k)
        bv = self.params["BV"]
        if s.guess is not None:
            if math.isfinite(bv) and v < -bv / 2:  # towards breakdown: limit the reverse junction instead
                vcrit_r = nvt * math.log(nvt / (math.sqrt(2.0) * self.params["IBV"]))
                vr = junction_limit(-(v + bv), -(self._v.get("d", 0.0) + bv), nvt, vcrit_r)
                v = s.limit(v, -vr - bv)
            else:
                v = s.limit(v, junction_limit(v, self._v.get("d", 0.0), nvt, vcrit))
        self._v["d"] = v
        i, g = self.current(v)
        s.conductance(a, k, g)
        s.flow(a, k, i - g * v)


@register
class BJT(_Semiconductor):
    """A bipolar transistor (Ebers-Moll transport model), NPN or PNP. Ports ``c`` (collector), ``b`` (base),
    ``e`` (emitter):

    $$ I_C = I_s\\left(e^{V_{BE}/V_T} - e^{V_{BC}/V_T}\\right) - \\frac{I_s}{\\beta_R}\\left(e^{V_{BC}/V_T} - 1\\right),
       \\qquad I_B = \\frac{I_s}{\\beta_F}\\left(e^{V_{BE}/V_T} - 1\\right) + \\frac{I_s}{\\beta_R}\\left(e^{V_{BC}/V_T} - 1\\right) $$

    In the active region the collector current is β_F times the base current; as a switch (a relay driver)
    the transistor saturates with a small collector-emitter voltage. A small NPN like the 2N2222: Is = 1e-14,
    β_F = 200.
    """

    type_id = "semiconductors.bjt"
    label = "Bipolar Transistor"
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (("c", "electrical"), ("b", "electrical"), ("e", "electrical"))
    PARAMS = (
        Param("type", "NPN", ParamKind.CHOICE, "Polarity", choices=("NPN", "PNP")),
        Param("Is", 1e-14, ParamKind.FLOAT, "Saturation current", "A"),
        Param("BF", 100.0, ParamKind.FLOAT, "Forward current gain β_F"),
        Param("BR", 1.0, ParamKind.FLOAT, "Reverse current gain β_R"),
    )

    def validate_params(self) -> None:
        if not (self.params["Is"] > 0 and self.params["BF"] > 0 and self.params["BR"] > 0):
            raise ParameterError("Is, BF and BR must be > 0")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        c, b, e = nodes
        p = 1.0 if self.params["type"] == "NPN" else -1.0
        i_s, bf, br = self.params["Is"], self.params["BF"], self.params["BR"]
        vcrit = VT * math.log(VT / (math.sqrt(2.0) * i_s))
        vc, vb, ve = (s.across_guess(n) for n in nodes)
        vbe, vbc = p * (vb - ve), p * (vb - vc)
        if s.guess is not None:
            vbe = s.limit(vbe, junction_limit(vbe, self._v.get("be", 0.0), VT, vcrit))
            vbc = s.limit(vbc, junction_limit(vbc, self._v.get("bc", 0.0), VT, vcrit))
        self._v["be"], self._v["bc"] = vbe, vbc
        i_f, g_f = exp_junction(vbe, i_s, VT)
        i_r, g_r = exp_junction(vbc, i_s, VT)
        ic = i_f - i_r - i_r / br
        ib = i_f / bf + i_r / br
        # Derivatives of the currents leaving the nodes into the device (for NPN; the signs work out for PNP).
        dic_dbe, dic_dbc = g_f, -g_r * (1.0 + 1.0 / br)
        dib_dbe, dib_dbc = g_f / bf, g_r / br
        # The node voltages (limited junction voltages, mapped back) the linearization is made at.
        v0 = {b: vb, e: vb - p * vbe, c: vb - p * vbc}
        jc = {b: dic_dbe + dic_dbc, e: -dic_dbe, c: -dic_dbc}
        jb = {b: dib_dbe + dib_dbc, e: -dib_dbe, c: -dib_dbc}
        je = {n: -(jc.get(n, 0.0) + jb.get(n, 0.0)) for n in (b, e, c)}
        _terminal(s, c, p * ic, jc, v0)
        _terminal(s, b, p * ib, jb, v0)
        _terminal(s, e, -p * (ic + ib), je, v0)
        s.conductance(b, e, G_DEVICE)
        s.conductance(b, c, G_DEVICE)


@register
class MOSFET(_Semiconductor):
    """A MOSFET (SPICE level 1, square law), N- or P-channel. Ports ``d`` (drain), ``g`` (gate), ``s`` (source);
    no current flows into the gate:

    $$ I_D = \\begin{cases} 0 & V_{GS} \\le V_{th} \\\\ K\\left((V_{GS} - V_{th})V_{DS} - V_{DS}^2/2\\right)(1 + \\lambda V_{DS}) & V_{DS} < V_{GS} - V_{th} \\\\
       \\frac{K}{2}(V_{GS} - V_{th})^2 (1 + \\lambda V_{DS}) & \\text{saturation} \\end{cases} $$

    *K* = μC_ox·W/L. A logic-level switch like a 2N7000: Vth = 2 V, K = 0.1 A/V²; a power MOSFET driving a
    motor: Vth = 3 V, K = 20 A/V². The device is symmetric: with V_DS < 0 drain and source swap roles.
    """

    type_id = "semiconductors.mosfet"
    label = "MOSFET"
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (("d", "electrical"), ("g", "electrical"), ("s", "electrical"))
    PARAMS = (
        Param("type", "N", ParamKind.CHOICE, "Channel", choices=("N", "P")),
        Param("K", 0.1, ParamKind.FLOAT, "Transconductance parameter μCox·W/L", "A/V²"),
        Param("Vth", 2.0, ParamKind.FLOAT, "Threshold voltage (positive for both types)", "V"),
        Param("lam", 0.0, ParamKind.FLOAT, "Channel-length modulation λ", "1/V"),
    )

    def validate_params(self) -> None:
        if not self.params["K"] > 0:
            raise ParameterError("K must be > 0")

    def _id(self, vgs: float, vds: float) -> tuple[float, float, float]:
        """Drain current and its derivatives gm = dI/dVgs, gds = dI/dVds (for V_DS ≥ 0)."""
        k, vth, lam = self.params["K"], self.params["Vth"], self.params["lam"]
        vov = vgs - vth
        if vov <= 0:
            return 0.0, 0.0, 0.0
        if vds < vov:
            core = vov * vds - vds * vds / 2
            i = k * core * (1 + lam * vds)
            return i, k * vds * (1 + lam * vds), k * (vov - vds) * (1 + lam * vds) + k * core * lam
        i = k / 2 * vov * vov * (1 + lam * vds)
        return i, k * vov * (1 + lam * vds), k / 2 * vov * vov * lam

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        d, g, src = nodes
        p = 1.0 if self.params["type"] == "N" else -1.0
        vd, vg, vs = (s.across_guess(n) for n in nodes)
        if p * (vd - vs) < 0:  # symmetric device: the lower node is the source
            d, src, vd, vs = src, d, vs, vd
        vgs, vds = p * (vg - vs), p * (vd - vs)
        if s.guess is not None and "gs" in self._v:  # limit big gate steps (SPICE's fetlim, simplified)
            vgs = s.limit(vgs, self._v["gs"] + float(np.clip(vgs - self._v["gs"], -2.0, 2.0)))
        self._v["gs"] = vgs
        i, gm, gds = self._id(vgs, vds)
        v0 = {g: vs + p * vgs, d: vs + p * vds, src: vs}
        jd = {g: gm, d: gds, src: -(gm + gds)}
        _terminal(s, d, p * i, jd, v0)
        _terminal(s, src, -p * i, {n: -v for n, v in jd.items()}, v0)
        s.conductance(d, src, G_DEVICE)


@register
class OpAmp(_Semiconductor):
    """An operational amplifier: high gain, and the output limited to its supply rails:

    $$ v_{out} = v_{mid} + v_{half} \\tanh\\left(\\frac{A\\,(v_+ - v_-)}{v_{half}}\\right) $$

    with $v_{mid} = (V_{pos} + V_{neg})/2$ and $v_{half} = (V_{pos} - V_{neg})/2$.

    No current flows into the inputs ``plus`` and ``minus``; the output ``out`` is referenced to ground and can
    deliver any current. With negative feedback it is an amplifier or an active filter; without, a comparator.
    """

    type_id = "semiconductors.opamp"
    label = "Op-Amp"
    N_BRANCHES = 1
    PORTS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("plus", "electrical"),
        ("minus", "electrical"),
        ("out", "electrical"),
    )
    PARAMS = (
        Param("A", 1e5, ParamKind.FLOAT, "Open-loop gain"),
        Param("Vpos", 15.0, ParamKind.FLOAT, "Positive output rail", "V"),
        Param("Vneg", -15.0, ParamKind.FLOAT, "Negative output rail", "V"),
    )

    def validate_params(self) -> None:
        if not (self.params["A"] > 0 and self.params["Vpos"] > self.params["Vneg"]):
            raise ParameterError("A must be > 0 and Vpos > Vneg")

    def stamp(self, s: Stamper, nodes: list[int], branches: list[int], x: Array, u: Sequence[float]) -> None:
        plus, minus, out = nodes
        a, hi, lo = self.params["A"], self.params["Vpos"], self.params["Vneg"]
        mid, half = (hi + lo) / 2, (hi - lo) / 2
        vd = s.across_guess(plus) - s.across_guess(minus)
        th = math.tanh(a * vd / half)
        f, df = mid + half * th, a * (1 - th * th)
        r = s.branch(branches[0])
        # v_out - df (v+ - v-) = f(vd0) - df vd0; the branch current flows from out through the amplifier.
        s.add(r, out, 1.0)
        s.add(r, plus, -df)
        s.add(r, minus, df)
        s.add(out, r, 1.0)
        s.b[r] = f - df * vd
