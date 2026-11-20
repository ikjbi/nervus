import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    DiscretePID,
    Gain,
    Inport,
    MovingAverage,
    Outport,
    RateTransition,
    Subsystem,
    Sum,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.codegen import CodegenError, generate_c


def two_tasks(with_transitions: bool = True) -> Diagram:
    """A 10 ms filter feeds a 100 ms controller, whose output a 10 ms actuator task uses."""
    d = Diagram("ecu")
    sensor = d.add(Inport(port=1), name="sensor")
    target_in = d.add(Inport(port=2), name="target")
    target = d.add(ZeroOrderHold(sample_time=0.1), name="target_100ms")  # an ECU samples its inputs
    d.connect(target_in, target)
    filt = d.add(MovingAverage(length=4, sample_time=0.01), name="filter_10ms")
    err = d.add(Sum(signs="+-"), name="error")
    pid = d.add(DiscretePID(P=0.5, I=2.0, sample_time=0.1), name="pid_100ms")
    act = d.add(Gain(gain=2.0), name="actuator")
    act_task = d.add(UnitDelay(sample_time=0.01), name="actuator_10ms")
    d.chain(sensor, filt)
    if with_transitions:
        f2s = d.add(RateTransition(direction="fast_to_slow", sample_time=0.1), name="rt_f2s")
        s2f = d.add(RateTransition(direction="slow_to_fast", sample_time=0.1, output_sample_time=0.01), name="rt_s2f")
        d.connect(filt, f2s)
        d.connect(target, (err, 0))
        d.connect(f2s, (err, 1))
        d.chain(err, pid, s2f, act, act_task)
    else:
        d.connect(target, (err, 0))
        d.connect(filt, (err, 1))
        d.chain(err, pid, act, act_task)
    d.connect(act_task, d.add(Outport(port=1), name="cmd"))
    return d


def test_rate_transition_simulation_semantics() -> None:
    r = simulate(two_tasks(), 1.0, solver="rk4", step=0.01, inputs={"sensor": 1.0, "target": 2.0})
    t = r.t
    k = int(np.argmin(abs(t - 0.1)))
    assert r["rt_s2f"][k] == r["pid_100ms"][int(np.argmin(abs(t - 0.0)))]  # one slow period late
    assert r["rt_f2s"][int(np.argmin(abs(t - 0.15)))] == r["filter_10ms"][int(np.argmin(abs(t - 0.1)))]  # held


@pytest.mark.parametrize("tasks", [False, True])
def test_task_functions_match_simulation(tmp_path, tasks: bool) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    k = np.arange(150)
    inputs = {"sensor": np.sin(0.07 * k) + 0.1 * (k % 3), "target": 1.0 + (k > 60)}
    res = back_to_back(two_tasks(), inputs, 150, tolerance=1e-12, folder=tmp_path, tasks=tasks)
    assert res.passed, res.summary()


def test_task_functions_in_the_code() -> None:
    code = generate_c(two_tasks(), tasks=True)
    h, c = code.files["ecu.h"], code.files["ecu.c"]
    assert "void ecu_task_10ms(void);" in h and "void ecu_task_100ms(void);" in h
    assert "void ecu_task_10ms(void)" in c and "if (rt_hit[1] != 0u) { ecu_task_100ms(); }" in c


def test_missing_rate_transition_is_reported() -> None:
    with pytest.raises(CodegenError, match=r"different rates.*insert a Rate Transition"):
        generate_c(two_tasks(with_transitions=False), tasks=True)
    generate_c(two_tasks(with_transitions=False))  # the single step function handles it (no RTOS)


def test_atomic_task_subsystems() -> None:
    d = Diagram("tasks")
    u = d.add(Inport(port=1), name="u")
    fast_sys, slow_sys = Diagram(), Diagram()
    for sys_ in (fast_sys, slow_sys):
        i = sys_.add(Inport(port=1), name="i")
        sys_.chain(i, sys_.add(Gain(gain=2.0), name="g"), sys_.add(Outport(port=1), name="o"))
    fast = d.add(Subsystem(system=fast_sys, sample_time=0.01), name="fast")
    slow = d.add(Subsystem(system=slow_sys, sample_time=0.1), name="slow")
    rt = d.add(RateTransition(sample_time=0.1), name="rt")
    d.chain(u, fast, rt, slow, d.add(Outport(port=1), name="y"))
    code = generate_c(d, tasks=True)
    assert "tasks_task_100ms" in code.files["tasks.c"]
