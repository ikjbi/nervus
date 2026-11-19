"""Run test cases and compare simulation results.

Typical use, e.g. inside pytest for regression tests::

    from nervus import load
    from nervus.testing import run_tests

    model = load("throttle_ecu.nervus")
    for r in run_tests(model, base_dir="examples"):
        print(r.summary())
        assert r.passed
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.diagram import Diagram
from nervus.core.errors import NervusError
from nervus.core.testcase import Check, TestCase
from nervus.core.types import Array
from nervus.core.workspace import ParameterSet
from nervus.sim.result import SimResult
from nervus.sim.simulator import simulate


@dataclass
class CheckResult:
    check: Check
    passed: bool
    message: str


@dataclass
class TestResult:
    __test__ = False

    case: TestCase
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    result: SimResult | None = None
    error: str = ""

    def summary(self) -> str:
        head = f"{'PASS' if self.passed else 'FAIL'}  {self.case.name}"
        if self.error:
            return f"{head}: {self.error.splitlines()[0]}"
        lines = [head]
        for c in self.checks:
            lines.append(f"    {'✓' if c.passed else '✗'} {c.check.describe()}: {c.message}")
        return "\n".join(lines)


def _window(res: SimResult, data: Array, check: Check) -> tuple[Array, Array]:
    t0 = float(check.args.get("t_from", -np.inf))
    t1 = float(check.args.get("t_to", np.inf))
    mask = (res.t >= t0) & (res.t <= t1)
    return res.t[mask], data[mask]


def evaluate_check(check: Check, res: SimResult, base_dir: Path | None = None) -> CheckResult:
    try:
        data = res[check.signal]
    except KeyError:
        return CheckResult(check, False, f"no signal named {check.signal!r}")
    a = check.args
    if check.kind == "bounds":
        t, y = _window(res, data, check)
        lo, hi = float(a.get("lower", -np.inf)), float(a.get("upper", np.inf))
        bad = (y < lo) | (y > hi)
        if np.any(bad):
            k = int(np.argmax(bad.any(axis=1) if bad.ndim > 1 else bad))
            return CheckResult(check, False, f"violated at t = {t[k]:g} (value {np.ravel(y[k])[0]:g})")
        return CheckResult(check, True, f"min {np.min(y):g}, max {np.max(y):g}")
    if check.kind == "final_value":
        last = float(np.ravel(data[-1])[0])
        tol = float(a.get("tolerance", 1e-6))
        ok = abs(last - float(a["value"])) <= tol
        return CheckResult(check, ok, f"final value {last:g}")
    if check.kind == "reaches":
        target, before = float(a["value"]), float(a.get("before", np.inf))
        flat = data if data.ndim == 1 else data[:, 0]
        hit = flat <= target if a.get("direction") == "below" else flat >= target
        if not np.any(hit):
            return CheckResult(check, False, "never reached")
        t_hit = float(res.t[int(np.argmax(hit))])
        return CheckResult(check, t_hit <= before, f"reached at t = {t_hit:g}")
    if check.kind in ("max", "min"):
        v = float(np.max(data) if check.kind == "max" else np.min(data))
        ok = v <= float(a["value"]) if check.kind == "max" else v >= float(a["value"])
        return CheckResult(check, ok, f"{check.kind} = {v:g}")
    # baseline
    path = Path(a["path"])
    if base_dir is not None and not path.is_absolute():
        path = base_dir / path
    try:
        baseline = SimResult.load(path)
    except (OSError, NervusError, KeyError, ValueError) as exc:
        return CheckResult(check, False, f"cannot load baseline: {exc}")
    diff = compare_results(res, baseline, [check.signal]).get(check.signal, np.inf)
    tol = float(a.get("tolerance", 1e-6))
    return CheckResult(check, diff <= tol, f"max difference {diff:.3g}")


def run_test(diagram: Diagram, case: TestCase, base_dir: str | Path | None = None, coverage: Any = None) -> TestResult:
    """Run one test case on ``diagram``. Parameter overrides only apply to this run; the model is unchanged."""
    base = Path(base_dir) if base_dir is not None else None
    try:
        params = {}
        if case.parameter_set:
            ps_path = Path(case.parameter_set)
            if base is not None and not ps_path.is_absolute():
                ps_path = base / ps_path
            params.update({k: v for k, v in ParameterSet.load(ps_path).values.items() if k in diagram.workspace})
        params.update(case.parameters)
        res = simulate(diagram, case.stop_time, params=params or None, inputs=dict(case.inputs), coverage=coverage)
    except NervusError as exc:
        return TestResult(case, False, error=str(exc))
    except Exception as exc:
        return TestResult(case, False, error=f"{exc}\n{traceback.format_exc()}")
    checks = [evaluate_check(c, res, base) for c in case.checks]
    return TestResult(case, all(c.passed for c in checks), checks, res)


def run_tests(
    diagram: Diagram,
    cases: list[TestCase] | None = None,
    base_dir: str | Path | None = None,
    coverage: Any = None,
) -> list[TestResult]:
    """Run the given test cases, or all test cases stored with the model. Pass a
    :class:`nervus.coverage.Coverage` to measure the model coverage of the whole suite."""
    return [run_test(diagram, c, base_dir, coverage) for c in (cases if cases is not None else diagram.tests)]


def compare_results(a: SimResult, b: SimResult, signals: list[str] | None = None) -> dict[str, float]:
    """Largest absolute difference per signal, with ``b`` interpolated onto ``a``'s time points.

    Signals are compared by name; with ``signals=None`` every signal present in both results is compared.
    """
    names = signals if signals is not None else [n for n in a.names() if n in b]
    out: dict[str, float] = {}
    for name in names:
        if name not in a or name not in b:
            out[name] = float("inf")
            continue
        ya, yb = np.atleast_2d(a[name].T).T, np.atleast_2d(b[name].T).T
        if ya.ndim == 1:
            ya = ya[:, None]
        if yb.ndim == 1:
            yb = yb[:, None]
        if ya.shape[1] != yb.shape[1] or a.t.size == 0 or b.t.size == 0:
            out[name] = float("inf")
            continue
        yb_on_a = np.column_stack([np.interp(a.t, b.t, yb[:, j]) for j in range(yb.shape[1])])
        out[name] = float(np.max(np.abs(ya - yb_on_a)))
    return out
