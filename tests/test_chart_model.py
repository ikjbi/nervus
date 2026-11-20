"""The editable chart behind the graphical chart editor: text -> states and transitions -> text."""

from pathlib import Path

import numpy as np
import pytest

from nervus import Diagram, load, simulate
from nervus.blocks import Inport, Outport, StateChart
from nervus.blocks.chart import parse_chart
from nervus.blocks.chart_model import ETransition, auto_layout, from_text
from nervus.core.errors import ParameterError

ROOT = Path(__file__).parent.parent


def _charts() -> list[tuple[str, str]]:
    """Every chart in the example models and the chart tests."""
    import test_chart
    import test_chart_hierarchy

    out = [("ENGINE", test_chart.ENGINE), ("POWER", test_chart_hierarchy.POWER),
           ("HISTORY", test_chart_hierarchy.HISTORY)]  # fmt: skip
    for path in sorted((ROOT / "examples").glob("*.nervus")):
        for _path, b in load(path).walk():
            if b.type_id == "charts.state_chart":
                out.append((f"{path.stem}/{b.name}", str(b.params["definition"])))
    return out


def _shape(text: str) -> tuple:  # type: ignore[type-arg]
    s = parse_chart(text)
    return (s.inputs, s.outputs, s.locals, s.params, s.events, s.initial,
            [(st.name, st.parent, st.children, st.parallel, st.initial, st.history, st.entry_src, st.during_src,
              st.exit_src) for st in s.states],
            [(t.source, t.target, t.guard_src, t.action_src) for t in s.transitions])  # fmt: skip


@pytest.mark.parametrize(("name", "text"), _charts(), ids=lambda x: x if isinstance(x, str) and "\n" not in x else "")
def test_round_trip_keeps_the_chart(name: str, text: str) -> None:
    again = from_text(text).to_text()
    assert _shape(again) == _shape(text)
    assert from_text(again).to_text() == again  # stable


def test_round_trip_simulates_the_same() -> None:
    import test_chart_hierarchy

    def run(text: str) -> np.ndarray:
        d = Diagram("c")
        spec = parse_chart(text)
        c = d.add(StateChart(definition=text, sample_time=0.01), name="chart")
        for k, n in enumerate(spec.inputs):
            d.connect(d.add(Inport(port=k + 1, value=float(k % 2)), name=n), (c, k))
        d.connect((c, 0), d.add(Outport(port=1), name="y"))
        return np.ravel(simulate(d, 1.0)["y"])

    text = test_chart_hierarchy.POWER
    assert np.array_equal(run(text), run(from_text(text).to_text()))


def test_initial_values_are_kept_as_written() -> None:
    text = "output rpm = 800, y = 2.5, z = 1e-3\nstate a\n"
    chart = from_text(text)
    assert chart.outputs == [("rpm", "800"), ("y", "2.5"), ("z", "1e-3")]
    assert "output rpm = 800, y = 2.5, z = 1e-3" in chart.to_text()


def test_edits() -> None:
    chart = from_text("input u\noutput y\nstate low\n  entry: y = 0\nstate high\n  entry: y = 1\n"
                      "transition low -> high: u > 1\ntransition high -> low: u < 0\n")  # fmt: skip
    # add a composite state with children, a transition with an action, and reorder priorities
    chart.add_state("fault")
    chart.add_state("latched", parent="fault", entry="y = -1")
    chart.add_state("cleared", parent="fault")
    chart.state("fault").initial = "cleared"
    chart.transitions.append(ETransition("high", "fault", "u > 10", "y = 5"))
    chart.move_priority(chart.transitions[-1], -1)
    assert [t.target for t in chart.outgoing("high")] == ["fault", "low"]
    assert chart.priority(chart.transitions[1]) == 1
    text = chart.to_text()
    assert "transition high -> fault: u > 10 / y = 5" in text and "  initial cleared" in text
    assert parse_chart(text).states[parse_chart(text).states[2].initial or 0].name == "cleared"
    # composite boxes surround their children
    _fx, _fy, fw, fh = chart.layout["fault"]
    for kid in ("latched", "cleared"):
        x, y, w, h = chart.layout[kid]
        assert x >= 0 and y >= 0 and x + w <= fw and y + h <= fh
    # rename everywhere, remove with the children and transitions
    chart.rename_state("high", "on")
    assert {t.source for t in chart.transitions} == {"low", "on"} and "on" in chart.layout
    chart.remove_state("fault")
    assert [s.name for s in chart.states] == ["low", "on"] and len(chart.transitions) == 2
    with pytest.raises(ValueError, match="already"):
        chart.rename_state("on", "low")
    with pytest.raises(ValueError, match="valid"):
        chart.rename_state("on", "2x")


def test_invalid_edits_are_reported_with_the_line() -> None:
    chart = from_text("input u\noutput y\nstate a\nstate b\ntransition a -> b: u > 1\n")
    chart.transitions[0].guard = "w > 1"
    with pytest.raises(ParameterError, match="unknown name 'w'"):
        chart.to_text()


def test_layout_is_kept_and_completed() -> None:
    chart = from_text("output y\nstate a\nstate b\nstate c\n", layout={"a": [500, 40, 120, 60], "zz": [0, 0, 1, 1]})
    assert chart.layout["a"] == [500.0, 40.0, 120.0, 60.0] and "zz" not in chart.layout
    assert set(chart.layout) == {"a", "b", "c"}
    boxes = [chart.layout[n] for n in ("a", "b", "c")]
    for i, p in enumerate(boxes):
        for q in boxes[i + 1 :]:
            assert p[0] + p[2] <= q[0] or q[0] + q[2] <= p[0] or p[1] + p[3] <= q[1] or q[1] + q[3] <= p[1]
    auto_layout(chart)  # nothing moves
    assert chart.layout["a"] == [500.0, 40.0, 120.0, 60.0]
