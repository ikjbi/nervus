import numpy as np
import pytest

from nervus import Diagram, ModelError, simulate
from nervus.blocks import Counter, Gain, Inport, Integrator, Outport, Scope, Sine, Subsystem, UnitDelay


def task(period: float, inner_block=None) -> Subsystem:  # type: ignore[no-untyped-def]
    d = Diagram()
    u = d.add(Inport(port=1), name="u")
    g = d.add(inner_block if inner_block is not None else Gain(gain=2.0), name="work")
    d.chain(u, g, d.add(Outport(port=1), name="y"))
    return Subsystem(system=d, sample_time=period)


def test_task_samples_inputs_and_holds_outputs() -> None:
    d = Diagram()
    s = d.add(task(0.1), name="task_10ms")
    d.chain(d.add(Sine(), name="sine"), s, d.add(Scope()))
    from nervus.sim.compiler import compile_diagram

    m = compile_diagram(d)
    assert m.sample_times[m.index_of("task_10ms/work")].period == 0.1
    r = simulate(d, 1.0, solver="rk4", step=0.01)
    t, y = r.t, r["task_10ms/work"]
    k = int(np.argmin(abs(t - 0.35)))  # between hits at 0.3 and 0.4: holds 2 * sin(0.3)
    assert y[k] == pytest.approx(2 * np.sin(0.3), abs=1e-9)


def test_inherited_counter_runs_at_task_rate_and_inner_rate_wins() -> None:
    d = Diagram()
    outer_sys = Diagram()
    i = outer_sys.add(Inport(port=1), name="i")
    inner = outer_sys.add(task(0.5, Counter(limit=1000)), name="slow")
    fast = outer_sys.add(Counter(limit=1000), name="fast_count")
    outer_sys.chain(i, inner, outer_sys.add(Outport(port=1), name="o1"))
    outer_sys.chain(i, fast, outer_sys.add(Outport(port=2), name="o2"))
    outer = d.add(Subsystem(system=outer_sys, sample_time=0.1), name="ecu")
    d.chain(d.add(Sine(bias=2.0)), outer)
    d.connect((outer, 0), d.add(Scope()))
    d.connect((outer, 1), d.add(Scope()))
    r = simulate(d, 2.0, solver="rk4", step=0.01)
    assert r["ecu/fast_count"][-1] == 20  # every 0.1 s (outputs before the update at t = 2.0)
    assert r["ecu/slow/work"][-1] == 4  # every 0.5 s


def test_continuous_states_rejected() -> None:
    d = Diagram()
    s = d.add(task(0.1, Integrator()), name="task")
    d.chain(d.add(Sine()), s, d.add(Scope()))
    with pytest.raises(ModelError, match="discrete sample time"):
        simulate(d, 1.0)


def test_two_tasks_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("tasks")
    u = d.add(Inport(port=1), name="u")
    fast = d.add(task(0.01, UnitDelay(sample_time=-1)), name="task_10ms")
    slow = d.add(task(0.1, Counter(limit=1000)), name="task_100ms")
    d.chain(u, fast, d.add(Outport(port=1), name="y_fast"))
    d.connect(u, slow)
    d.connect(slow, d.add(Outport(port=2), name="y_slow"))
    k = np.arange(100)
    res = back_to_back(d, {"u": np.sin(0.1 * k) + 1.5}, 100, tolerance=1e-12, folder=tmp_path)
    assert res.passed, res.summary()
    assert res.c["y_slow"][-1, 0] == 9
