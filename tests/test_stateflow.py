"""Stateflow import: the sample models made in MATLAB R2025b (scripts/matlab) compute what Simulink computed."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from test_chart import run_chart

from nervus import Diagram, simulate
from nervus.blocks import Inport, Outport, RepeatingSequence, StateChart, ZeroOrderHold
from nervus.blocks.chart import parse_chart
from nervus.codegen.sil import back_to_back, find_compiler
from nervus.core.errors import ParameterError
from nervus.simulink import read_model
from nervus.stateflow import convert_chart, expression

SAMPLES = Path(__file__).parent.parent / "scripts" / "matlab" / "stateflow_samples"


@pytest.mark.parametrize("name", ["sf_lamp", "sf_gearbox"])
@pytest.mark.parametrize("suffix", [".slx", ".mdl"])
def test_samples_compute_what_simulink_computed(name: str, suffix: str) -> None:
    d = read_model(SAMPLES / f"{name}{suffix}")
    report = d.meta["simulink_report"]
    assert "Stateflow charts imported as State Charts (1)" in report
    assert "Not supported" not in report
    assert d.settings.t_final == 10 and d.settings.step == 0.01 and d.settings.solver == "euler"
    ref = np.genfromtxt(SAMPLES / f"{name}.csv", delimiter=",", names=True)
    r = simulate(d)
    at = np.searchsorted(np.round(r.t, 9), np.round(ref["t"], 9))  # the same sample times
    for out in ref.dtype.names[1:]:  # type: ignore[index]
        np.testing.assert_array_equal(r[out][at], ref[out], err_msg=out)


def test_gearbox_definition() -> None:
    text = read_model(SAMPLES / "sf_gearbox.slx").block("Gearbox").params["definition"]
    assert "first_sample: enter" in text
    assert "state Gearbox parallel" in text  # the parallel chart: one parallel top state
    assert "entry: gear = 0; shifts = 0" in text  # Gear's default transition action
    assert "transition Driving -> Parked: pedal < 0.05" in text  # through the junction
    assert "transition High -> Low within Gear: pedal < 0.3" in text  # drawn in Gear: leaves Driving
    assert "transition Busy -> Ok within chart: t_in_state >= 2" in text  # drawn at the top: leaves both regions
    assert "transition Low -> High: t_in_state >= 1 and pedal > 0.5" in text


@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
@pytest.mark.parametrize("name", ["sf_lamp", "sf_gearbox"])
def test_imported_chart_c_code(name: str, tmp_path: Path) -> None:
    src = read_model(SAMPLES / f"{name}.slx")
    chart = next(b for b in src.blocks if isinstance(b, StateChart))
    c = StateChart(definition=chart.params["definition"], sample_time=0.01, state_output=True)
    d = Diagram("sf")
    blk = d.add(c, name="chart")
    rng = np.random.default_rng(5)
    steps = 1200
    levels = {"speed": [0.0, 3.0, 20.0, 60.0], "pedal": [0.0, 0.04, 0.2, 0.4, 0.8]}
    inputs = {}
    for k, inp in enumerate(c.spec.inputs):
        d.chain(d.add(Inport(port=k + 1), name=inp), d.add(ZeroOrderHold(sample_time=0.01)))
        d.connect(d.blocks[-1], (blk, k))
        inputs[inp] = np.repeat(rng.choice(levels[inp], steps // 40 + 1), 40)[:steps]
    for k in range(c.num_outputs()):
        d.connect((blk, k), d.add(Outport(port=k + 1), name=f"y{k}"))
    res = back_to_back(d, inputs, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()


# ---------------------------------------------------------------------------- the chart language


def test_first_sample_enter_only() -> None:
    chart = "input u\noutput y\n{}state a\nstate b\n  entry: y = 1\ntransition a -> b: u > 0\n"
    out = run_chart(chart.format(""), {"u": [1, 1, 1]})
    assert list(out["y"]) == [1, 1, 1]  # entered and processed in the first sample
    out = run_chart(chart.format("first_sample: enter\n"), {"u": [1, 1, 1]})
    assert list(out["y"]) == [0, 1, 1]  # Stateflow: the first sample only enters
    with pytest.raises(ParameterError, match="first_sample"):
        parse_chart("first_sample: later\nstate a\n")


def test_within() -> None:
    chart = """
