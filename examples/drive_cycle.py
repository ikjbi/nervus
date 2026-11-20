"""A car driving the ECE-15 urban drive cycle: vehicle longitudinal dynamics and a driver model.

Drive cycles are the speed-over-time profiles used for type approval and for comparing vehicles. The ECE-15
urban cycle (the city part of the old European NEDC, also called UDC) is 195 s long, reaches 50 km/h, and
covers 994 m. This example follows it with:

* **driver**: a PI controller on the speed error, plus feed-forward of the cycle's acceleration, giving a
  pedal command between -1 (full brake) and +1 (full throttle)
* **powertrain**: traction force limited by the maximum force and by the engine power (``F <= P_max / v``),
  and the brakes
* **road loads**: aerodynamic drag ``1/2·ρ·c_d·A·v²`` and rolling resistance ``m·g·c_rr``
* **vehicle**: ``m·dv/dt = F_traction - F_brake - F_aero - F_roll``

It reports the energy delivered at the wheels and a rough fuel estimate (average engine efficiency
``eta_engine``, no idle fuel). ``build("wltc3b")`` or ``build("ftp75")`` drive the official WLTC class 3b or FTP-75
instead (the Drive Cycle block); for another cycle use its ``csv_file`` option (time [s], speed [km/h]).

Run with ``uv run python examples/drive_cycle.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    PID,
    FromWorkspace,
    Gain,
    Inport,
    Integrator,
    MathFunction,
    Outport,
    Product,
    PythonFunction,
    Saturation,
    Scope,
    Subsystem,
    Sum,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
KMH = 1 / 3.6

# ECE-15 urban cycle: (time [s], speed [km/h]) corner points of the published profile.
ECE15 = [
    (0, 0), (11, 0), (15, 15), (23, 15), (28, 0), (49, 0), (61, 32), (85, 32), (96, 0), (117, 0),
    (143, 50), (155, 50), (163, 35), (176, 35), (188, 0), (195, 0),
]  # fmt: skip

POWERTRAIN = '''def f(t, pedal, v):
    """Wheel force [N] from the pedal (-1 brake .. +1 throttle). p = [F_max N, P_max W, F_brake_max N]"""
    if pedal >= 0:
        return pedal * min(p[0], p[1] / max(v, 0.5))  # traction: force limit, then power limit
    return pedal * p[2] * min(1.0, v / 0.2)  # brakes (fade out at standstill so the car does not roll back)
'''


def _place(d: Diagram, positions: dict[str, tuple[int, int]]) -> None:
    for name, (x, y) in positions.items():
        if name in d:
            d.block(name).meta["position"] = [float(x), float(y)]


def build_driver() -> Subsystem:
    """PI control of the speed error plus feed-forward of the cycle's acceleration -> pedal (-1 .. +1)."""
    d = Diagram("driver")
    v_ref = d.add(Inport(port=1), name="v_ref")
    a_ref = d.add(Inport(port=2), name="a_ref")
    v = d.add(Inport(port=3), name="v")
    err = d.add(Sum(signs="+-"), name="speed_error")
    # D = 0, so the derivative filter is unused; N = 1 keeps its state slow enough for a 0.1 s step.
    pi = d.add(PID(P="Kp_driver", I="Ki_driver", N=1.0), name="driver_pi")
    ff = d.add(Gain(gain="m / F_max"), name="feed_forward")
    total = d.add(Sum(signs="++"), name="pedal_sum")
    pedal = d.add(Saturation(upper=1.0, lower=-1.0), name="pedal")
    err_kmh = d.add(Gain(gain=3.6), name="tracking_error_kmh")
    d.connect(v_ref, err.in_port(0))
    d.connect(v, err.in_port(1))
    d.chain(err, pi)
    d.connect(pi, total.in_port(0))
    d.chain(a_ref, ff)
    d.connect(ff, total.in_port(1))
    d.chain(total, pedal, d.add(Outport(port=1), name="pedal_cmd"))
    d.chain(err, err_kmh, d.add(Outport(port=2), name="error_kmh"))
    _place(
        d,
        {
            "v_ref": (0, 0),
            "v": (0, 100),
            "speed_error": (150, 40),
            "driver_pi": (300, 40),
            "a_ref": (150, 200),
            "feed_forward": (300, 200),
            "pedal_sum": (450, 100),
            "pedal": (600, 100),
            "pedal_cmd": (750, 100),
            "tracking_error_kmh": (450, 300),
            "error_kmh": (600, 300),
        },
    )
    return Subsystem(system=d)


