"""Condition coverage and MC/DC (modified condition/decision coverage)."""

import pytest

from nervus import Diagram
from nervus.blocks import FromWorkspace, LogicalOperator, Scope
from nervus.coverage import ConditionCoverage, Coverage
from nervus.sim.simulator import simulate


def _seen(op: str, n: int, vectors: list[str]) -> ConditionCoverage:
    c = ConditionCoverage("d", op, n)
    for v in vectors:
        c.record(tuple(ch == "1" for ch in v))
    return c


def test_and_needs_n_plus_one_evaluations() -> None:
    """The classic minimal MC/DC set for a 3-input AND: all true, and each condition false alone."""
    c = _seen("AND", 3, ["111", "011", "101", "110"])
    assert c.mcdc() == (3, 3) and c.condition_outcomes() == (6, 6)


def test_condition_coverage_is_not_mcdc() -> None:
    """000 and 111 make every condition true and false (100 % condition coverage), but show none independently."""
    c = _seen("AND", 3, ["000", "111"])
    assert c.condition_outcomes() == (6, 6) and c.mcdc() == (0, 3)
    need = c.needed(1)
    assert "(1, 0, 1) → 0" in need  # with 111 seen, one more evaluation shows condition 2


@pytest.mark.parametrize(("op", "vectors", "done"), [
    ("OR", ["000", "100", "010", "001"], 3),
    ("OR", ["100", "010"], 0),
    ("XOR", ["00", "10"], 1),
    ("NAND", ["11", "01", "10"], 2),
    ("NOR", ["00", "10"], 1),
])  # fmt: skip
def test_other_operators(op: str, vectors: list[str], done: int) -> None:
    assert _seen(op, len(vectors[0]), vectors).mcdc()[0] == done


def _model(a: list[float], b: list[float], c: list[float]) -> Diagram:
    d = Diagram("logic")
    t = [float(k) for k in range(len(a))]
    srcs = [d.add(FromWorkspace(time=t, data=[[v] for v in vals], interpolation="hold"), name=n)
            for n, vals in (("enable", a), ("speed_ok", b), ("no_fault", c))]  # fmt: skip
    gate = d.add(LogicalOperator(operator="AND", num_inputs=3), name="permit")
    for k, s in enumerate(srcs):
        d.connect(s, (gate, k))
    d.connect(gate, d.add(Scope(), name="scope"))
    return d


def test_measured_in_a_simulation() -> None:
    cov = Coverage()
    simulate(_model([1, 0, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0]), 3.5, coverage=cov)
    c = cov.conditions["permit"]
    assert [c.independent(i) for i in range(3)] == [True, False, True]
    assert cov.mcdc_percent == pytest.approx(200 / 3)
    missing = cov.mcdc_missing()["permit"]
    assert missing == ["condition 2: needs (1, 0, 1) → 0 (the pair (1, 1, 1) → 1 / (1, 0, 1) → 0)"]
    text = cov.summary()
    assert "MC/DC 67 %" in text and "permit: condition 2" in text
    assert "Condition and MC/DC coverage" in cov.to_html()
