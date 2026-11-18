import pytest

from nervus import Diagram
from nervus.blocks import Gain, Integrator, Scope, Step, Sum


@pytest.fixture
def first_order() -> Diagram:
    """dy/dt = (u - y) / tau with tau = 0.5 and a unit step at t = 0."""
    d = Diagram("first_order")
    u = d.add(Step(time=0.0, final=1.0), name="u")
    err = d.add(Sum(signs="+-"), name="err")
    k = d.add(Gain(gain=2.0), name="k")
    y = d.add(Integrator(), name="y")
    scope = d.add(Scope(num_inputs=2), name="scope")
    d.connect(u, err.in_port(0))
    d.connect(y, err.in_port(1))
    d.chain(err, k, y)
    d.connect(u, scope.in_port(0))
    d.connect(y, scope.in_port(1))
    return d
