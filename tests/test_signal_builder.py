"""Signal Builder: the text format, the block and its groups."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import Scope, SignalBuilder
from nervus.blocks.signal_builder import parse_signals, signals_to_text
from nervus.core.errors import ParameterError

TEXT = """group tip_in
  pedal: 0 0, 1 0, 1 80, 6 80, 6 0
  brake: 0 0
group panic
  pedal: 0 30, 2 30, 2 0
  brake: 0 0, 2 0, 2.5 100
"""


def test_parse_and_write_back() -> None:
    groups = parse_signals(TEXT)
    assert [g.name for g in groups] == ["tip_in", "panic"]
    pedal = groups[0].signal("pedal")
    assert pedal.value(0.5) == 0 and pedal.value(1.0) == 80 and pedal.value(3) == 80 and pedal.value(9) == 0
    assert groups[1].signal("brake").value(2.25) == pytest.approx(50.0)  # linear between points
    assert parse_signals(signals_to_text(groups))[1].signal("brake").times == [0, 2, 2.5]


@pytest.mark.parametrize(("text", "message"), [
    ("pedal: 0 0, 1", "time value"),
    ("pedal: 1 0, 0 1", "must increase"),
    ("pedal: 0 0, 1 0, 1 1, 1 2", "three points"),
    ("group a\n  x: 0 0\ngroup b\n  y: 0 0\n", "must have the signals x"),
    ("group a\n  x: 0 zero\n", "not a number"),
    ("", "at least one signal"),
])  # fmt: skip
def test_errors_name_the_line(text: str, message: str) -> None:
    with pytest.raises(ParameterError, match=message):
        parse_signals(text)


def test_block_plays_the_chosen_group() -> None:
    d = Diagram("sb")
    b = d.add(SignalBuilder(definition=TEXT), name="sig")
    assert b.num_outputs() == 2 and b.output_names() == ["pedal", "brake"]
    d.connect((b, 0), d.add(Scope(), name="s0"))
    d.connect((b, 1), d.add(Scope(), name="s1"))
    r = simulate(d, 4.0)
    pedal = np.ravel(r.signal("sig", 0))
    assert pedal[np.searchsorted(r.t, 1.0)] == 80.0  # the jump is exact: the solver stops at every point
    assert np.max(r.signal("sig", 1)) == 0.0
    b.set_param("group", "panic")
    r = simulate(d, 4.0)
    assert np.interp(2.25, r.t, np.ravel(r.signal("sig", 1))) == pytest.approx(50.0)
    assert b.suggestions("group") == ["tip_in", "panic"]
    with pytest.raises(ParameterError, match="no group 'nope'"):
        b.set_param("group", "nope")
        b.validate_params()
