from nervus import Diagram, load
from nervus.advisor import RULES, advise
from nervus.blocks import (
    DiscretePID,
    Inport,
    Integrator,
    Lookup1D,
    Outport,
    Product,
    RelationalOperator,
    Scope,
    Sine,
    StateChart,
    Subsystem,
    UnitDelay,
)
from nervus.core import Variable

EXAMPLES = __import__("pathlib").Path(__file__).parent.parent / "examples"


def rules_of(d: Diagram) -> set[str]:
    return {f.rule for f in advise(d)}


def test_finds_common_problems() -> None:
    d = Diagram()
    d.workspace.add(Variable("unused", 1.0))
    s = d.add(Sine(), name="s")
    rel = d.add(RelationalOperator(operator="=="), name="eq")
    prod = d.add(Product(ops="*/"), name="ratio")
    pid = d.add(DiscretePID(I=1.0, upper=1.0, sample_time=0.01), name="pid")
    ud = d.add(UnitDelay(sample_time=0.1), name="ud")
    lut = d.add(Lookup1D(extrapolation="linear"), name="lut")
    chart = d.add(
        StateChart(
            definition="state a\nstate b\nstate c\ntransition a -> b: true\ntransition a -> c: 1 > 0", sample_time=0.1
        ),
        name="chart",
    )
    d.connect(s, (rel, 0))
    d.connect(s, (rel, 1))
    d.connect(s, (prod, 0))
    d.connect(s, (prod, 1))
    d.chain(s, pid, d.add(Scope()))
    d.chain(s, ud, d.add(Scope()))
    d.chain(s, lut, d.add(Scope()))
    d.connect((chart, 0), d.add(Scope()))
    for b in (rel, prod):
        d.connect(b, d.add(Scope()))
    found = rules_of(d)
    assert {
        "float-equality",
        "division",
        "antiwindup",
        "implicit-sampling",
        "lookup-extrapolation",
        "workspace-docs",
        "workspace-unused",
        "chart-shadowed",
    } <= found
    shadow = [f for f in advise(d) if f.rule == "chart-shadowed"]
    assert "a -> c" in shadow[0].message
    assert advise(d)[0].severity == "warning"


def test_unreachable_state_and_default_names() -> None:
    d = Diagram()
    inner = Diagram()
    i = inner.add(Inport(port=1), name="In1")
    g = inner.add(Integrator(), name="Integrator")
    inner.chain(i, g, inner.add(Outport(port=1), name="Out1"))
    d.add(Subsystem(system=inner), name="plant")
    d.add(
        StateChart(definition="input u\nstate a\nstate b\nstate island\ntransition a -> b: u > 1", sample_time=0.1),
        name="c",
    )
    found = advise(d)
    assert any(f.rule == "chart-unreachable" and "island" in f.message for f in found)
    assert any(f.rule == "default-names" and f.blocks == ("plant/Integrator",) for f in found)


def test_examples_are_mostly_clean() -> None:
    findings = advise(load(EXAMPLES / "throttle_ecu.nervus"))
    assert not [f for f in findings if f.severity == "warning"], findings
    assert len(RULES) >= 9