input u
output n, m
state top
  exit: m += 1
  state p
    exit: n += 1
    state a
    state b
transition a -> b {}: u > 0
transition b -> a {}: u < 0
"""
    u = [1, -1, 1, -1]
    out = run_chart(chart.format("", ""), {"u": u})
    assert list(out["n"]) == [0, 0, 0, 0]  # inside p: p stays active
    out = run_chart(chart.format("within top", "within top"), {"u": u})
    assert list(out["n"]) == [1, 2, 3, 4] and list(out["m"]) == [0, 0, 0, 0]  # leaves p, not top
    out = run_chart(chart.format("within chart", ""), {"u": u})
    assert list(out["m"]) == [1, 1, 2, 2]
    with pytest.raises(ParameterError, match="must contain both"):
        parse_chart(chart.format("within a", ""))
    with pytest.raises(ParameterError, match="unknown state"):
        parse_chart(chart.format("within nowhere", ""))


def test_repeating_sequence() -> None:
    d = Diagram("rs")
    d.chain(d.add(RepeatingSequence(times=[0, 2, 2, 4], values=[0, 4, 1, 1])), d.add(Outport(), name="y"))
    d.settings.solver, d.settings.step, d.settings.t_final = "euler", 0.5, 6.0
    r = simulate(d)
    expect = {0.0: 0, 1.0: 2, 1.5: 3, 2.0: 1, 3.0: 1, 4.0: 0, 5.0: 2}
    for t, v in expect.items():
        assert r["y"][np.argmin(abs(r.t - t))] == pytest.approx(v), t


# ---------------------------------------------------------------------------- the translation


def _state(ssid: int, label: str, pos: str = "[0 0 100 60]", kind: str = "OR_STATE", inner: str = "",
           order: int = 0) -> str:  # fmt: skip
    eo = f'<P Name="executionOrder">{order}</P>' if order else ""
    children = f"<Children>{inner}</Children>" if inner else ""
    return (f'<state SSID="{ssid}"><P Name="labelString">{label}</P><P Name="position">{pos}</P>'
            f'<P Name="type">{kind}</P><P Name="decomposition">CLUSTER_STATE</P>{eo}{children}</state>')  # fmt: skip


def _tr(ssid: int, src: int | None, dst: int, label: str = "", order: int = 1) -> str:
    s = f'<src><P Name="SSID">{src}</P></src>' if src is not None else "<src/>"
    return (f'<transition SSID="{ssid}"><P Name="labelString">{label}</P>{s}<dst><P Name="SSID">{dst}</P></dst>'
            f'<P Name="executionOrder">{order}</P></transition>')  # fmt: skip


def _data(name: str, scope: str, init: str = "", dtype: str = "double") -> str:
    iv = f'<P Name="initialValue">{init}</P>' if init else ""
    return (f'<data SSID="0" name="{name}"><P Name="scope">{scope}</P><props>{iv}<array><P Name="size">-1</P>'
            f'</array></props><P Name="dataType">{dtype}</P></data>')  # fmt: skip


def _chart(body: str, extra: str = "") -> str:
    return (f'<chart id="1"><P Name="name">C</P><P Name="decomposition">CLUSTER_CHART</P>'
            f'<P Name="updateMethod">DISCRETE</P><P Name="sampleTime">0.1</P>{extra}<Children>{body}</Children>'
            "</chart>")  # fmt: skip


def test_c_action_language_and_labels() -> None:
    body = (
        _state(1, "A\nen, du: n++; // count\nex: y = 0;")
        + _state(2, "B/ y = 1;", "[200 0 100 60]")
        + _tr(10, None, 1)
        + _tr(11, 1, 2, "[u != 0 &amp;&amp; !(n &gt; 3)]{k += 2;}/y = 5;")
        + _tr(12, 2, 1, "after(500, msec)")
        + _tr(13, 2, 1, "after(3, tick)[u == 0 || n &gt;= 10]", order=2)
        + _data("u", "INPUT_DATA")
        + _data("y", "OUTPUT_DATA", "2")
        + _data("n", "LOCAL_DATA")
        + _data("k", "LOCAL_DATA", dtype="int16")
    )
    r = convert_chart(_chart(body))
    text = r.definition
    assert r.sample_time == 0.1
    assert "output y = 2" in text and "local n, k" in text
    assert "entry: n += 1\n  during: n += 1\n  exit: y = 0" in text
    assert "state B\n  entry: y = 1" in text
    assert "transition A -> B: u != 0 and not (n > 3) / k += 2; y = 5" in text
    assert "transition B -> A: t_in_state >= 0.5" in text
    assert "transition B -> A: after(3) and (u == 0 or n >= 10)" in text
    assert any("'k' is int16" in n for n in r.notes)


def test_junction_paths() -> None:
    body = (
        _state(1, "Idle")
        + _state(2, "Low", "[200 0 100 60]")
        + _state(3, "High", "[200 200 100 60]")
        + '<junction SSID="9"><P Name="type">CONNECTIVE_JUNCTION</P></junction>'
        + _tr(10, None, 1)
        + _tr(11, 1, 9, "[go &gt; 0]{c = c + 1;}")
        + _tr(12, 9, 3, "[x &gt; 5]/lvl = 2;", order=1)
        + _tr(13, 9, 2, "/lvl = 1;", order=2)
        + _data("go", "INPUT_DATA")
        + _data("x", "INPUT_DATA")
        + _data("lvl", "OUTPUT_DATA")
        + _data("c", "OUTPUT_DATA")
    )
    text = convert_chart(_chart(body)).definition
    assert "transition Idle -> High: go > 0 and x > 5 / c = c + 1; lvl = 2" in text
    assert "transition Idle -> Low: go > 0 / c = c + 1; lvl = 1" in text
    assert text.index("Idle -> High") < text.index("Idle -> Low")  # the junction's order


def test_matlab_syntax_and_expression() -> None:
    notes: list[str] = []
    assert expression("~(a ~= b) && x^2 > mod(t, 3)", notes, "") == "not (a != b) and x**2 > ((t) % (3))"
    assert expression("before(2, sec) | c", notes, "") == "t_in_state < 2 or c"
    assert not notes
    expression("every(3, tick)", notes, "here")
    expression("foo(1)", notes, "there")
    assert any("every" in n for n in notes) and any("foo()" in n for n in notes)


def test_hierarchy_names_history_and_notes() -> None:
    inner_a = _state(2, "On", "[10 40 60 40]") + _state(3, "Off", "[10 100 60 40]") + _tr(20, None, 3)
    inner_b = (_state(5, "On", "[210 40 60 40]") + _state(6, "Off", "[210 100 60 40]") + _tr(21, None, 5)
               + '<junction SSID="30"><P Name="type">HISTORY_JUNCTION</P></junction>')  # fmt: skip
    body = (
        _state(1, "A", "[0 0 150 200]", inner=inner_a)
        + _state(4, "B", "[200 0 150 200]", inner=inner_b)
        + _state(7, "helper", kind="FUNC_STATE")
        + _tr(22, None, 4, "{y = 3;}")
        + _tr(23, 1, 4, "go")
        + _tr(24, 4, 6, "[u &gt; 1]")
        + _data("u", "INPUT_DATA")
        + _data("y", "OUTPUT_DATA")
        + '<event SSID="40" name="go"><P Name="scope">INPUT_EVENT</P></event>'
    )
    r = convert_chart(_chart(body))
    text = r.definition
    assert "initial B" in text  # the chart's default transition
    assert "output y = 3" in text  # its constant action is the initial value
    assert "state A\n\n  state Off" in text  # Off first: A's initial state
    assert "state B\n  history\n\n  state B_On" in text  # the second On renamed
    assert "transition A -> B: 0" in text  # an input event: never true
    notes = " ".join(r.notes)
    assert "renamed to 'B_On'" in notes and "function 'helper'" in notes and "input event" in notes
    assert "inner transition" in notes  # B -> B_Off (B contains B_Off)
    parse_chart(text)
