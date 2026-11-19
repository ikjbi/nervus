import numpy as np
import pytest

from nervus import Diagram
from nervus.analysis import linearize, trim
from nervus.blocks import Gain, Inport, Integrator, Outport, PythonFunction, Sum, TransferFunction


def io(block) -> Diagram:  # type: ignore[no-untyped-def]
    d = Diagram()
    u = d.add(Inport(port=1), name="u")
    b = d.add(block, name="g")
    d.chain(u, b, d.add(Outport(port=1), name="y"))
    return d


def test_first_order_tf() -> None:
    lin = linearize(io(TransferFunction(numerator=[2.0], denominator=[0.5, 1.0])))
    num, den = lin.transfer_function()
    np.testing.assert_allclose(num / den[0], [4.0], rtol=1e-6)
    np.testing.assert_allclose(den / den[0], [1.0, 2.0], rtol=1e-6)
    assert lin.dc_gain() == pytest.approx(2.0, rel=1e-6)
    np.testing.assert_allclose(lin.poles(), [-2.0], rtol=1e-6)
    assert lin.is_stable()
    _t, y = lin.step_response(np.linspace(0, 5, 200))
    assert y[-1] == pytest.approx(2.0, rel=1e-3)


def test_bode_and_margins() -> None:
    # Open loop L(s) = 10 / (s (s+1) (0.1 s + 1)): classic textbook example.
    lin = linearize(
        io(TransferFunction(numerator=[10.0], denominator=np.polymul([1, 0], np.polymul([1, 1], [0.1, 1]))))
    )
    _w, mag, phase = lin.bode(np.array([1e-3, 1.0, 100.0]))
    assert mag[0] == pytest.approx(20 * np.log10(10 / 1e-3), abs=0.01)
    assert phase[0] == pytest.approx(-90.0, abs=0.5)
    m = lin.margins()
    # Phase crossover at w = sqrt(10) rad/s, |L| there = 10/(sqrt10*sqrt11*sqrt1.1) -> GM = 20 log10(1.1) dB.
    assert m.phase_crossover == pytest.approx(np.sqrt(10.0), rel=1e-3)
    assert m.gain_margin_db == pytest.approx(20 * np.log10(1.1), abs=0.05)
    assert 0 < m.phase_margin_deg < 10


def nonlinear_tank() -> Diagram:
    """Tank level h: A dh/dt = q_in - k sqrt(h)."""
    d = Diagram()
    q = d.add(Inport(port=1, value=2.0), name="q_in")
    out = d.add(PythonFunction(code="def f(t, h):\n    return 0.5 * math.sqrt(max(h, 0.0))\n"), name="outflow")
    s = d.add(Sum(signs="+-"), name="net")
    a = d.add(Gain(gain=1 / 3.0), name="1/A")
    h = d.add(Integrator(initial=1.0), name="h")
    d.connect(q, (s, 0))
    d.connect(out, (s, 1))
    d.chain(s, a, h, out)
    d.connect(h, d.add(Outport(port=1), name="level"))
    return d


def test_trim_and_linearize_nonlinear() -> None:
    d = nonlinear_tank()
    op = trim(d, {"q_in": 2.0})
    assert op.x[0] == pytest.approx(16.0, rel=1e-6)  # 0.5 sqrt(h) = 2
    assert op.residual < 1e-9
    lin = linearize(d, x0=op.x, u0=op.u)
    # d(dh/dt)/dh = -(0.5 / (2 sqrt 16)) / 3 = -1/48
    np.testing.assert_allclose(lin.A, [[-1 / 48]], rtol=1e-5)
    np.testing.assert_allclose(lin.B, [[1 / 3]], rtol=1e-5)
    assert lin.states == ["h"]
    assert lin.inputs == ["q_in"] and lin.outputs == ["level"]
    assert d.block("q_in").signal is None  # the model is left unchanged


def test_mass_spring_damper_poles() -> None:
    d = Diagram()
    f = d.add(Inport(port=1), name="F")
    s = d.add(Sum(signs="+--"), name="sum")
    v = d.add(Integrator(), name="v")
    x = d.add(Integrator(), name="x")
    c = d.add(Gain(gain=0.4), name="c")
    k = d.add(Gain(gain=4.0), name="k")
    d.connect(f, (s, 0))
    d.connect(c, (s, 1))
    d.connect(k, (s, 2))
    d.chain(s, v, x)
    d.connect(v, c)
    d.connect(x, k)
    d.connect(x, d.add(Outport(port=1), name="pos"))
    lin = linearize(d)
    poles = sorted(lin.poles(), key=lambda z: z.imag)
    np.testing.assert_allclose(poles, np.roots([1, 0.4, 4.0])[np.argsort(np.roots([1, 0.4, 4.0]).imag)], rtol=1e-5)
