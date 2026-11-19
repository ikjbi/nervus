import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Counter, Inport, Outport, Scope, Sine, StateChart, Subsystem, ZeroOrderHold

CHART = """
input u
output calls = 0

state low
state high
  entry: calls = calls + 1

transition low -> high: u > 0.5
transition high -> low: u < -0.5
"""


def model(with_inport: bool = False) -> Diagram:
    d = Diagram("fc")
    src = d.add(Inport(port=1), name="u") if with_inport else d.add(Sine(frequency=2 * np.pi), name="u")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="zoh")
    chart = d.add(StateChart(definition=CHART, state_output=False, sample_time=0.01), name="chart")
    inner = Diagram()
    i = inner.add(Inport(port=1), name="x")
    inner.chain(i, inner.add(Counter(limit=1000, sample_time=0.01), name="n"), inner.add(Outport(port=1), name="count"))
    fc = d.add(Subsystem(system=inner, trigger="function_call"), name="logger")
    d.chain(src, z, chart)
    d.connect(z, (fc, 0))
    d.connect(chart, (fc, 1))
    d.connect(fc, d.add(Outport(port=1), name="count_out") if with_inport else d.add(Scope()))
    return d


def test_function_call_runs_once_per_call() -> None:
    r = simulate(model(), 3.05, solver="rk4", step=0.01)
    calls = r["chart"][-1]
    assert calls == 3  # the sine goes above 0.5 three times in 3 s
    # The counter output shows the count before its own update: after 3 calls it shows 2.
    assert r["logger/n"][-1] == calls - 1


def test_function_call_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    k = np.arange(300)
    res = back_to_back(
        model(with_inport=True), {"u": np.sin(2 * np.pi * 0.01 * k)}, 300, tolerance=0.0, folder=tmp_path
    )
    assert res.passed, res.summary()
    assert res.c["count_out"][-1, 0] == 2
