import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Constant, Integrator, Pulse, Scope, Sine


def model(mode: str, reset_block=None) -> Diagram:  # type: ignore[no-untyped-def]
    d = Diagram()
    i = d.add(Integrator(external_reset=mode, initial=0.5), name="int")
    d.connect(d.add(Constant(value=1.0)), (i, 0))
    d.connect(reset_block if reset_block is not None else d.add(Pulse(period=2.0, duty=25.0, start=0.5)), (i, 1))
    d.connect(i, d.add(Scope()))
    return d


def pulse_model(mode: str) -> Diagram:
    d = Diagram()
    i = d.add(Integrator(external_reset=mode, initial=0.5), name="int")
    d.connect(d.add(Constant(value=1.0)), (i, 0))
    d.connect(d.add(Pulse(period=2.0, duty=25.0, delay=1.0), name="r"), (i, 1))  # high 1.0-1.5, 3.0-3.5 s
    d.connect(i, d.add(Scope()))
    return d


@pytest.mark.parametrize("solver", [{"solver": "rk4", "step": 0.01}, {}])
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("rising", 0.5 + 1.0),  # reset at 3.0 s, then 1 s more
        ("falling", 0.5 + 0.5),  # reset at 3.5 s
        ("either", 0.5 + 0.5),
        ("level", 0.5 + 0.5),  # held at 0.5 from 3.0 to 3.5 s
    ],
)
def test_reset_modes(mode: str, expected: float, solver: dict) -> None:  # type: ignore[type-arg]
    r = simulate(pulse_model(mode), 4.0, **solver)
    assert r["int"][-1] == pytest.approx(expected, abs=2e-3)


def test_reset_on_a_continuous_signal_is_located_exactly() -> None:
    d = Diagram()
    i = d.add(Integrator(external_reset="rising"), name="int")
    d.connect(d.add(Constant(value=1.0)), (i, 0))
    d.connect(d.add(Sine(frequency=np.pi, phase=-np.pi / 2)), (i, 1))  # -cos(pi t): rises through 0 at t = 0.5, 2.5
    d.connect(i, d.add(Scope()))
    r = simulate(d, 3.0)
    assert r["int"][-1] == pytest.approx(0.5, abs=1e-6)  # restarted at t = 2.5


def test_no_reset_input_is_unchanged() -> None:
    assert Integrator().num_inputs() == 1 and Integrator(external_reset="rising").input_names()[1] == "reset (rising)"
