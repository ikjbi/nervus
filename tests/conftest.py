import os

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


_EXIT_STATUS = 0


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config) -> None:  # type: ignore[no-untyped-def]
    """In CI, skip Python's interpreter teardown once results (and coverage) are reported.

    PySide6 can crash while Python deallocates its objects at exit ("none_dealloc"), which turns a green run
    red. The exit status of the test session is preserved.
    """
    if os.environ.get("NERVUS_HARD_EXIT") == "1":
        import sys

        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_EXIT_STATUS)
