"""Requirements-based testing: the idle speed controller with its requirements, test cases and coverage.

The requirements of the idle speed function are in ``examples/data/idle_requirements.csv`` (as exported from a
requirements tool or a spreadsheet). This script builds ``idle_requirements.nervus``: the idle speed model with the
requirements imported, the ECU subsystem linked to all of them, each test case linked to the requirements it
verifies, and a fourth test case that was missing (IDLE-05, found with the coverage report). It runs the tests
with model coverage and writes the traceability and coverage reports.

Run with ``uv run python examples/idle_requirements.py``.
"""

from __future__ import annotations

from pathlib import Path

from nervus import Diagram, load, save
from nervus.core import Check, TestCase
from nervus.core.requirements import read_csv, trace, write_report

HERE = Path(__file__).parent
LINKS = {  # test case → the requirements it verifies
    "AC compressor on at 5 s": ["IDLE-01", "IDLE-02"],
    "AC compressor on, no feed-forward": ["IDLE-03"],
    "higher idle target": ["IDLE-04"],
}


def build(with_new_test: bool = True) -> Diagram:
    d = load(HERE / "idle_speed_control.nervus")
    d.name = "idle_requirements"
    for req in read_csv(HERE / "data" / "idle_requirements.csv"):
        d.requirements.add(req)
    d.block("ECU").meta["requirements"] = [r.id for r in d.requirements.items]
    for case in d.tests:
        case.requirements = LINKS.get(case.name, [])
    if with_new_test:
        d.tests.append(
            TestCase(
                "large target change: correction limited",
                "Target 1500 rpm: the correction runs into its 15° limit and the engine still settles at 1500 rpm",
                parameters={"rpm_idle": 1500.0},
                checks=[
                    Check("bounds", "ECU/idle_pi", {"lower": -2.0, "upper": 15.0}),
                    Check("final_value", "engine_rpm", {"value": 1500.0, "tolerance": 20.0}),
                ],
                requirements=["IDLE-05"],
            )
        )
    return d


def main() -> None:
    from nervus.coverage import Coverage
    from nervus.testing import run_tests

    for with_new_test in (False, True):
        d = build(with_new_test)
        cov = Coverage()
        results = {r.case.name: r.passed for r in run_tests(d, base_dir=HERE, coverage=cov)}
        label = "with the new test" if with_new_test else "the original tests"
        print(f"--- {label}: {cov.summary().splitlines()[0]}")
        for row in trace(d, results):
            print(f"  {row.requirement.id}  {row.status:15s} {', '.join(row.tests)}")
    save(d, HERE / "idle_requirements.nervus")
    out = HERE / "generated"
    out.mkdir(exist_ok=True)
    write_report(d, out / "idle_traceability.html", results)
    cov.save_html(out / "idle_coverage.html")
    print(f"reports: {out / 'idle_traceability.html'}, {out / 'idle_coverage.html'}")


if __name__ == "__main__":
    main()
