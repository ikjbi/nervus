"""Electronic throttle position control, the way an ECU does it.

A throttle body is modelled as a first-order actuator: the plate angle follows the commanded duty cycle with a
time constant of 50 ms, and moves between 0° (closed) and 90° (wide open). Its position sensor is read by an ECU
task running every 10 ms (Zero-Order Hold), and a Discrete PI controller with clamping anti-windup computes the
duty cycle, limited to 0–100 %.

The pedal (target angle) steps from 5° (idle) to 60°, then back to 20°.

Run with ``uv run python examples/throttle_pi.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import DiscretePID, FromWorkspace, Gain, Integrator, Scope, Sum, ZeroOrderHold
from nervus.core.layout import auto_layout

TAU = 0.05  # s, actuator time constant
GAIN = 0.9  # degrees per % duty cycle at steady state
TS = 0.01  # s, ECU task period


def build() -> Diagram:
    d = Diagram("throttle_pi")
    d.settings.t_final = 2.0

    target = d.add(
        FromWorkspace(time=[0.0, 0.2, 1.2], data=[5.0, 60.0, 20.0], interpolation="hold"), name="target_angle"
    )
    sensor = d.add(ZeroOrderHold(sample_time=TS), name="tps_sample")
    err = d.add(Sum(signs="+-"), name="error")
    pi = d.add(
        DiscretePID(P=1.5, I=40.0, upper=100.0, lower=0.0, anti_windup="clamping", sample_time=TS),
        name="throttle_pi",
    )

    # Actuator: angle' = (GAIN * duty - angle) / TAU, limited to 0..90 degrees
    k = d.add(Gain(gain=GAIN), name="deg_per_pct")
    lag = d.add(Sum(signs="+-"), name="lag")
    inv_tau = d.add(Gain(gain=1 / TAU), name="1/tau")
    angle = d.add(Integrator(initial=5.0, lower=0.0, upper=90.0), name="plate_angle")
    scope = d.add(Scope(num_inputs=3), name="scope")

    d.chain(angle, sensor)
    d.connect(target, err.in_port(0))
    d.connect(sensor, err.in_port(1))
    d.chain(err, pi, k)
    d.connect(k, lag.in_port(0))
    d.connect(angle, lag.in_port(1))
    d.chain(lag, inv_tau, angle)

    d.connect(target, scope.in_port(0))
    d.connect(angle, scope.in_port(1))
    d.connect(pi, scope.in_port(2))
    return d


def report(res: SimResult) -> None:
    t, angle = res.t, res["plate_angle"]
    for t_check, target in ((1.15, 60.0), (1.95, 20.0)):
        a = float(np.interp(t_check, t, angle))
        print(f"t = {t_check:4.2f} s: angle {a:6.2f}° (target {target:.0f}°)")
    print(f"duty cycle range {res['throttle_pi'].min():.1f} – {res['throttle_pi'].max():.1f} %")


def plot(res: SimResult) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(install matplotlib to see a plot)")
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    ax1.step(res.t, res["target_angle"], "--", where="post", label="target")
    ax1.plot(res.t, res["plate_angle"], label="plate angle")
    ax1.set_ylabel("angle [°]")
    ax1.legend()
    ax2.step(res.t, res["throttle_pi"], where="post")
    ax2.set_ylabel("duty cycle [%]")
    ax2.set_xlabel("time [s]")
    fig.suptitle("Electronic throttle control (10 ms discrete PI)")
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
