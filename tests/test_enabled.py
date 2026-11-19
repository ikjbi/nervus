import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import (
    Clock,
    CompareToConstant,
    Constant,
    Counter,
    Inport,
    Integrator,
    Outport,
    Pulse,
    Scope,
    Subsystem,
    ZeroOrderHold,
)


def counting_subsystem(reset: bool = False) -> Subsystem:
    inner = Diagram()
    u = inner.add(Inport(port=1), name="u")
    c = inner.add(Counter(limit=1000, sample_time=0.1), name="count")
    i = inner.add(Integrator(), name="integral")
    inner.chain(u, c, inner.add(Outport(port=1), name="n"))
    inner.connect(u, i)
    inner.connect(i, inner.add(Outport(port=2), name="area"))
    return Subsystem(system=inner, enable_port=True, when_enabled="reset" if reset else "held")


def model(reset: bool = False) -> Diagram:
    d = Diagram()
    en = d.add(Pulse(period=2.0, duty=50.0), name="enable")  # on 0-1 s, off 1-2 s, on 2-3 s ...
    s = d.add(counting_subsystem(reset), name="task")
    d.connect(d.add(Constant(value=1.0)), (s, 0))
    d.connect(en, (s, 1))
    d.connect((s, 0), d.add(Scope()))
    d.connect((s, 1), d.add(Scope()))
    return d


def test_enable_port_counts_and_holds() -> None:
    sub = counting_subsystem()
    assert sub.num_inputs() == 2
    r = simulate(model(), 4.0, solver="rk4", step=0.05)
    t, n, area = r.t, r["task/count"], r["task/integral"]
    at = lambda x: int(np.argmin(abs(t - x)))  # noqa: E731
    assert n[at(0.95)] == pytest.approx(9)  # counted every 0.1 s while enabled
    assert n[at(1.5)] == n[at(1.95)]  # held while disabled
    assert area[at(1.5)] == pytest.approx(1.0, abs=1e-6)  # integral stops while disabled
    assert area[at(3.0)] == pytest.approx(2.0, abs=1e-6)
    assert n[at(2.95)] > n[at(1.95)]  # counting continues when enabled again


def test_reset_on_enable() -> None:
    r = simulate(model(reset=True), 4.0, solver="rk4", step=0.05)
    t, n = r.t, r["task/count"]
    at = lambda x: int(np.argmin(abs(t - x)))  # noqa: E731
    assert n[at(2.95)] == n[at(0.95)]  # restarted from 0 at t = 2


def test_enable_must_be_connected() -> None:
    d = Diagram()
    s = d.add(counting_subsystem(), name="task")
    d.connect(d.add(Constant()), (s, 0))
    d.connect((s, 0), d.add(Scope()))
    d.connect((s, 1), d.add(Scope()))
    assert any("input 1 of 'task'" in i.message for i in d.check())


def test_codegen_enabled_subsystem(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("enabled")
    u = d.add(Inport(port=1), name="u")
    en_in = d.add(Inport(port=2), name="en")
    zu, ze = d.add(ZeroOrderHold(sample_time=0.1)), d.add(ZeroOrderHold(sample_time=0.1))
    inner = Diagram()
    i1 = inner.add(Inport(port=1), name="x")
    cnt = inner.add(Counter(limit=1000, sample_time=0.1), name="count")
    inner.chain(i1, cnt, inner.add(Outport(port=1), name="n"))
    s = d.add(Subsystem(system=inner, enable_port=True, when_enabled="reset"), name="task")
    d.chain(u, zu)
    d.chain(en_in, ze)
    d.connect(zu, (s, 0))
    d.connect(ze, (s, 1))
    d.connect(s, d.add(Outport(port=1), name="n_out"))
    steps = 60
    k = np.arange(steps)
    res = back_to_back(d, {"u": 1.0, "en": ((k // 10) % 2 == 0).astype(float)}, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
    assert res.c["n_out"].max() >= 9


def test_clock_enable_compare() -> None:
    d = Diagram()
    clk = d.add(Clock())
    gate = d.add(CompareToConstant(operator=">=", constant=1.0), name="after_1s")
    s = d.add(counting_subsystem(), name="task")
    d.chain(clk, gate)
    d.connect(d.add(Constant()), (s, 0))
    d.connect(gate, (s, 1))
    d.connect((s, 1), d.add(Scope()))
    d.connect((s, 0), d.add(Scope()))
    r = simulate(d, 2.0, solver="rk4", step=0.05)
    assert r["task/integral"][-1] == pytest.approx(1.0, abs=0.06)


def triggered_model(edge: str) -> Diagram:
    d = Diagram()
    trig = d.add(Pulse(period=1.0, duty=50.0, sample_time=0.1), name="trig")  # rising at 1, 2, 3, ...
    inner = Diagram()
    u = inner.add(Inport(port=1), name="u")
    cnt = inner.add(Counter(limit=1000, sample_time=0.1), name="count")
    inner.chain(u, cnt, inner.add(Outport(port=1), name="n"))
    s = d.add(Subsystem(system=inner, trigger=edge), name="task")
    d.connect(d.add(Constant()), (s, 0))
    d.connect(trig, (s, 1))
    d.connect(s, d.add(Scope()))
    return d


@pytest.mark.parametrize(("edge", "edges"), [("rising", 4), ("falling", 5), ("either", 9)])
def test_triggered_subsystem_counts_edges(edge: str, edges: int) -> None:
    r = simulate(triggered_model(edge), 4.95, solver="euler", step=0.05)
    # The counter outputs its count before the update, so after n edges it shows n - 1.
    assert r["task/count"][-1] == edges - 1
    assert r["task/count"][0] == 0  # nothing runs before the first edge


def test_triggered_rejects_continuous_states() -> None:
    from nervus import ModelError

    d = Diagram()
    inner = Diagram()
    u = inner.add(Inport(port=1), name="u")
    inner.chain(u, inner.add(Integrator()), inner.add(Outport(port=1), name="y"))
    s = d.add(Subsystem(system=inner, trigger="rising"), name="task")
    d.connect(d.add(Constant()), (s, 0))
    d.connect(d.add(Pulse()), (s, 1))
    d.connect(s, d.add(Scope()))
    with pytest.raises(ModelError, match="triggered"):
        simulate(d, 1.0)


@pytest.mark.parametrize("edge", ["rising", "falling", "either"])
def test_codegen_triggered_subsystem(tmp_path, edge: str) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("triggered")
    u = d.add(Inport(port=1), name="u")
    tr_in = d.add(Inport(port=2), name="tr")
    en_in = d.add(Inport(port=3), name="en")
    zs = [d.add(ZeroOrderHold(sample_time=0.1)) for _ in range(3)]
    inner = Diagram()
    i1 = inner.add(Inport(port=1), name="x")
    cnt = inner.add(Counter(limit=1000, sample_time=0.1), name="count")
    inner.chain(i1, cnt, inner.add(Outport(port=1), name="n"))
    s = d.add(Subsystem(system=inner, enable_port=True, when_enabled="reset", trigger=edge), name="task")
    for src, z in zip((u, en_in, tr_in), zs, strict=True):  # data, enable, trigger
        d.chain(src, z)
    for k, z in enumerate(zs):
        d.connect(z, (s, k))
    d.connect(s, d.add(Outport(port=1), name="n_out"))
    steps = 80
    k = np.arange(steps)
    inputs = {"u": 1.0, "tr": ((k // 3) % 2).astype(float), "en": (k < 50).astype(float) + (k > 60)}
    res = back_to_back(d, inputs, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
    assert res.c["n_out"].max() >= 3
