import pytest

from nervus import Diagram, ModelError, compile_diagram
from nervus.blocks import (
    Constant,
    Demux,
    Gain,
    Integrator,
    Mux,
    Scope,
    Sine,
    Sum,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core import AlgebraicLoopError
from nervus.sim.compiler import Kind


def test_unconnected_input_is_error() -> None:
    d = Diagram()
    d.add(Gain(), name="g")
    with pytest.raises(ModelError, match="not connected") as exc:
        compile_diagram(d)
    assert exc.value.blocks == ("g",)


def test_execution_order_respects_feedthrough(first_order: Diagram) -> None:
    m = compile_diagram(first_order)
    names = [b.name for b in m.blocks]
    # err needs u and y (y is an integrator, no feedthrough); k needs err.
    assert names.index("u") < names.index("err") < names.index("k")


def test_algebraic_loop_detected() -> None:
    d = Diagram()
    c = d.add(Constant(), name="c")
    s = d.add(Sum(signs="+-"), name="s")
    g = d.add(Gain(gain=2), name="g")
    d.connect(c, (s, 0))
    d.connect(g, (s, 1))
    d.connect(s, g)
    with pytest.raises(AlgebraicLoopError) as exc:
        compile_diagram(d)
    assert set(exc.value.blocks) == {"s", "g"}
    assert "->" in str(exc.value)


def test_vector_width_propagation_through_loop() -> None:
    d = Diagram()
    c = d.add(Constant(value=[1.0, 2.0, 3.0]), name="c")
    s = d.add(Sum(signs="+-"), name="s")
    i = d.add(Integrator(), name="i")
    d.connect(c, (s, 0))
    d.connect(i, (s, 1))
    d.connect(s, i)
    m = compile_diagram(d)
    assert m.out_widths[m.index_of("i")] == [3]
    assert m.n_continuous_states == 3


def test_width_mismatch() -> None:
    d = Diagram()
    a = d.add(Constant(value=[1.0, 2.0]))
    b = d.add(Constant(value=[1.0, 2.0, 3.0]))
    s = d.add(Sum(), name="s")
    d.connect(a, (s, 0))
    d.connect(b, (s, 1))
    with pytest.raises(ModelError, match="incompatible"):
        compile_diagram(d)


def test_mux_demux_widths() -> None:
    d = Diagram()
    a = d.add(Constant(value=[1.0, 2.0]))
    b = d.add(Constant(value=[3.0, 4.0]))
    m = d.add(Mux(), name="m")
    dm = d.add(Demux(num_outputs=4), name="dm")
    sc = d.add(Scope(num_inputs=4))
    d.connect(a, (m, 0))
    d.connect(b, (m, 1))
    d.connect(m, dm)
    for k in range(4):
        d.connect((dm, k), (sc, k))
    model = compile_diagram(d)
    assert model.out_widths[model.index_of("m")] == [4]
    assert model.out_widths[model.index_of("dm")] == [1, 1, 1, 1]


def test_sample_time_inheritance() -> None:
    d = Diagram()
    src = d.add(Sine(), name="src")
    zoh = d.add(ZeroOrderHold(sample_time=0.1), name="zoh")
    g = d.add(Gain(), name="g")
    c = d.add(Constant(), name="c")
    g2 = d.add(Gain(), name="g2")
    sc = d.add(Scope(num_inputs=2))
    d.chain(src, zoh, g)
    d.connect(c, g2)
    d.connect(g, (sc, 0))
    d.connect(g2, (sc, 1))
    m = compile_diagram(d)
    kinds = {b.name: k for b, k in zip(m.blocks, m.kinds, strict=True)}
    assert kinds["src"] is Kind.CONTINUOUS
    assert kinds["zoh"] is Kind.DISCRETE
    assert kinds["g"] is Kind.DISCRETE
    assert kinds["c"] is Kind.CONSTANT
    assert kinds["g2"] is Kind.CONSTANT
    assert len(m.rates) == 1


def test_unit_delay_needs_discrete_time() -> None:
    d = Diagram()
    src = d.add(Sine())
    ud = d.add(UnitDelay(), name="ud")
    d.chain(src, ud, d.add(Scope()))
    with pytest.raises(ModelError, match="discrete sample time"):
        compile_diagram(d)


def test_discrete_feedback_with_inherited_delay() -> None:
    d = Diagram()
    zoh = d.add(ZeroOrderHold(sample_time=0.5), name="zoh")
    src = d.add(Constant(value=1.0))
    s = d.add(Sum(), name="s")
    ud = d.add(UnitDelay(), name="ud")
    d.connect(src, zoh)
    d.connect(zoh, (s, 0))
    d.connect(ud, (s, 1))
    d.connect(s, ud)
    m = compile_diagram(d)
    assert m.sample_times[m.index_of("ud")].period == 0.5
