"""PID position control of a mass-spring-damper: the first experiment of many control lab courses.

Plant:      m x'' + c x' + k x = F
Controller: continuous PID with output limits (±50 N) and clamping anti-windup

The masses, springs and gains are workspace variables (m, c, k, Kp, Ki, Kd), so the lab sequence of the
tutorial (P, then PD, then PID) is a matter of changing three numbers.

Run with ``uv run python examples/mass_spring_damper_pid.py``. If matplotlib is installed the response is plotted.
The model is also saved next to this script as ``mass_spring_damper_pid.nervus``.
"""

from __future__ import annotations

from pathlib import Path

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import PID, Gain, Integrator, Scope, Step, Sum
from nervus.core import Check, TestCase, Variable
from nervus.core.layout import auto_layout

M, C, K = 1.0, 0.5, 2.0  # kg, N·s/m, N/m


def build() -> Diagram:
    d = Diagram("mass_spring_damper_pid")
    d.settings.t_final = 10.0
    ws = d.workspace
    for name, value, unit, desc in (("m", M, "kg", "Mass"), ("c", C, "N·s/m", "Damping coefficient"),
                                    ("k", K, "N/m", "Spring stiffness"), ("Kp", 40.0, "N/m", "Proportional gain"),
                                    ("Ki", 30.0, "N/(m·s)", "Integral gain"), ("Kd", 8.0, "N·s/m", "Derivative gain")):  # fmt: skip
        ws.add(Variable(name, value, desc, unit))

    ref = d.add(Step(time=0.5, final=1.0), name="reference")
    err = d.add(Sum(signs="+-"), name="error")
    pid = d.add(
        PID(P="Kp", I="Ki", D="Kd", N=100.0, upper=50.0, lower=-50.0, anti_windup="clamping"),
        name="pid",
    )

    # Plant: x'' = (F - c x' - k x) / m
    forces = d.add(Sum(signs="+--"), name="forces")
    inv_m = d.add(Gain(gain="1 / m"), name="1/m")
    vel = d.add(Integrator(), name="velocity")
    pos = d.add(Integrator(), name="position")
    damping = d.add(Gain(gain="c"), name="c")
    spring = d.add(Gain(gain="k"), name="k")
    scope = d.add(Scope(num_inputs=3), name="scope")

    d.connect(ref, err.in_port(0))
    d.connect(pos, err.in_port(1))
    d.chain(err, pid)
    d.connect(pid, forces.in_port(0))
    d.connect(damping, forces.in_port(1))
    d.connect(spring, forces.in_port(2))
    d.chain(forces, inv_m, vel, pos)
    d.connect(vel, damping)
    d.connect(pos, spring)

    d.connect(ref, scope.in_port(0))
    d.connect(pos, scope.in_port(1))
    d.connect(pid, scope.in_port(2))
    d.tests = [
        TestCase(
            "PID reaches the reference",
            "Within 2 % of the 1 m reference after 6 s, overshoot below 15 %, force within the ±50 N limit",
            stop_time=10.0,
            checks=[
                Check("bounds", "position", {"lower": 0.98, "upper": 1.02, "t_from": 6.0}),
                Check("bounds", "position", {"upper": 1.15}),
                Check("bounds", "pid", {"lower": -50.0, "upper": 50.0}),
            ],
        )
    ]
    return d


def report(res: SimResult) -> None:
    pos = res["position"]
    print(f"final position   {pos[-1]:.4f} m (reference 1.0)")
    print(f"peak position    {pos.max():.4f} m  (overshoot {max(0.0, 100 * (pos.max() - 1)):.1f} %)")
    print(f"peak force       {abs(res['pid']).max():.1f} N (limit 50)")
    print(f"solver           {res.stats.solver if res.stats else '?'}, {len(res.t)} points")


def plot(res: SimResult) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(install matplotlib to see a plot)")
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    ax1.plot(res.t, res["reference"], "--", label="reference")
    ax1.plot(res.t, res["position"], label="position")
    ax1.set_ylabel("position [m]")
    ax1.legend()
    ax2.plot(res.t, res["pid"])
    ax2.set_ylabel("force [N]")
    ax2.set_xlabel("time [s]")
    fig.suptitle("PID control of a mass-spring-damper")
    plt.show()


def main(show_plot: bool = True) -> SimResult:
    d = build()
    auto_layout(d)  # give the blocks positions for the editor
    save(d, Path(__file__).with_suffix(".nervus"))
    res = simulate(d)
    report(res)
    if show_plot:
        plot(res)
    return res


if __name__ == "__main__":
    main()
