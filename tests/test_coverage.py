import numpy as np

from nervus import Diagram, load, simulate
from nervus.blocks import Constant, Lookup1D, Saturation, Scope, Sine, StateChart, Switch, ZeroOrderHold
from nervus.coverage import Coverage
from nervus.testing import run_tests

EXAMPLES = __import__("pathlib").Path(__file__).parent.parent / "examples"


def test_switch_and_saturation_coverage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram()
    s = d.add(Sine(amplitude=2.0), name="u")
    sat = d.add(Saturation(upper=1.0, lower=-5.0), name="sat")  # never below -5
    sw = d.add(Switch(threshold=0.0), name="sw")
    d.chain(s, sat)
    d.connect(d.add(Constant(value=1.0)), (sw, 0))
    d.connect(sat, (sw, 1))
    d.connect(d.add(Constant(value=0.0)), (sw, 2))
    d.connect(sw, d.add(Scope()))
    cov = Coverage()
    simulate(d, 10.0, coverage=cov)
    assert cov.blocks["sw"].covered == 2
    assert cov.blocks["sat"].missed == ["below lower"]
    assert cov.covered == 4 and cov.total == 5
    assert "never below lower" in cov.summary()
    page = cov.save_html(tmp_path / "c.html").read_text()
    assert "80 %" in page and 'class="miss">below lower' in page


def test_lookup_intervals_and_chart() -> None:
    d = Diagram()
    s = d.add(Sine(amplitude=1.5), name="u")
    z = d.add(ZeroOrderHold(sample_time=0.1), name="z")
    lut = d.add(Lookup1D(breakpoints=[-1, 0, 1, 2], table=[0, 1, 2, 3]), name="lut")
    chart = d.add(StateChart(sample_time=0.1), name="chart")  # default: low/high hysteresis on 1 / 0
    d.chain(s, lut, d.add(Scope()))
    d.chain(s, z, chart)
    d.connect((chart, 0), d.add(Scope()))
    d.connect((chart, 1), d.add(Scope()))
    cov = Coverage()
    simulate(d, 10.0, coverage=cov)
    assert cov.blocks["lut"].missed == ["[1, 2]", "above range"] or set(cov.blocks["lut"].missed) <= {"above range"}
    assert cov.blocks["chart"].covered == cov.blocks["chart"].total  # both states and both transitions


def test_coverage_of_a_test_suite() -> None:
    model = load(EXAMPLES / "throttle_ecu.nervus")
    cov = Coverage()
    results = run_tests(model, base_dir=EXAMPLES, coverage=cov)
    assert all(r.passed for r in results)
    assert cov.runs == 3
    assert 0 < cov.percent <= 100
    assert np.isfinite(cov.percent)
