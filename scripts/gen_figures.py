"""Generate the explanatory block figures used in the docs and the in-app help.

Run: uv run python scripts/gen_figures.py

Each figure is written to ``src/nervus/gui/resources/figures/`` (bundled with the app) and copied to
``docs/images/blocks/`` (for the GitHub/MkDocs docs). Response plots are simulated with Nervus itself.
Figures have a transparent background and neutral grey text so they read well in light and dark themes.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from nervus import Diagram, simulate
from nervus.blocks import (
    PID,
    Constant,
    Debounce,
    DiscreteFilter,
    DiscreteIntegrator,
    EdgeDetect,
    Integrator,
    Pulse,
    RateLimiter,
    Relay,
    Scope,
    Sine,
    Step,
    Sum,
    TransferFunction,
    ZeroOrderHold,
)

ROOT = Path(__file__).parent.parent
APP_DIR = ROOT / "src" / "nervus" / "gui" / "resources" / "figures"
DOCS_DIR = ROOT / "docs" / "images" / "blocks"

# Categorical palette (validated for colour-vision deficiency), used in this fixed order.
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK = "#7d7c76"  # neutral grey: readable on light and dark backgrounds
GRID = "#9a99924d"

plt.rcParams.update(
    {
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "lines.linewidth": 2.0,
        "legend.frameon": False,
        "savefig.transparent": True,
        "mathtext.fontset": "dejavusans",
    }
)

FIGURES: dict[str, Callable[[], plt.Figure]] = {}


def figure(name: str) -> Callable[[Callable[[], plt.Figure]], Callable[[], plt.Figure]]:
    def deco(fn: Callable[[], plt.Figure]) -> Callable[[], plt.Figure]:
        FIGURES[name] = fn
        return fn

    return deco


# ---------------------------------------------------------------------------- schematic helpers


def box(
    ax: Axes, x: float, y: float, w: float, h: float, text: str, color: str = INK, fill: str = "none", size: float = 11
) -> None:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", ec=color, fc=fill, lw=1.6))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=color)


def arrow(
    ax: Axes, a: tuple[float, float], b: tuple[float, float], color: str = INK, text: str = "", above: bool = True
) -> None:
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, lw=1.5, color=color))
    if text:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ax.text(
            mx,
            my + (0.12 if above else -0.12),
            text,
            ha="center",
            va="bottom" if above else "top",
            fontsize=10,
            color=color,
        )


def vector(ax: Axes, x: float, y: float, labels: list[str], color: str, cell: float = 0.42) -> None:
    """A column vector drawn as stacked cells, top to bottom."""
    for i, lab in enumerate(labels):
        yy = y - i * cell
        ax.add_patch(
            FancyBboxPatch((x, yy - cell), cell * 1.6, cell, boxstyle="square,pad=0", ec=color, fc=color + "22", lw=1.2)
        )
        ax.text(x + cell * 0.8, yy - cell / 2, lab, ha="center", va="center", fontsize=10, color=color)


def schematic(
    width: float, height: float, xlim: tuple[float, float], ylim: tuple[float, float]
) -> tuple[plt.Figure, Axes]:
    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def run(d: Diagram, t: float, **kw: object):  # type: ignore[no-untyped-def]
    return simulate(d, t, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- figures


@figure("gain_modes")
def gain_modes() -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.3))
    titles = ["Scalar gain", "Vector gain (elementwise)", "Matrix gain (matrix)"]
    for ax, title in zip(axes, titles, strict=True):
        ax.set_xlim(0, 6)
        ax.set_ylim(-2.2, 1.2)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(title, color=INK, fontsize=11, pad=4)

    ax = axes[0]
    vector(ax, 0.2, 0.6, ["$u_1$", "$u_2$", "$u_3$"], C1)
    ax.text(1.4, -0.03, r"$\times$", fontsize=14, ha="center", va="center", color=INK)
    vector(ax, 1.8, 0.18, ["$k$"], C2)
    ax.text(3.0, -0.03, "=", fontsize=14, ha="center", va="center", color=INK)
    vector(ax, 3.4, 0.6, ["$k\\,u_1$", "$k\\,u_2$", "$k\\,u_3$"], C3)
    ax.text(3.0, -1.55, "gain = 2  →  every element doubled", ha="center", fontsize=9, color=INK)

    ax = axes[1]
    vector(ax, 0.2, 0.6, ["$u_1$", "$u_2$", "$u_3$"], C1)
    ax.text(1.4, -0.03, r"$\odot$", fontsize=14, ha="center", va="center", color=INK)
    vector(ax, 1.8, 0.6, ["$k_1$", "$k_2$", "$k_3$"], C2)
    ax.text(3.0, -0.03, "=", fontsize=14, ha="center", va="center", color=INK)
    vector(ax, 3.4, 0.6, ["$k_1u_1$", "$k_2u_2$", "$k_3u_3$"], C3)
    ax.text(3.0, -1.55, "gain = [1 2 3]  →  element by element", ha="center", fontsize=9, color=INK)

    ax = axes[2]
    cell = 0.42
    for r in range(2):
        for c in range(3):
            x, y = 0.1 + c * cell * 1.3, 0.39 - r * cell
            ax.add_patch(
                FancyBboxPatch((x, y - cell), cell * 1.3, cell, boxstyle="square,pad=0", ec=C2, fc=C2 + "22", lw=1.2)
            )
            ax.text(
                x + cell * 0.65, y - cell / 2, f"$K_{{{r + 1}{c + 1}}}$", ha="center", va="center", fontsize=9, color=C2
            )
    ax.text(1.95, -0.03, "@", fontsize=13, ha="center", va="center", color=INK)
    vector(ax, 2.25, 0.6, ["$u_1$", "$u_2$", "$u_3$"], C1)
    ax.text(3.55, -0.03, "=", fontsize=14, ha="center", va="center", color=INK)
    vector(ax, 3.85, 0.39, ["$y_1$", "$y_2$"], C3)
    ax.text(3.0, -1.55, "K is 2×3, u has 3 elements  →  y has 2", ha="center", fontsize=9, color=INK)
    fig.tight_layout()
    return fig


@figure("sum_signs")
def sum_signs() -> plt.Figure:
    fig, ax = schematic(6.0, 2.6, (0, 9), (-0.6, 3.3))
    for i, (lab, sign) in enumerate((("$u_0$", "+"), ("$u_1$", "−"), ("$u_2$", "+"))):
        y = 2.6 - i * 1.0
        arrow(ax, (0.6, y), (3.3, 1.6 + (1 - i) * 0.45), C1)
        ax.text(0.3, y, lab, ha="center", va="center", color=C1, fontsize=12)
        ax.text(3.0, 1.6 + (1 - i) * 0.45 + 0.08, sign, ha="right", va="bottom", fontsize=12, color=INK)
    box(ax, 3.35, 0.9, 1.4, 1.4, "Σ", size=18)
    arrow(ax, (4.75, 1.6), (6.4, 1.6), C3)
    ax.text(6.5, 1.6, r"$y = u_0 - u_1 + u_2$", va="center", fontsize=12, color=C3)
    ax.text(4.05, 0.35, 'signs = "+-+"', ha="center", fontsize=10, color=INK)
    return fig


@figure("saturation")
def saturation() -> plt.Figure:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.0))
    u = np.linspace(-2, 2, 400)
    a1.plot(u, np.clip(u, -0.5, 1.0), color=C1)
    a1.plot(u, u, "--", color=INK, lw=1, alpha=0.6)
    a1.axhline(1.0, color=C2, lw=1, ls=":")
    a1.axhline(-0.5, color=C2, lw=1, ls=":")
    a1.text(-1.9, 1.05, "upper", color=C2, va="bottom")
    a1.text(-1.9, -0.55, "lower", color=C2, va="top")
    a1.set_xlabel("input u")
    a1.set_ylabel("output y")
    a1.set_title("Characteristic", color=INK)
    t = np.linspace(0, 10, 500)
    a2.plot(t, 1.6 * np.sin(t), color=INK, lw=1, ls="--", label="input")
    a2.plot(t, np.clip(1.6 * np.sin(t), -0.5, 1.0), color=C1, label="output")
    a2.set_xlabel("time [s]")
    a2.set_title("In time", color=INK)
    a2.legend(loc="lower left")
    fig.tight_layout()
    return fig


def _source_plot(t: np.ndarray, y: np.ndarray, title: str, notes: list[tuple[float, float, str]]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(6.0, 2.6))
    ax.plot(t, y, color=C1)
    for x, yy, text in notes:
        ax.annotate(text, (x, yy), color=C2, fontsize=10)
    ax.set_xlabel("time [s]")
    ax.set_title(title, color=INK)
    fig.tight_layout()
    return fig


@figure("step")
def step() -> plt.Figure:
    t = np.linspace(0, 3, 601)
    y = np.where(t >= 1.0, 2.0, 0.5)
    fig = _source_plot(t, y, "Step: time = 1, initial = 0.5, final = 2", [])
    ax = fig.axes[0]
    ax.axvline(1.0, color=C2, ls=":", lw=1)
    ax.text(1.03, 1.2, "time", color=C2)
    ax.text(0.1, 0.6, "initial", color=C2)
    ax.text(2.0, 2.06, "final", color=C2)
    ax.set_ylim(0, 2.4)
    return fig


@figure("ramp")
def ramp() -> plt.Figure:
    t = np.linspace(0, 3, 301)
    y = 0.5 + 1.5 * np.maximum(0, t - 1)
    fig = _source_plot(t, y, "Ramp: slope = 1.5, start_time = 1, initial = 0.5", [])
    ax = fig.axes[0]
    ax.axvline(1.0, color=C2, ls=":", lw=1)
    ax.text(1.03, 2.2, "start_time", color=C2)
    ax.annotate("", (2.5, 2.75), (2.0, 2.0), arrowprops={"arrowstyle": "-", "color": C2})
    ax.text(2.3, 2.1, "slope", color=C2)
    return fig


@figure("sine")
def sine() -> plt.Figure:
    t = np.linspace(0, 4, 800)
    w = 2 * np.pi * 0.5
    y = 1.5 * np.sin(w * t + 0.6) + 0.5
    fig = _source_plot(t, y, r"Sine Wave: amplitude 1.5, frequency $\pi$ rad/s (0.5 Hz), phase 0.6, bias 0.5", [])
    ax = fig.axes[0]
    ax.axhline(0.5, color=C2, ls=":", lw=1)
    ax.text(3.6, 0.55, "bias", color=C2)
    ax.annotate("", (0.0, 2.0), (0.0, 0.5), arrowprops={"arrowstyle": "<->", "color": C2})
    ax.text(0.05, 1.2, "amplitude", color=C2)
    ax.annotate("", (2.0, -1.4), (0.0, -1.4), arrowprops={"arrowstyle": "<->", "color": C2})
    ax.text(0.6, -1.33, r"period = $2\pi$ / frequency", color=C2)
    ax.set_ylim(-1.7, 2.4)
    return fig


@figure("pulse")
def pulse() -> plt.Figure:
    t = np.linspace(0, 4, 4001)
    on = ((t - 0.5) % 1.0 < 0.3) & (t >= 0.5)
    fig = _source_plot(t, np.where(on, 1.0, 0.0), "Pulse Generator: period 1, duty 30 %, delay 0.5", [])
    ax = fig.axes[0]
    ax.annotate("", (1.5, 1.15), (0.5, 1.15), arrowprops={"arrowstyle": "<->", "color": C2})
    ax.text(0.85, 1.2, "period", color=C2)
    ax.annotate("", (1.8, 0.5), (1.5, 0.5), arrowprops={"arrowstyle": "<->", "color": C2})
    ax.text(1.85, 0.47, "duty × period", color=C2)
    ax.text(0.03, 0.08, "delay", color=C2)
    ax.set_ylim(-0.1, 1.45)
    return fig


@figure("zero_order_hold")
def zero_order_hold() -> plt.Figure:
    d = Diagram()
    s = d.add(Sine(frequency=2.0), name="u")
    z = d.add(ZeroOrderHold(sample_time=0.25), name="zoh")
    d.chain(s, z, d.add(Scope()))
    r = run(d, 3.0, solver="rk4", step=0.005)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.plot(r.t, r["u"], color=INK, lw=1.2, ls="--", label="continuous input")
    ax.step(r.t, r["zoh"], where="post", color=C1, label="ZOH output (T = 0.25 s)")
    ts = np.arange(0, 3.0001, 0.25)
    ax.plot(ts, np.sin(2 * ts), "o", color=C2, ms=5, label="samples")
    ax.set_xlabel("time [s]")
    ax.legend(loc="lower left", ncols=3, fontsize=9)
    ax.set_ylim(-1.6, 1.3)
    fig.tight_layout()
    return fig


@figure("unit_delay")
def unit_delay() -> plt.Figure:
    k = np.arange(0, 9)
    u = np.array([0, 1, 3, 2, 4, 1, 0, 2, 3], dtype=float)
    y = np.concatenate([[0.0], u[:-1]])
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.stem(k - 0.08, u, linefmt=C1, markerfmt="o", basefmt=" ", label="input u[k]")
    ml, _sl, _ = ax.stem(k + 0.08, y, linefmt=C2, markerfmt="s", basefmt=" ", label="output y[k] = u[k−1]")
    ml.set_color(C2)
    ax.set_xlabel("sample k")
    ax.legend(loc="upper right", fontsize=9)
    ax.set_title("Unit Delay: the output is the input from one sample earlier (initial = 0)", color=INK, fontsize=10)
    fig.tight_layout()
    return fig


@figure("integrator_limits")
def integrator_limits() -> plt.Figure:
    d = Diagram()
    src = d.add(Sine(frequency=1.0, amplitude=1.0, bias=0.3), name="u")
    i = d.add(Integrator(upper=1.5, lower=-0.2), name="limited")
    j = d.add(Integrator(), name="free")
    d.chain(src, i, d.add(Scope()))
    d.connect(src, j)
    d.chain(j, d.add(Scope()))
    r = run(d, 12.0)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.plot(r.t, r["free"], color=INK, ls="--", lw=1.2, label="no limits")
    ax.plot(r.t, r["limited"], color=C1, label="upper = 1.5, lower = −0.2")
    ax.axhline(1.5, color=C2, ls=":", lw=1)
    ax.set_xlabel("time [s]")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("Integrator of 0.3 + sin(t): at a limit, integration stops", color=INK, fontsize=10)
    fig.tight_layout()
    return fig


@figure("pid_structure")
def pid_structure() -> plt.Figure:
    fig, ax = schematic(8.4, 3.4, (0, 13), (-0.4, 4.6))
    ax.text(0.2, 2.1, "e", fontsize=13, color=C1, va="center")
    ax.plot([0.6, 1.6], [2.1, 2.1], color=INK, lw=1.5)
    ax.plot([1.6, 1.6], [0.6, 3.6], color=INK, lw=1.5)
    for y, label, color in ((3.6, "P", C1), (2.1, r"$\frac{I}{s}$", C2), (0.6, r"$D\,\frac{N s}{s+N}$", C3)):
        arrow(ax, (1.6, y), (3.0, y))
        box(ax, 3.0, y - 0.5, 2.6, 1.0, label, color=color, size=13)
        arrow(ax, (5.6, y), (7.0, 2.1 + (y - 2.1) * 0.25))
    box(ax, 7.0, 1.4, 1.4, 1.4, "Σ", size=18)
    arrow(ax, (8.4, 2.1), (9.4, 2.1))
    box(ax, 9.4, 1.5, 1.6, 1.2, "", size=10)
    ax.plot([9.6, 10.0, 10.4, 10.8], [1.75, 1.75, 2.45, 2.45], color=INK, lw=1.4)
    ax.text(10.2, 1.25, "lower / upper", ha="center", va="top", color=INK, fontsize=9)
    arrow(ax, (11.0, 2.1), (12.3, 2.1), text="u")
    ax.text(4.3, 4.35, "proportional · integral · filtered derivative", ha="center", color=INK, fontsize=10)
    return fig


@figure("prelookup")
def prelookup() -> plt.Figure:
    fig, ax = schematic(8.4, 3.6, (0, 13), (-0.6, 4.8))
    ax.text(0.1, 3.0, "engine\nspeed", fontsize=10, color=INK, va="center")
    arrow(ax, (1.3, 3.0), (2.4, 3.0))
    box(ax, 2.4, 2.3, 2.6, 1.4, "Prelookup\nspeed axis", color=C1, size=10)
    ax.text(0.1, 0.6, "load", fontsize=10, color=INK, va="center")
    arrow(ax, (1.3, 0.6), (2.4, 0.6))
    box(ax, 2.4, -0.1, 2.6, 1.4, "Prelookup\nload axis", color=C2, size=10)
    for y_from, color, label in ((3.0, C1, "k₁, f₁"), (0.6, C2, "k₂, f₂")):
        ax.text(5.6, y_from + 0.15, label, fontsize=10, color=INK, ha="center", va="bottom")
        for y_to in (3.6, 1.4):
            arrow(ax, (5.0, y_from), (7.6, y_to + (0.25 if y_from > 2 else -0.25)), color=color)
    box(ax, 7.6, 3.0, 3.0, 1.2, "Interpolation\nignition map", size=10)
    box(ax, 7.6, 0.8, 3.0, 1.2, "Interpolation\nfuel map", size=10)
    arrow(ax, (10.6, 3.6), (12.0, 3.6), text="advance")
    arrow(ax, (10.6, 1.4), (12.0, 1.4), text="fuel")
    ax.text(
        6.5,
        4.6,
        "each axis is searched once; every map over the same axes reuses k and f",
        ha="center",
        color=INK,
        fontsize=10,
    )
    return fig


@figure("rate_transition")
def rate_transition() -> plt.Figure:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(6.4, 3.6), sharex=True)
    t = np.arange(0, 0.501, 0.01)
    fast = np.sin(2 * np.pi * 2 * t) + 1.5
    slow_t = np.arange(0, 0.501, 0.1)
    top.step(t, fast, where="post", color=C1, lw=1.2, label="10 ms signal")
    held = fast[(np.floor(t / 0.1 + 1e-9) * 10).astype(int)]
    top.step(t, held, where="post", color=C2, lw=2, label="fast_to_slow: sampled at 100 ms")
    top.set_ylabel("value")
    top.legend(loc="upper right", fontsize=8)
    top.set_title("Rate Transition between a 10 ms and a 100 ms task", color=INK, fontsize=10)
    slow = np.array([1.0, 2.0, 1.5, 3.0, 2.5, 2.0])
    bottom.step(slow_t, slow, where="post", color=C3, lw=2, label="100 ms signal")
    delayed = np.concatenate([[0.0], slow[:-1]])
    bottom.step(slow_t, delayed, where="post", color=C4, lw=2, ls="--", label="slow_to_fast: one slow period later")
    bottom.set_ylabel("value")
    bottom.set_xlabel("time [s]")
    bottom.legend(loc="upper left", fontsize=8)
    bottom.set_xlim(0, 0.5)
    for ax in (top, bottom):
        for x in slow_t:
            ax.axvline(x, color=INK, lw=0.6, ls=":")
    fig.tight_layout()
    return fig


@figure("pid_anti_windup")
def pid_anti_windup() -> plt.Figure:
    def response(aw: str):  # type: ignore[no-untyped-def]
        d = Diagram()
        r = d.add(Step(time=0.0, final=1.2), name="r")
        e = d.add(Sum(signs="+-"), name="e")
        c = d.add(PID(P=1.0, I=5.0, upper=1.5, lower=-1.5, anti_windup=aw), name="pid")
        p = d.add(TransferFunction(numerator=[1.0], denominator=[1.0, 1.0]), name="y")
        d.connect(r, (e, 0))
        d.connect(p, (e, 1))
        d.chain(e, c, p, d.add(Scope()))
        return run(d, 8.0, solver="rk4", step=0.005)

    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    for aw, color, label in (
        ("none", C2, "none"),
        ("clamping", C1, "clamping"),
        ("back_calculation", C3, "back_calculation"),
    ):
        res = response(aw)
        ax.plot(res.t, res["y"], color=color, label=f"anti_windup = {label}")
    ax.axhline(1.2, color=INK, ls=":", lw=1)
    ax.text(7.9, 1.23, "setpoint", color=INK, ha="right", va="bottom", fontsize=9)
    ax.set_xlabel("time [s]")
    ax.set_ylabel("plant output")
    ax.set_title("Output limited to ±1.5: without anti-windup the integrator overshoots", color=INK, fontsize=10)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    return fig


@figure("discrete_integrator")
def discrete_integrator() -> plt.Figure:
    def seq(method: str):  # type: ignore[no-untyped-def]
        d = Diagram()
        i = d.add(DiscreteIntegrator(sample_time=1.0, method=method), name="i")
        d.chain(d.add(Constant(value=1.0)), i, d.add(Scope()))
        return run(d, 5.0)

    f, b = seq("forward_euler"), seq("backward_euler")
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.stem(f.t - 0.07, f["i"], linefmt=C1, markerfmt="o", basefmt=" ", label="forward_euler: y[k] = x[k]")
    ml, _, _ = ax.stem(
        b.t + 0.07, b["i"], linefmt=C2, markerfmt="s", basefmt=" ", label="backward_euler: y[k] = x[k] + K·T·u[k]"
    )
    ml.set_color(C2)
    ax.set_xlabel("time [s]  (T = 1 s, input u = 1)")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


@figure("transfer_function")
def transfer_function() -> plt.Figure:
    d = Diagram()
    u = d.add(Step(time=0.0), name="u")
    g1 = d.add(TransferFunction(numerator=[1.0], denominator=[0.5, 1.0]), name="first")
    g2 = d.add(TransferFunction(numerator=[4.0], denominator=[1.0, 0.8, 4.0]), name="second")
    d.chain(u, g1, d.add(Scope()))
    d.connect(u, g2)
    d.chain(g2, d.add(Scope()))
    r = run(d, 8.0, rtol=1e-8)
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.plot(r.t, r["first"], color=C1, label=r"$\frac{1}{0.5 s + 1}$  (num [1], den [0.5 1])")
    ax.plot(r.t, r["second"], color=C2, label=r"$\frac{4}{s^2 + 0.8 s + 4}$  (num [4], den [1 0.8 4])")
    ax.axvline(0.5, color=C1, ls=":", lw=1)
    ax.text(0.55, 0.15, "τ = 0.5 s\n(63 %)", color=C1, fontsize=9)
    ax.set_xlabel("time [s]")
    ax.set_title("Unit step responses", color=INK, fontsize=10)
    ax.legend(loc="lower right", fontsize=10)
    fig.tight_layout()
    return fig


@figure("from_workspace")
def from_workspace() -> plt.Figure:
    tp = np.array([0, 1, 2, 3, 4.0])
    yp = np.array([0, 2, 1, 3, 3.0])
    t = np.linspace(0, 4.5, 500)
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.plot(t, np.interp(t, tp, yp), color=C1, label="interpolation = linear")
    ax.step(np.append(tp, 4.5), np.append(yp, 3.0), where="post", color=C2, label="interpolation = hold")
    ax.plot(tp, yp, "o", color=INK, ms=5, label="data points")
    ax.set_xlabel("time [s]")
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


@figure("switch")
def switch() -> plt.Figure:
    fig, ax = schematic(6.4, 2.8, (0, 10), (-0.4, 3.8))
    for y, lab, color in (
        (3.0, "input 0  (passed when the condition holds)", C1),
        (1.7, "input 1  (control)", C4),
        (0.4, "input 2  (passed otherwise)", C2),
    ):
        arrow(ax, (0.2, y), (5.0, 1.7 + (y - 1.7) * 0.4), color)
        ax.text(0.2, y + 0.12, lab, color=color, fontsize=9, va="bottom")
    box(ax, 5.0, 0.9, 1.6, 1.6, "switch", size=10)
    arrow(ax, (6.6, 1.7), (8.4, 1.7), text="y")
    ax.text(5.8, 0.35, "criterion: u1 >= threshold", ha="center", color=INK, fontsize=9)
    return fig


@figure("mux_demux")
def mux_demux() -> plt.Figure:
    fig, ax = schematic(7.6, 2.6, (0, 12), (-0.2, 3.6))
    for i, (lab, color) in enumerate((("a (width 1)", C1), ("b (width 2)", C2))):
        y = 2.6 - i * 1.4
        arrow(ax, (0.2, y), (2.4, 1.6 + (0.5 - i) * 0.8), color)
        ax.text(0.2, y + 0.1, lab, color=color, fontsize=9, va="bottom")
    box(ax, 2.4, 0.6, 0.6, 2.0, "", size=9)
    ax.text(2.7, 0.35, "Mux", ha="center", color=INK, fontsize=9)
    arrow(ax, (3.0, 1.6), (6.4, 1.6), text="[a, b₁, b₂]  (width 3)")
    box(ax, 6.4, 0.6, 0.6, 2.0, "", size=9)
    ax.text(6.7, 0.35, "Demux (3 outputs)", ha="center", color=INK, fontsize=9)
    for i, lab in enumerate(("a", "b₁", "b₂")):
        y = 2.3 - i * 0.7
        arrow(ax, (7.0, y), (9.0, y), C3)
        ax.text(9.15, y, lab, color=C3, va="center", fontsize=10)
    return fig


# Sequential single-hue ramp (light -> dark blue) for magnitude, e.g. a calibration map.
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


@figure("lookup_1d")
def lookup_1d() -> plt.Figure:
    from nervus.blocks.lookup import locate

    bp = np.array([0.0, 1.0, 2.0, 3.0])
    tab = np.array([0.0, 2.0, 1.5, 3.0])
    x = np.linspace(-0.7, 3.7, 900)

    def lut(interp: str, extrap: str) -> np.ndarray:
        i, f = locate(x, bp, interp, extrap)
        return tab[i] + f * (tab[i + 1] - tab[i])

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.0), sharey=True)
    a1.plot(x, lut("linear", "clip"), color=C1, label="linear")
    a1.plot(x, lut("nearest", "clip"), color=C2, label="nearest")
    a1.plot(x, lut("flat", "clip"), color=C3, label="flat")
    a1.set_title("interpolation (extrapolation = clip)", color=INK, fontsize=10)
    a2.plot(x, lut("linear", "clip"), color=C1, label="clip")
    a2.plot(x, lut("linear", "linear"), color=C2, ls="--", label="linear")
    a2.set_title("extrapolation (interpolation = linear)", color=INK, fontsize=10)
    for ax in (a1, a2):
        ax.plot(bp, tab, "o", color=INK, ms=6, label="table points")
        ax.axvspan(-0.7, 0, color=GRID, lw=0)
        ax.axvspan(3, 3.7, color=GRID, lw=0)
        ax.set_xlabel("input u")
        ax.legend(loc="upper left", fontsize=9)
    a1.set_ylabel("output y")
    fig.tight_layout()
    return fig


@figure("lookup_2d")
def lookup_2d() -> plt.Figure:
    from matplotlib.colors import LinearSegmentedColormap

    from nervus.blocks import Lookup2D

    rpm = np.array([800, 1500, 2500, 3500, 4500, 6000.0])
    load = np.array([10, 30, 50, 70, 90.0])
    advance = np.array(
        [
            [12, 10, 8, 6, 4],
            [20, 17, 14, 11, 8],
            [28, 25, 21, 17, 13],
            [33, 30, 26, 21, 16],
            [36, 33, 28, 23, 18],
            [38, 35, 30, 25, 20.0],
        ]
    )
    blk = Lookup2D(row_breakpoints=rpm, column_breakpoints=load, table=advance)
    blk.configure([1, 1], [1])
    rr, ll = np.meshgrid(np.linspace(800, 6000, 160), np.linspace(10, 90, 120), indexing="ij")
    zz = np.array(
        [
            [
                blk.outputs(0, [np.array([r]), np.array([lv])], np.zeros(0), np.zeros(0))[0][0]
                for r, lv in zip(rrow, lrow, strict=True)
            ]
            for rrow, lrow in zip(rr, ll, strict=True)
        ]
    )
    cmap = LinearSegmentedColormap.from_list("seq", SEQ_BLUE)
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    mesh = ax.pcolormesh(ll, rr, zz, cmap=cmap, shading="auto")
    lv, rv = np.meshgrid(load, rpm)
    ax.plot(lv, rv, "o", color="#ffffff", ms=4, mec=INK, mew=0.6)
    cb = fig.colorbar(mesh, ax=ax)
    cb.set_label("ignition advance [°]", color=INK)
    cb.outline.set_edgecolor(INK)
    ax.set_xlabel("input 1: load [%]  (column_breakpoints)")
    ax.set_ylabel("input 0: speed [rpm]\n(row_breakpoints)")
    ax.set_title("Ignition map: bilinear between table points (dots)", color=INK, fontsize=10)
    ax.grid(False)
    fig.tight_layout()
    return fig


@figure("dead_zone")
def dead_zone() -> plt.Figure:
    u = np.linspace(-2, 2, 400)
    y = np.where(u > 0.5, u - 0.5, np.where(u < -0.5, u + 0.5, 0.0))
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.plot(u, y, color=C1)
    ax.axvspan(-0.5, 0.5, color=C2 + "22", lw=0)
    ax.text(0, 0.9, "dead zone\n[start, end]", ha="center", color=C2, fontsize=9)
    ax.set_xlabel("input u")
    ax.set_ylabel("output y")
    fig.tight_layout()
    return fig


def _discrete_run(block, src, t_final: float, ts: float):  # type: ignore[no-untyped-def]
    d = Diagram()
    s = d.add(src, name="u")
    z = d.add(ZeroOrderHold(sample_time=ts), name="zoh")
    b = d.add(block, name="y")
    d.chain(s, z, b, d.add(Scope()))
    return run(d, t_final, solver="rk4", step=ts / 10)


@figure("relay")
def relay() -> plt.Figure:
    r = _discrete_run(Relay(on_point=0.5, off_point=-0.5), Sine(amplitude=1.0, frequency=1.5), 8.0, 0.02)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.0), gridspec_kw={"width_ratios": [1, 1.6]})
    a1.plot([-1.2, 0.5, 0.5, 1.2], [0, 0, 1, 1], color=C1)
    a1.plot([1.2, -0.5, -0.5, -1.2], [1, 1, 0, 0], color=C2, ls="--")
    a1.annotate("", (0.5, 0.6), (0.5, 0.35), arrowprops={"arrowstyle": "-|>", "color": C1})
    a1.annotate("", (-0.5, 0.4), (-0.5, 0.65), arrowprops={"arrowstyle": "-|>", "color": C2})
    a1.text(0.55, 0.15, "on_point", color=C1, fontsize=9)
    a1.text(-1.15, 0.82, "off_point", color=C2, fontsize=9)
    a1.set_xlabel("input u")
    a1.set_ylabel("output")
    a1.set_title("Hysteresis", color=INK, fontsize=10)
    a2.plot(r.t, r["u"], color=INK, ls="--", lw=1.2, label="input")
    a2.step(r.t, r["y"], where="post", color=C1, label="relay output")
    a2.axhline(0.5, color=C1, ls=":", lw=1)
    a2.axhline(-0.5, color=C2, ls=":", lw=1)
    a2.set_xlabel("time [s]")
    a2.legend(loc="lower left", fontsize=9, ncols=2)
    a2.set_ylim(-1.5, 1.4)
    fig.tight_layout()
    return fig


@figure("rate_limiter")
def rate_limiter() -> plt.Figure:
    d = Diagram()
    s = d.add(Pulse(amplitude=1.0, period=4.0, duty=50.0, delay=0.5), name="u")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="zoh")
    b = d.add(RateLimiter(rising_rate=1.0, falling_rate=-2.0), name="y")
    d.chain(s, z, b, d.add(Scope()))
    r = run(d, 6.0, solver="rk4", step=0.01)
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.step(r.t, r["zoh"], where="post", color=INK, ls="--", lw=1.2, label="input")
    ax.plot(r.t, r["y"], color=C1, label="rising_rate = 1/s, falling_rate = −2/s")
    ax.set_xlabel("time [s]")
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    return fig


def _bool_figure(t: np.ndarray, rows: list[tuple[str, np.ndarray, str]], title: str) -> plt.Figure:
    fig, axes = plt.subplots(len(rows), 1, figsize=(6.4, 0.9 + 0.75 * len(rows)), sharex=True)
    for ax, (label, y, color) in zip(axes, rows, strict=True):
        ax.step(t, y, where="post", color=color)
        ax.set_ylim(-0.25, max(1.25, float(np.max(y)) + 0.25))
        ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize=9)
        ax.set_yticks([0, 1] if np.max(y) <= 1 else [0, int(np.max(y))])
    axes[0].set_title(title, color=INK, fontsize=10)
    axes[-1].set_xlabel("sample k")
    fig.tight_layout()
    return fig


def _bool_input() -> np.ndarray:
    return np.array([0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0], dtype=float)


def _seq(block) -> tuple[np.ndarray, np.ndarray, np.ndarray]:  # type: ignore[no-untyped-def]
    from nervus.blocks import FromWorkspace

    u = _bool_input()
    k = np.arange(u.size, dtype=float)
    d = Diagram()
    s = d.add(FromWorkspace(time=k, data=u, interpolation="hold"), name="u")
    z = d.add(ZeroOrderHold(sample_time=1.0), name="zoh")
    b = d.add(block, name="y")
    d.chain(s, z, b, d.add(Scope()))
    r = run(d, float(u.size - 1), solver="rk4", step=1.0)
    return r.t, r["zoh"], r["y"]


@figure("edge_detect")
def edge_detect() -> plt.Figure:
    t, u, rising = _seq(EdgeDetect(direction="rising"))
    _, _, falling = _seq(EdgeDetect(direction="falling"))
    return _bool_figure(
        t,
        [("input", u, INK), ("rising", rising, C1), ("falling", falling, C2)],
        "Edge Detect: a one-sample pulse on each change",
    )


@figure("debounce")
def debounce() -> plt.Figure:
    t, u, y = _seq(Debounce(on_samples=3, off_samples=2))
    return _bool_figure(
        t, [("input", u, INK), ("output", y, C1)], "Debounce: on after 3 true samples, off after 2 false samples"
    )


@figure("counter")
def counter() -> plt.Figure:
    from nervus.blocks import Counter

    t, u, y = _seq(Counter(limit=5, at_limit="wrap"))
    return _bool_figure(
        t,
        [("count enable", u, INK), ("count", y, C1)],
        "Counter (limit = 5, wrap): counts samples while the input is true",
    )


@figure("discrete_filter")
def discrete_filter() -> plt.Figure:
    rng = np.random.default_rng(3)
    t = np.arange(0, 3, 0.01)
    noisy = np.where(t >= 0.5, 1.0, 0.0) + 0.15 * rng.standard_normal(t.size)
    from nervus.blocks import FromWorkspace

    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.plot(t, noisy, color=INK, lw=0.8, alpha=0.7, label="noisy sensor")
    for tau, color in ((0.05, C1), (0.25, C2)):
        d = Diagram()
        s = d.add(FromWorkspace(time=t, data=noisy, interpolation="hold"), name="u")
        z = d.add(ZeroOrderHold(sample_time=0.01), name="zoh")
        b = d.add(DiscreteFilter(time_constant=tau), name="y")
        d.chain(s, z, b, d.add(Scope()))
        r = run(d, float(t[-1]), solver="rk4", step=0.01)
        ax.plot(r.t, r["y"], color=color, label=f"τ = {tau} s")
    ax.set_xlabel("time [s]  (T = 10 ms)")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    return fig


@figure("chart_engine_modes")
def chart_engine_modes() -> plt.Figure:
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0.2, 4.0)
    ax.axis("off")
    states = {"off": (1.0, 2.0), "cranking": (5.0, 2.0), "running": (9.0, 2.0)}
    notes = {
        "off": "entry: mode = 0; fuel = 0",
        "cranking": "entry: mode = 1\nduring: fuel = 1",
        "running": "entry: mode = 2",
    }
    colors = {"off": INK, "cranking": C2, "running": C3}
    for name, (x, y) in states.items():
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                2.2,
                1.3,
                boxstyle="round,pad=0.05,rounding_size=0.3",
                ec=colors[name],
                fc=colors[name] + "18",
                lw=1.8,
            )
        )
        ax.text(x + 1.1, y + 0.95, name, ha="center", va="center", fontsize=12, color=colors[name], weight="bold")
        ax.text(x + 1.1, y + 0.4, notes[name], ha="center", va="center", fontsize=8, color=INK)

    def arrow(a: tuple[float, float], b: tuple[float, float], label: str, rad: float, ly: float) -> None:
        ax.add_patch(
            FancyArrowPatch(
                a, b, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>", mutation_scale=13, lw=1.4, color=INK
            )
        )
        ax.text((a[0] + b[0]) / 2, ly, label, ha="center", fontsize=8.5, color=C1)

    arrow((3.2, 2.95), (5.0, 2.95), "key > 0.5", -0.35, 3.45)
    arrow((7.2, 2.95), (9.0, 2.95), "rpm > 600", -0.35, 3.45)
    arrow((5.0, 2.15), (3.2, 2.15), "after(300) / fuel = 0", -0.35, 1.72)
    arrow((10.1, 2.0), (2.1, 2.0), "key < 0.5 or rpm < 300", -0.28, 0.42)
    ax.plot([0.55], [2.65], "o", color=INK, ms=7)
    ax.annotate("", (1.0, 2.65), (0.6, 2.65), arrowprops={"arrowstyle": "-|>", "color": INK})
    ax.text(0.35, 3.0, "initial", fontsize=8, color=INK)
    fig.tight_layout()
    return fig


@figure("idle_speed_control")
def idle_speed_control() -> plt.Figure:
    import importlib.util

    spec = importlib.util.spec_from_file_location("idle", ROOT / "examples" / "idle_speed_control.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    d = mod.build()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 4.6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for alpha, color, label in (
        (0.0, C2, "feedback only (alpha_ac = 0)"),
        (3.0, C1, "with AC feed-forward (alpha_ac = 3°)"),
    ):
        r = simulate(d, params={"alpha_ac": alpha})
        a1.plot(r.t, r["engine_rpm"], color=color, label=label)
        a2.plot(r.t, r["throttle_actuator"], color=color)
    a1.axvline(5.0, color=INK, ls=":", lw=1)
    a1.text(5.05, 870, "AC compressor on", color=INK, fontsize=9)
    a1.axvline(4.8, color=C1, ls=":", lw=1)
    a1.set_ylabel("engine speed [rpm]")
    a1.set_ylim(650, 900)
    a1.set_xlim(3.5, 12)
    a1.legend(loc="lower right", fontsize=9)
    a2.set_ylabel("throttle [°]")
    a2.set_xlabel("time [s]")
    fig.tight_layout()
    return fig


@figure("datatype_conversion")
def datatype_conversion() -> plt.Figure:
    from nervus.core.datatypes import parse_datatype

    t = np.linspace(0, 1, 2000)
    u = 160 * np.sin(2 * np.pi * t)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.0))
    i8 = parse_datatype("int8")
    a1.plot(t, u, color=INK, ls="--", lw=1.2, label="input (double)")
    a1.plot(t, i8.quantize(u), color=C1, label="int8, saturate")
    a1.plot(t, i8.quantize(u, overflow="wrap"), color=C2, lw=1.4, label="int8, wrap")
    a1.set_title("Overflow: int8 holds -128 … 127", color=INK, fontsize=10)
    a1.set_xlabel("time [s]")
    a1.legend(loc="lower left", fontsize=8)
    x = np.linspace(0, 1, 2000)
    v = 0.37 * np.sin(2 * np.pi * x) + 0.4
    fx = parse_datatype("fixdt(0, 8, 4)")
    a2.plot(x, v, color=INK, ls="--", lw=1.2, label="input (double)")
    a2.plot(x, fx.quantize(v), color=C1, label="fixdt(0, 8, 4): steps of 1/16")
    a2.set_title("Resolution: fixed point with 4 fraction bits", color=INK, fontsize=10)
    a2.set_xlabel("time [s]")
    a2.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    return fig


@figure("can_frame")
def can_frame() -> plt.Figure:
    from matplotlib.patches import Rectangle

    from nervus.can import load_dbc

    msg = load_dbc(ROOT / "examples" / "data" / "vehicle.dbc")["EngineData"]
    colors = [C1, C2, C3, C4, "#e87ba4"]
    fig, ax = plt.subplots(figsize=(9.0, 3.4))
    ax.set_xlim(-0.6, 8.4)
    ax.set_ylim(-2.3, 8.6)
    ax.invert_yaxis()
    ax.axis("off")
    owner: dict[int, int] = {}
    for k, s in enumerate(msg.signals):
        for b in range(s.length):
            owner[s.start + b] = k  # Intel signals: consecutive bits from the start bit
    for byte in range(8):
        ax.text(-0.35, byte + 0.5, f"byte {byte}", ha="right", va="center", fontsize=8, color=INK)
        for bit in range(8):
            n = byte * 8 + bit
            x = 7 - bit  # bit 7 on the left, as in DBC editors
            k = owner.get(n)
            fc = colors[k % len(colors)] + "55" if k is not None else "none"
            ax.add_patch(Rectangle((x, byte), 1, 1, fc=fc, ec=INK, lw=0.6))
            ax.text(x + 0.5, byte + 0.5, str(n), ha="center", va="center", fontsize=7, color=INK)
    for k, s in enumerate(msg.signals):
        ax.text(
            8.3,
            0.5 + k * 1.1,
            f"■ {s.name}: start {s.start}, {s.length} bits, ×{s.factor:g} {s.offset:+g} {s.unit}",
            color=colors[k % len(colors)],
            fontsize=9,
            va="center",
        )
    ax.set_xlim(-0.6, 15.5)
    ax.text(4, -0.9, "EngineData (0x100): Intel byte order, bit numbers per byte", ha="center", color=INK, fontsize=10)
    fig.tight_layout()
    return fig


@figure("engine_comparison")
def engine_comparison() -> plt.Figure:
    from nervus import load

    d = load(Path(__file__).parent.parent / "examples" / "engine_comparison.nervus")
    res = simulate(d)
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    for name, color, label in (("engine_1_6l", C1, "1.6 l"), ("engine_2_0l", C2, "2.0 l")):
        rpm = res[f"{name}/to_rpm"]
        ax.plot(res.t, rpm, color=color, label=f"{label} engine", lw=2)
        ax.text(res.t[-1] + 0.1, rpm[-1], label, color=INK, va="center", fontsize=9)
    for t_ev, text in ((2.0, "throttle 3° → 6°"), (5.0, "+15 N·m load")):
        ax.axvline(t_ev, color=INK, ls=":", lw=1)
        ax.text(t_ev + 0.08, 2350, text, color=INK, fontsize=9, va="top")
    ax.set_xlim(0, 8.7)
    ax.set_ylim(600, 2400)
    ax.set_xlabel("time [s]")
    ax.set_ylabel("engine speed [rpm]")
    ax.set_title("Same library component, two parameter sets", color=INK, fontsize=10)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


@figure("lambda_trims")
def lambda_trims() -> plt.Figure:
    from nervus import load

    d = load(Path(__file__).parent.parent / "examples" / "lambda_control.nervus")
    res = simulate(d)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(6.4, 4.2), sharex=True, height_ratios=[1, 1.3])
    top.plot(res.t, res["lambda_cyl"], color=C1, lw=2)
    top.axhline(1.0, color=INK, ls=":", lw=1)
    top.set_ylabel("lambda")
    top.set_ylim(0.97, 1.07)
    top.set_title("6 % unmetered air at 12 s: the STFT reacts, the LTFT learns", color=INK, fontsize=10)
    for name, color, label in (("ECU/stft_pct", C2, "STFT"), ("ECU/ltft_pct", C3, "LTFT")):
        y = res[name]
        bottom.plot(res.t, y, color=color, lw=2, label=label)
        bottom.text(res.t[-1] + 0.4, y[-1], label, color=INK, va="center", fontsize=9)
    for ax in (top, bottom):
        ax.axvline(12.0, color=INK, ls=":", lw=1)
    bottom.text(12.3, 6.6, "leak", color=INK, fontsize=9, va="top")
    bottom.set_ylabel("fuel trim [%]")
    bottom.set_xlabel("time [s]")
    bottom.set_xlim(0, 43)
    bottom.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


@figure("drive_cycle")
def drive_cycle() -> plt.Figure:
    from nervus import load

    d = load(Path(__file__).parent.parent / "examples" / "drive_cycle.nervus")
    res = simulate(d)
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(6.4, 4.2), sharex=True, height_ratios=[1.4, 1])
    top.plot(res.t, res["cycle_kmh"], color=INK, ls=":", lw=1.5, label="ECE-15 cycle")
    top.plot(res.t, res["speed_kmh"], color=C1, lw=2, label="car (driver model)")
    top.set_ylabel("speed [km/h]")
    top.set_ylim(0, 58)
    top.legend(loc="upper left", fontsize=9)
    top.set_title("Following the urban drive cycle: 994 m in 195 s", color=INK, fontsize=10)
    bottom.plot(res.t, res["vehicle/wheel_power"] / 1000, color=C2, lw=1.5)
    bottom.axhline(0, color=INK, lw=0.8)
    bottom.text(150, -9, "braking", color=INK, fontsize=9)
    bottom.set_ylabel("wheel power [kW]")
    bottom.set_xlabel("time [s]")
    bottom.set_xlim(0, 195)
    fig.tight_layout()
    return fig


@figure("engine_modes")
def engine_modes() -> plt.Figure:
    from nervus import load

    d = load(Path(__file__).parent.parent / "examples" / "engine_modes.nervus")
    case = next(c for c in d.tests if c.name == "overrun fuel cut-off")
    res = simulate(d, case.stop_time, inputs=case.inputs)
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(6.4, 4.8), sharex=True, height_ratios=[1.2, 0.8, 1.2])
    a1.plot(res.t, res["rpm_10ms"], color=C1, lw=2)
    for y, text in ((1500, "fuel cut-off above"), (1100, "fuel back below")):
        a1.axhline(y, color=INK, ls=":", lw=1)
        a1.text(1.6, y + 60, f"{text} {y} rpm", color=INK, fontsize=8, ha="left")
    a1.set_ylabel("rpm")
    a1.set_title("Overrun fuel cut-off: no fuel while coasting", color=INK, fontsize=10)
    a2.plot(res.t, res["pedal_10ms"], color=C2, lw=2)
    a2.set_ylabel("pedal [%]")
    names = ["off", "crank", "crank_fail", "idle", "run", "fuel_cut", "stalled"]
    a3.step(res.t, res["mode"], where="post", color=C3, lw=2, label="mode")
    a3.step(res.t, res["fuel"] * 5.4, where="post", color=C4, lw=1.5, ls="--", label="fuel on")
    a3.set_yticks(range(6), names[:6])
    a3.set_ylim(-0.4, 5.8)
    a3.legend(loc="lower right", fontsize=8)
    a3.set_xlabel("time [s]")
    a3.set_xlim(0, 10)
    fig.tight_layout()
    return fig


@figure("gear_shift")
def gear_shift() -> plt.Figure:
    from nervus import load

    d = load(Path(__file__).parent.parent / "examples" / "gear_shift.nervus")
    res = simulate(d)
    fig, (a0, a1, a2, a3) = plt.subplots(4, 1, figsize=(6.4, 6.0), sharex=True, height_ratios=[0.8, 1, 1, 1])
    a0.plot(res.t, res["pedal"], color=C1, lw=2)
    a0.plot(res.t, res["grade"], color=C2, lw=2)
    a0.text(12, 30, "pedal", color=INK, fontsize=8)
    a0.text(31, 20, "road grade", color=INK, fontsize=8)
    a0.set_ylabel("%")
    a0.set_title("Launch, cruise, kickdown, hill", color=INK, fontsize=10)
    a1.plot(res.t, res["speed"], color=C1, lw=2)
    a1.set_ylabel("speed [km/h]")
    a2.plot(res.t, res["rpm"], color=C3, lw=2)
    a2.set_ylabel("engine [rpm]")
    a3.step(res.t, res["gear"], where="post", color=C4, lw=2)
    a3.set_yticks(range(1, 6))
    a3.set_ylabel("gear")
    for t, y, text in ((0.5, 4.2, "full throttle:\nlate upshifts"), (13, 4.2, "20 %: up to 5th"),
                       (22.5, 1.6, "kickdown"), (38.5, 3.0, "hill")):  # fmt: skip
        a3.text(t, y, text, color=INK, fontsize=8)
    a3.set_xlabel("time [s]")
    a3.set_xlim(0, 45)
    fig.tight_layout()
    return fig


@figure("diagnostic_monitor")
def diagnostic_monitor() -> plt.Figure:
    from nervus.blocks import DiagnosticMonitor, Inport, Outport

    ts, n = 0.01, 60  # four operation cycles of 0.6 s
    d = Diagram()
    mon = d.add(DiagnosticMonitor(dtc="P0300", threshold=5.0, cycle_input=True, sample_time=ts), name="m")
    for k, name in enumerate(("fault", "cycle")):
        d.connect(d.add(Inport(port=k + 1), name=name), (mon, k))
    for k, name in enumerate(("mil", "pending", "confirmed")):
        d.connect((mon, k), d.add(Outport(port=k + 1), name=name))
    rng = np.random.default_rng(7)
    fault, cycle = [], []
    for failing in (True, True, False, False):
        f = (rng.random(n) < (0.85 if failing else 0.08)).astype(float)
        f[:5] = 0.0
        c = np.zeros(n)
        c[1:3] = 1.0
        fault += f.tolist()
        cycle += c.tolist()
    t = np.arange(len(fault)) * ts
    res = simulate(d, t[-1], solver="rk4", step=ts,
                   inputs={"fault": (t, np.c_[fault]), "cycle": (t, np.c_[cycle])})  # fmt: skip
    fig, axes = plt.subplots(4, 1, figsize=(6.4, 4.2), sharex=True)
    rows = (("fault", fault, C1), ("pending", res["pending"], C2), ("confirmed", res["confirmed"], C3),
            ("MIL", res["mil"], C4))  # fmt: skip
    for ax, (label, y, color) in zip(axes, rows, strict=True):
        ax.step(t, y, where="post", color=color, lw=1.5 if label == "fault" else 2)
        ax.set_ylim(-0.2, 1.3)
        ax.set_yticks([0, 1])
        ax.set_ylabel(label, rotation=0, ha="right", va="center")
        for k in range(1, 4):
            ax.axvline(k * n * ts, color=INK, ls=":", lw=1)
    for k, text in enumerate(("cycle 1: fails", "cycle 2: fails", "cycle 3: passes", "cycle 4: passes")):
        axes[0].text((k + 0.5) * n * ts, 1.15, text, ha="center", va="bottom", color=INK, fontsize=8)
    axes[-1].set_xlabel("time [s]")
    axes[-1].set_xlim(0, t[-1])
    fig.tight_layout()
    return fig


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])  # optional: names of the figures to regenerate
    for name, fn in FIGURES.items():
        if only and name not in only:
            continue
        fig = fn()
        out = APP_DIR / f"{name}.png"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        plt.close(fig)
        shutil.copy(out, DOCS_DIR / out.name)
        print("wrote", out.name)


if __name__ == "__main__":
    main()
