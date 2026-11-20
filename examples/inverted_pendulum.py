"""Balancing an inverted pendulum on a cart with state feedback (LQR): the classic advanced control lab.

A cart (driven by a motor force, limited to ±10 N) carries a pendulum hinged at its base. Upright is unstable:
without control the pendulum falls. A state-feedback controller measures all four states (cart position and
speed, pendulum angle and angular speed) and computes the force ``F = -K (x - x_ref)``. The gain K comes from an
LQR design on the linearized model; :func:`lqr_gain` computes it (the model stores it in the workspace as
``K_lqr``).

The plant is the full nonlinear model (a Python Function block), with the dimensions of a common lab rig:
cart 0.94 kg, pendulum rod 0.23 kg and 0.64 m long. The scenario: the pendulum starts 0.05 rad (3°) from upright,
gets a tap of 5 N for 0.1 s at 3 s, and the cart moves to 0.3 m at 5 s.

Run with ``uv run python examples/inverted_pendulum.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Demux,
    FromWorkspace,
    Gain,
    Integrator,
    Outport,
    PythonFunction,
    Saturation,
    Scope,
    Step,
    Sum,
    Terminator,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
TS = 0.002

PLANT = {
    "M_cart": (0.94, "kg", "Cart mass (with its motor)"),
    "m_pend": (0.23, "kg", "Pendulum mass"),
    "l_pend": (0.3207, "m", "Hinge to the pendulum's centre of mass (half the 0.64 m rod)"),
    "b_cart": (5.4, "N·s/m", "Cart viscous friction (motor and belt)"),
    "B_pend": (0.0024, "N·m·s/rad", "Pendulum hinge friction"),
    "F_max": (10.0, "N", "Motor force limit"),
}
G = 9.81

DYNAMICS = '''def f(t, s, F):
    """Cart-pole: s = [x, theta, x_dot, theta_dot], theta = 0 upright, positive leaning towards +x."""
    M, m, l, b, Bp = p[0], p[1], p[2], p[3], p[4]
    x, th, xd, thd = s[0], s[1], s[2], s[3]
    J = m * l * l / 3.0          # rod about its centre of mass is m (2l)^2 / 12 = m l^2 / 3
    c, sn = math.cos(th), math.sin(th)
    a11, a12 = M + m, m * l * c
    a21, a22 = m * l * c, J + m * l * l
    r1 = F - b * xd + m * l * thd * thd * sn
    r2 = m * 9.81 * l * sn - Bp * thd
    det = a11 * a22 - a12 * a21
    return [xd, thd, (r1 * a22 - a12 * r2) / det, (a11 * r2 - a21 * r1) / det]
'''


def linear_model(mass_cart: float = 0.94, mass_pend: float = 0.23, length: float = 0.3207, b: float = 5.4,
                 bp: float = 0.0024) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """A, B of the plant linearized at upright (state [x, theta, x_dot, theta_dot], input F)."""
    big_m, m, l_ = mass_cart, mass_pend, length
    j = m * l_ * l_ / 3.0
    a11, a12, a22 = big_m + m, m * l_, j + m * l_ * l_
    det = a11 * a22 - a12 * a12
    a = np.zeros((4, 4))
    a[0, 2] = a[1, 3] = 1.0
    # x_dd = (a22 (F - b xd) - a12 (m g l th - Bp thd)) / det, th_dd = (a11 (m g l th - Bp thd) - a12 (F - b xd)) / det
    a[2, 1], a[2, 2], a[2, 3] = -a12 * m * G * l_ / det, -a22 * b / det, a12 * bp / det
    a[3, 1], a[3, 2], a[3, 3] = a11 * m * G * l_ / det, a12 * b / det, -a11 * bp / det
    bvec = np.array([[0.0], [0.0], [a22 / det], [-a12 / det]])
    return a, bvec


def lqr_gain(q_x: float = 50.0, q_theta: float = 100.0, q_xdot: float = 0.0, q_thetadot: float = 0.0,
             r: float = 1.0) -> list[float]:  # fmt: skip
    """State-feedback gain K minimizing ∫ xᵀQx + r F² dt (Q diagonal), for F = -K x."""
    from scipy.linalg import solve_continuous_are

    a, b = linear_model()
    q = np.diag([q_x, q_theta, q_xdot, q_thetadot])
    p = solve_continuous_are(a, b, q, np.array([[r]]))
    return [float(v) for v in (b.T @ p / r).ravel()]


def build() -> Diagram:
    d = Diagram("inverted_pendulum")
    d.settings.t_final = 10.0
    d.settings.solver = "auto"
    d.settings.max_step = 1e-3
    for name, (value, unit, desc) in PLANT.items():
        d.workspace.add(Variable(name, value, desc, unit))
    d.workspace.add(Variable("K_lqr", lqr_gain(), "State-feedback gain [x, theta, x_dot, theta_dot] (from lqr_gain)",
                             "N/m, N/rad, N·s/m, N·s/rad"))  # fmt: skip
    plant = d.add(PythonFunction(code=DYNAMICS, num_inputs=2, output_width=4,
                                 parameters="[M_cart, m_pend, l_pend, b_cart, B_pend]"), name="cart_pole")  # fmt: skip
    state = d.add(Integrator(initial=[0.0, 0.05, 0.0, 0.0]), name="state")
    sample = d.add(ZeroOrderHold(sample_time=TS), name="sensors")
    ref = d.add(Step(time=5.0, final=0.3), name="cart_ref")
    ref_vec = d.add(Gain(gain=[1.0, 0.0, 0.0, 0.0]), name="ref_state")
    err = d.add(Sum(signs="-+"), name="state_error")  # x_ref - x
    k = d.add(Gain(gain="[K_lqr]", multiplication="matrix"), name="K")
    sat = d.add(Saturation(upper="F_max", lower="-F_max"), name="motor_limit")
    tap = d.add(FromWorkspace(time=[0, 3.0, 3.0001, 3.1, 3.1001, 10], data=[[0], [0], [5], [5], [0], [0]]),
                name="tap")  # fmt: skip
    force = d.add(Sum(signs="++"), name="force")
    d.connect(state, (plant, 0))
    d.connect(force, (plant, 1))
    d.chain(plant, state, sample)
    d.chain(ref, ref_vec)
    d.connect(sample, (err, 0))
    d.connect(ref_vec, (err, 1))
    d.chain(err, k, sat)
    d.connect(sat, (force, 0))
    d.connect(tap, (force, 1))
    split = d.add(Demux(num_outputs=4), name="states")
    d.connect(state, split)
    outs = [split.out_port(0), split.out_port(1)]
    d.connect(split.out_port(0), d.add(Outport(port=1), name="cart_position"))
    d.connect(split.out_port(1), d.add(Outport(port=2), name="angle"))
    for k in (2, 3):
        d.connect(split.out_port(k), d.add(Terminator()))
    d.connect(sat, d.add(Outport(port=3), name="motor_force"))
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(outs[0], (scope, 0))
    d.connect(outs[1], (scope, 1))
    positions = {"cart_ref": (0, 0), "ref_state": (130, 0), "state_error": (280, 30), "K": (400, 30),
                 "motor_limit": (520, 30), "tap": (520, 130), "force": (650, 50), "cart_pole": (780, 50),
                 "state": (920, 50), "sensors": (920, 170), "states": (1060, 50),
                 "cart_position": (1190, 0), "angle": (1190, 100), "motor_force": (650, -60), "scope": (1190, 200)}  # fmt: skip
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    d.tests = [
        TestCase(
            "balances and moves the cart",
            "The pendulum stays within 0.15 rad of upright, and the cart reaches 0.3 m ± 1 cm after 9 s",
            stop_time=10.0,
            checks=[
                Check("bounds", "angle", {"lower": -0.15, "upper": 0.15}),
                Check("bounds", "cart_position", {"lower": 0.29, "upper": 0.31, "t_from": 9.0}),
            ],
        )
    ]
    return d


def main() -> SimResult:
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "inverted_pendulum.nervus")
    for r in run_tests(d):
        print(r.summary())
    a, _b = linear_model()
    print("open-loop poles:", np.round(np.linalg.eigvals(a), 2))
    print("K =", np.round(lqr_gain(), 2))
    res = simulate(d)
    x = np.ravel(res["cart_position"])
    after = res.t > 5.0
    print(f"cart moves the wrong way first: down to {1000 * x[after].min():.0f} mm before going to 300 mm")
    return res


if __name__ == "__main__":
    main()
