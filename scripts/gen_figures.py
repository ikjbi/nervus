"""Generate the explanatory block figures used in the docs and the in-app help.

Run: uv run python scripts/gen_figures.py

Each figure is written to ``src/nervus/gui/resources/figures/`` (bundled with the app) and copied to
``docs/images/blocks/`` (for the GitHub/MkDocs docs). Response plots are simulated with Nervus itself.
Figures have a transparent background and neutral grey text so they read well in light and dark themes.
"""

from __future__ import annotations

import shutil
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
    DiscreteIntegrator,
    Integrator,
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


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for name, fn in FIGURES.items():
        fig = fn()
        out = APP_DIR / f"{name}.png"
        fig.savefig(out, dpi=160, bbox_inches="tight")
        plt.close(fig)
        shutil.copy(out, DOCS_DIR / out.name)
        print("wrote", out.name)


if __name__ == "__main__":
    main()