def build_vehicle() -> Subsystem:
    """Powertrain, road loads and the vehicle mass: pedal -> speed, distance, wheel power and energy."""
    d = Diagram("vehicle")
    pedal = d.add(Inport(port=1), name="pedal")
    pt = d.add(
        PythonFunction(code=POWERTRAIN, num_inputs=2, parameters="[F_max, P_max, F_brake_max]"), name="wheel_force"
    )
    net = d.add(Sum(signs="+--"), name="net_force")
    inv_m = d.add(Gain(gain="1 / m"), name="1/m")
    v = d.add(Integrator(initial=0.0, lower=0.0), name="speed")
    v2 = d.add(Product(ops="**"), name="v_squared")
    aero = d.add(Gain(gain="0.5 * 1.2 * cd_A"), name="F_aero")
    v_scaled = d.add(Gain(gain=10.0), name="v_x10")
    roll_sign = d.add(MathFunction(function="tanh"), name="rolling_onset")  # smooth sign(v)
    roll = d.add(Gain(gain="m * 9.81 * c_rr"), name="F_roll")
    x = d.add(Integrator(), name="distance")
    power = d.add(Product(ops="**"), name="wheel_power")
    traction = d.add(Saturation(upper=1e9, lower=0.0), name="traction_power")
    energy = d.add(Integrator(), name="wheel_energy_J")
    d.connect(pedal, pt.in_port(0))
    d.connect(v, pt.in_port(1))
    d.connect(pt, net.in_port(0))
    d.connect(aero, net.in_port(1))
    d.connect(roll, net.in_port(2))
    d.chain(net, inv_m, v, d.add(Outport(port=1), name="v_out"))
    d.connect(v, v2.in_port(0))
    d.connect(v, v2.in_port(1))
    d.chain(v2, aero)
    d.chain(v, v_scaled, roll_sign, roll)
    d.chain(v, x, d.add(Outport(port=2), name="distance_m"))
    d.connect(pt, power.in_port(0))
    d.connect(v, power.in_port(1))
    d.chain(power, traction, energy, d.add(Outport(port=3), name="energy_J"))
    d.connect(power, d.add(Outport(port=4), name="power_W"))
    _place(
        d,
        {
            "pedal": (0, 0),
            "wheel_force": (150, 0),
            "net_force": (300, 0),
            "1/m": (450, 0),
            "speed": (600, 0),
            "v_out": (900, 0),
            # Road loads are fed back from the speed, right to left (flipped blocks).
            "v_squared": (600, 150),
            "F_aero": (450, 150),
            "v_x10": (600, 260),
            "rolling_onset": (450, 260),
            "F_roll": (300, 260),
            "distance": (750, 120),
            "distance_m": (900, 120),
            "wheel_power": (450, 400),
            "traction_power": (600, 400),
            "wheel_energy_J": (750, 400),
            "energy_J": (900, 400),
            "power_W": (900, 500),
        },
    )
    for name in ("v_squared", "F_aero", "v_x10", "rolling_onset", "F_roll"):
        d.block(name).meta["flipped"] = True
    return Subsystem(system=d)


