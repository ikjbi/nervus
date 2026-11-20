"""Radiator fan control: a classic ECU on/off function.

The coolant temperature rises with engine heat and falls when the electric fan runs. The ECU reads the
temperature sensor every 10 ms, smooths it with a first-order filter, and switches the fan with a relay that
has hysteresis (on at 98 °C, off at 92 °C) so the fan does not chatter. A 1-D lookup table turns the engine
load into heat input.

Run with ``uv run python examples/coolant_fan.py``.
"""

from __future__ import annotations

from pathlib import Path

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Bias,
    DiscreteFilter,
    FromWorkspace,
    Gain,
    Integrator,
    Lookup1D,
    Relay,
    Scope,
    Sum,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable
from nervus.core.layout import auto_layout


def build() -> Diagram:
    d = Diagram("coolant_fan")
    d.settings.t_final = 600.0
    ws = d.workspace
    ws.add(Variable("T_on", 98.0, "Fan switch-on temperature", "°C"))
    ws.add(Variable("T_off", 92.0, "Fan switch-off temperature", "°C"))
    ws.add(Variable("Ts", 0.01, "ECU task period", "s"))
    ws.add(Variable("tau_sensor", 2.0, "Sensor filter time constant", "s"))
    ws.add(Variable("C_th", 40.0, "Thermal capacity of the cooling circuit", "kJ/K"))
    ws.add(Variable("P_fan", 25.0, "Cooling power of the fan", "kW"))

    load = d.add(
        FromWorkspace(time=[0, 120, 300, 420, 600], data=[20, 80, 80, 30, 30], interpolation="linear"),
        name="engine_load",
    )
    heat_map = d.add(Lookup1D(breakpoints=[0, 50, 100], table=[5, 18, 40]), name="heat_kW")
    net = d.add(Sum(signs="+--"), name="net_heat")
    natural = d.add(Gain(gain=0.2), name="natural_cooling")
    temp_rate = d.add(Gain(gain="1/C_th"), name="1/C_th")
    temp = d.add(Integrator(initial=85.0), name="coolant_temp")
    sensor = d.add(ZeroOrderHold(sample_time="Ts"), name="sensor")
    filt = d.add(DiscreteFilter(time_constant="tau_sensor", initial=85.0), name="temp_filtered")
    fan = d.add(Relay(on_point="T_on", off_point="T_off", on_value=1.0, off_value=0.0), name="fan_on")
    fan_power = d.add(Gain(gain="P_fan"), name="fan_cooling")
    ambient_drop = d.add(Bias(bias=-25.0), name="above_ambient")  # natural cooling ~ T - T_ambient
    scope = d.add(Scope(num_inputs=3), name="scope")

    d.chain(load, heat_map)
    d.connect(heat_map, net.in_port(0))
    d.connect(fan_power, net.in_port(1))
    d.connect(natural, net.in_port(2))
    d.chain(net, temp_rate, temp)
    d.chain(temp, ambient_drop, natural)
    d.chain(temp, sensor, filt, fan, fan_power)
    d.connect(temp, scope.in_port(0))
    d.connect(filt, scope.in_port(1))
    d.connect(fan, scope.in_port(2))
    d.tests = [
        TestCase(
            "coolant stays below 100 °C",
            "The fan holds the coolant below boiling (100 °C at the radiator cap's pressure is the limit used here)",
            stop_time=600.0,
            checks=[Check("bounds", "coolant_temp", {"upper": 100.0})],
        )
    ]
    return d


def report(res: SimResult) -> None:
    fan = res["fan_on"]
    switches = int((abs(fan[1:] - fan[:-1]) > 0.5).sum())
    print(f"max coolant temperature {res['coolant_temp'].max():.1f} °C")
    print(f"fan switched {switches} times; on {100 * fan.mean():.0f} % of the time")


def main(show_plot: bool = True) -> SimResult:
    d = build()
    auto_layout(d)
    save(d, Path(__file__).with_suffix(".nervus"))
    res = simulate(d, solver="rk4", step=0.01)
    report(res)
    if show_plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return res
        _fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(8, 5))
        a1.plot(res.t, res["coolant_temp"], label="coolant")
        a1.plot(res.t, res["temp_filtered"], label="filtered sensor")
        a1.axhline(98, ls=":", color="grey")
        a1.axhline(92, ls=":", color="grey")
        a1.set_ylabel("°C")
        a1.legend()
        a2.step(res.t, res["fan_on"], where="post")
        a2.set_ylabel("fan on")
        a2.set_xlabel("time [s]")
        plt.show()
    return res


if __name__ == "__main__":
    main()
