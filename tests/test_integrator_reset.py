import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Constant, DiscreteIntegrator, FromWorkspace, Inport, Outport, Scope, ZeroOrderHold


def counting(mode: str, method: str = "forward_euler") -> Diagram:
    d = Diagram("reset_int")
    r = d.add(  # reset pulse at 0.5 s, high for 0.3 s
        FromWorkspace(time=[0.0, 0.5, 0.8], data=[[0.0], [1.0], [0.0]], interpolation="hold"), name="reset_sig"
    )
    i = d.add(DiscreteIntegrator(external_reset=mode, method=method, sample_time=0.1), name="acc")
    d.connect(d.add(Constant(value=1.0)), (i, 0))
    d.connect(r, (i, 1))
    d.connect(i, d.add(Scope()))
    return d


def _plain() -> Diagram:
    d = Diagram()
    i = d.add(DiscreteIntegrator(sample_time=0.1), name="acc")
    d.chain(d.add(Constant(value=1.0)), i, d.add(Scope()))
    return d


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("none", 1.5),  # 15 steps of 0.1 (no reset input: same as without)
        ("rising", 1.0),  # reset at 0.5 s, then 1.0 s more
        ("falling", 0.7),  # reset at 0.8 s
        ("either", 0.7),
        ("level", 0.8),  # output 0 at 0.5-0.7 s; integrates again from the update at 0.7 s (8 steps)
    ],
)
def test_reset_modes(mode: str, expected: float) -> None:
    d = counting(mode) if mode != "none" else _plain()
    r = simulate(d, 1.5, solver="rk4", step=0.05)
    assert r["acc"][-1] == pytest.approx(expected, abs=1e-9)


def test_reset_output_is_initial_at_the_reset_step() -> None:
    r = simulate(counting("rising"), 0.6, solver="rk4", step=0.1)
    k = int(np.argmin(abs(r.t - 0.5)))
    assert r["acc"][k] == 0.0 and r["acc"][k - 1] == pytest.approx(0.4)


@pytest.mark.parametrize("mode", ["rising", "falling", "either", "level"])
@pytest.mark.parametrize("method", ["forward_euler", "backward_euler"])
def test_reset_codegen_matches(tmp_path, mode: str, method: str) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = Diagram("reset_int")
    u = d.add(Inport(port=1), name="u")
    r = d.add(Inport(port=2), name="r")
    zu, zr = d.add(ZeroOrderHold(sample_time=0.01)), d.add(ZeroOrderHold(sample_time=0.01))
    i = d.add(DiscreteIntegrator(external_reset=mode, method=method, initial=0.5, upper=3.0, sample_time=0.01))
    d.chain(u, zu)
    d.chain(r, zr)
    d.connect(zu, (i, 0))
    d.connect(zr, (i, 1))
    d.connect(i, d.add(Outport(port=1), name="y"))
    k = np.arange(120)
    res = back_to_back(
        d, {"u": 5.0 + np.sin(k * 0.3), "r": ((k // 17) % 2).astype(float)}, 120, tolerance=1e-12, folder=tmp_path
    )
    assert res.passed, res.summary()


def test_input_names() -> None:
    assert DiscreteIntegrator(external_reset="rising").input_names() == ["u", "reset (rising)"]
    assert DiscreteIntegrator().input_names() == ["u"]
