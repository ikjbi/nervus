"""A sensor signal chain in fixed point, the way it runs on an ECU without a floating-point unit.

A manifold pressure sensor gives 0.5–4.5 V, read by a 12-bit ADC (0–4095 counts, ``uint16``). The ECU
converts counts to kPa and smooths the value with a first-order filter, then compares it against a limit.

Two versions run side by side:

* ``*_dbl``: everything in ``double`` (the reference),
* ``*_fix``: pressure in ``fixdt(0, 16, 6)`` (unsigned 16 bit, resolution 1/64 kPa ≈ 0.016 kPa), like
  production code.

The difference shows the quantization error, which stays below the fixed-point resolution plus the ADC step.
Run with ``uv run python examples/fixed_point_sensor.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Bias,
    CompareToConstant,
    DataTypeConversion,
    DiscreteFilter,
    Gain,
    Scope,
    Sine,
    Sum,
    ZeroOrderHold,
)
from nervus.core.layout import auto_layout

HERE = Path(__file__).parent
KPA_PER_COUNT = 250.0 / 4095.0 * (5.0 / 4.0)  # 0.5–4.5 V spans 20–270 kPa; 12-bit ADC on 0–5 V


def build() -> Diagram:
    d = Diagram("fixed_point_sensor")
    d.settings.t_final = 2.0
    d.settings.solver = "rk4"
    d.settings.step = 0.001
    pressure = d.add(Sine(amplitude=60.0, frequency=2 * np.pi * 1.5, bias=100.0), name="true_pressure_kPa")
    # Sensor + ADC: kPa -> volts -> counts (uint16), sampled every 10 ms
    to_counts = d.add(Gain(gain=1 / KPA_PER_COUNT), name="kPa_to_counts")
    offset = d.add(Bias(bias=-20.0 / KPA_PER_COUNT), name="sensor_offset")
    adc = d.add(DataTypeConversion(output_type="uint16", rounding="floor"), name="adc_counts")
    sample = d.add(ZeroOrderHold(sample_time=0.01), name="adc_sample")
    d.chain(pressure, offset, to_counts, adc, sample)
    # Reference chain in double
    scale_dbl = d.add(Gain(gain=KPA_PER_COUNT, output_type="double"), name="scale_dbl")
    off_dbl = d.add(Bias(bias=20.0), name="kPa_dbl")
    filt_dbl = d.add(DiscreteFilter(time_constant=0.05), name="filtered_dbl")
    d.chain(sample, scale_dbl, off_dbl, filt_dbl)
    # Production chain in fixed point
    scale_fix = d.add(Gain(gain=KPA_PER_COUNT, output_type="fixdt(0, 16, 6)"), name="scale_fix")
    off_fix = d.add(Bias(bias=20.0), name="kPa_fix")  # inherits fixdt(0, 16, 6)
    filt_fix = d.add(DiscreteFilter(time_constant=0.05), name="filtered_fix")  # inherits as well
    over = d.add(CompareToConstant(operator=">", constant=150.0), name="over_150kPa")
    d.chain(sample, scale_fix, off_fix, filt_fix, over)
    err = d.add(Sum(signs="+-", output_type="double"), name="fixed_minus_double")
    d.connect(filt_fix, err.in_port(0))
    d.connect(filt_dbl, err.in_port(1))
    scope = d.add(Scope(num_inputs=3), name="scope")
    d.connect(filt_dbl, scope.in_port(0))
    d.connect(filt_fix, scope.in_port(1))
    d.connect(err, scope.in_port(2))
    auto_layout(d)
    return d


def main() -> SimResult:
    d = build()
    save(d, HERE / "fixed_point_sensor.nervus")
    res = simulate(d)
    e = res["fixed_minus_double"]
    print(f"largest fixed-point error: {np.max(np.abs(e)):.4f} kPa (resolution {2**-6:.4f} kPa)")
    print(f"distinct fixed-point values are multiples of 1/64: {np.allclose(np.mod(res['filtered_fix'] * 64, 1), 0)}")
    return res


if __name__ == "__main__":
    main()