def build(cycle_name: str = "ece15") -> Diagram:
    """The car on a drive cycle: ``ece15`` (default, the tests use it), or ``wltc3b`` / ``ftp75`` from the
    Drive Cycle block with the official tables."""
    d = Diagram("drive_cycle")
    d.settings.t_final = 195.0
    d.settings.solver = "rk4"
    d.settings.step = 0.1
    ws = d.workspace
    ws.add(Variable("m", 1300.0, "Vehicle mass incl. driver", "kg"))
    ws.add(Variable("cd_A", 0.30 * 2.2, "Drag coefficient × frontal area", "m²"))
    ws.add(Variable("c_rr", 0.012, "Rolling resistance coefficient", "-"))
    ws.add(Variable("F_max", 4500.0, "Maximum traction force (1st gear)", "N"))
    ws.add(Variable("P_max", 66e3, "Maximum engine power", "W"))
    ws.add(Variable("F_brake_max", 9000.0, "Maximum brake force", "N"))
    ws.add(Variable("Kp_driver", 0.5, "Driver proportional gain", "1/(m/s)"))
    ws.add(Variable("Ki_driver", 0.05, "Driver integral gain", "1/m"))
    ws.add(Variable("eta_engine", 0.25, "Average engine + gearbox efficiency", "-"))

    t_pts = [t for t, _ in ECE15]
    v_pts = [v * KMH for _, v in ECE15]
    slopes = [(v_pts[k + 1] - v_pts[k]) / (t_pts[k + 1] - t_pts[k]) for k in range(len(t_pts) - 1)] + [0.0]
    if cycle_name == "ece15":
        cycle = d.add(FromWorkspace(time=t_pts, data=[[v] for v in v_pts], interpolation="linear"), name="drive_cycle")
        accel = d.add(  # the cycle is piecewise linear, so its acceleration is piecewise constant
            FromWorkspace(time=t_pts, data=[[a] for a in slopes], interpolation="hold"), name="cycle_accel"
        )
    else:
        from nervus.blocks import DriveCycle
        from nervus.cycles import cycle_stats

        cycle = d.add(DriveCycle(cycle=cycle_name, unit="m/s"), name="drive_cycle")
        accel = cycle.out_port(1)  # type: ignore[assignment]
        d.settings.t_final = cycle_stats(cycle_name)["duration_s"]
    driver = d.add(build_driver(), name="driver")
    vehicle = d.add(build_vehicle(), name="vehicle")
    cycle_kmh = d.add(Gain(gain=3.6), name="cycle_kmh")
    speed_kmh = d.add(Gain(gain=3.6), name="speed_kmh")
    scope = d.add(Scope(num_inputs=2), name="speed_scope")
    d.connect(cycle, driver.in_port(0))
    d.connect(accel, driver.in_port(1))
    d.connect(vehicle.out_port(0), driver.in_port(2))
    d.connect(driver.out_port(0), vehicle.in_port(0))
    d.connect(driver.out_port(1), d.add(Scope(), name="error_scope"))
    d.chain(cycle, cycle_kmh)
    d.connect(vehicle.out_port(0), speed_kmh)
    d.connect(cycle_kmh, scope.in_port(0))
    d.connect(speed_kmh, scope.in_port(1))
    d.connect(vehicle.out_port(1), d.add(Scope(), name="distance_scope"))
    d.connect(vehicle.out_port(2), d.add(Scope(), name="energy_scope"))
    d.connect(vehicle.out_port(3), d.add(Scope(), name="power_scope"))
    _place(
        d,
        {
            "drive_cycle": (0, 0),
            "cycle_accel": (0, 120),
            "driver": (220, 40),
            "vehicle": (520, 40),
            "error_scope": (520, 220),
            "cycle_kmh": (220, 320),
            "speed_kmh": (820, 320),
            "speed_scope": (1000, 320),
            "distance_scope": (1000, 0),
            "energy_scope": (1000, 100),
            "power_scope": (1000, 200),
        },
    )
    d.tests = [
        TestCase(
            "driver follows the cycle",
            "The speed stays within ±2 km/h of the cycle, and the distance matches the 994 m of ECE-15",
            checks=[
                Check("bounds", "driver/tracking_error_kmh", {"lower": -2.0, "upper": 2.0}),
                Check("final_value", "vehicle/distance", {"value": 994.0, "tolerance": 10.0}),
            ],
        ),
        TestCase(
            "wheel energy of the 1300 kg car",
            "About 340 kJ for one ECE-15 cycle (9.5 kWh/100 km)",
            checks=[Check("final_value", "vehicle/wheel_energy_J", {"value": 340e3, "tolerance": 10e3})],
        ),
        TestCase(
            "heavier car needs more energy",
            "500 kg more: about 35 % more energy; accelerating and rolling grow with the mass, only drag does not",
            parameters={"m": 1800.0},
            checks=[Check("final_value", "vehicle/wheel_energy_J", {"value": 460e3, "tolerance": 12e3})],
        ),
    ]
    return d


def summary(res: SimResult, d: Diagram) -> dict[str, float]:
    distance_km = float(res["vehicle/distance"][-1]) / 1000
    energy_j = float(res["vehicle/wheel_energy_J"][-1])
    energy_kwh = energy_j / 3.6e6
    fuel_l = energy_j / d.workspace["eta_engine"] / 43e6 / 0.745  # petrol: 43 MJ/kg, 0.745 kg/l
    return {
        "distance_km": distance_km,
        "max_error_kmh": float(np.max(np.abs(res["speed_kmh"] - res["cycle_kmh"]))),
        "wheel_energy_kwh_per_100km": energy_kwh / distance_km * 100,
        "fuel_l_per_100km": fuel_l / distance_km * 100,
    }


def main() -> SimResult:
    d = build()
    save(d, HERE / "drive_cycle.nervus")
    res = simulate(d)
    for k, v in summary(res, d).items():
        print(f"{k:28s} {v:8.2f}")
    from nervus.testing import run_tests

    for r in run_tests(d):
        print(r.summary())
    return res


if __name__ == "__main__":
    main()
