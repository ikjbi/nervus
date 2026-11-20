"""Requirements traceability."""

from pathlib import Path

import pytest

from nervus import Diagram, load, save
from nervus.advisor import advise
from nervus.blocks import Gain, Scope, Step
from nervus.core import Check, TestCase
from nervus.core.errors import ParameterError
from nervus.core.requirements import Requirement, read_csv, trace, write_csv, write_report


def _model() -> Diagram:
    d = Diagram("req")
    d.chain(d.add(Step(), name="u"), d.add(Gain(gain=2.0), name="k"), d.add(Scope(), name="sc"))
    for rid, title in (("R1", "Gain of two"), ("R2", "Step at 1 s"), ("R3", "Not done yet")):
        d.requirements.add(Requirement(rid, title, f"The model shall … ({rid})"))
    d.block("k").meta["requirements"] = ["R1"]
    d.block("u").meta["requirements"] = ["R2", "R9"]  # R9 does not exist
    d.tests = [
        TestCase("gain", checks=[Check("bounds", "k", {"upper": 2.0})], requirements=["R1"]),
        TestCase("step", checks=[Check("bounds", "u", {"upper": 0.5})], requirements=["R2"]),
    ]
    return d


def test_trace_statuses_and_files(tmp_path: Path) -> None:
    d = _model()
    status = {r.requirement.id: r.status for r in trace(d)}
    assert status == {"R1": "not run", "R2": "not run", "R3": "not implemented"}
    from nervus.testing import run_tests

    results = {r.case.name: r.passed for r in run_tests(d)}
    assert results == {"gain": True, "step": False}
    rows = {r.requirement.id: r for r in trace(d, results)}
    assert rows["R1"].status == "verified" and rows["R2"].status == "failed"
    assert rows["R1"].blocks == ["k"] and rows["R2"].tests == ["step"]
    html = write_report(d, tmp_path / "trace.html", results).read_text()
    assert "verified" in html and "unknown requirement R9" in html
    again = read_csv(write_csv(d, tmp_path / "trace.csv", results))
    assert [r.id for r in again] == ["R1", "R2", "R3"] and again[0].title == "Gain of two"
    # Saved with the model.
    save(d, tmp_path / "m")
    m = load(tmp_path / "m.nervus")
    assert m.requirements["R3"].title == "Not done yet" and m.tests[0].requirements == ["R1"]


def test_csv_variants_and_advisor(tmp_path: Path) -> None:
    f = tmp_path / "reqs.csv"
    f.write_text(
        "ID;Name;Description\nIDLE-1;Idle speed;800 rpm when warm\n;;\nIDLE-2;Stall;No stall\n", encoding="utf-8"
    )
    reqs = read_csv(f)
    assert [(r.id, r.title, r.text) for r in reqs] == [("IDLE-1", "Idle speed", "800 rpm when warm"),
                                                        ("IDLE-2", "Stall", "No stall")]  # fmt: skip
    g = tmp_path / "plain.csv"
    g.write_text("A1,First\nA2,Second\n")
    assert [r.id for r in read_csv(g)] == ["A1", "A2"]
    with pytest.raises(ParameterError):
        Requirement("bad,id")
    msgs = [f.message for f in advise(_model(), ["requirements"])]
    assert any("R3 is not linked to any block" in m for m in msgs)
    assert any("unknown requirement R9" in m for m in msgs)
