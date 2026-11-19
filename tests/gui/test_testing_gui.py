"""Test Manager and Data Inspector in the editor."""

from pathlib import Path

from nervus.core import Check, Signal, TestCase
from nervus.gui.views.test_manager import TestCaseDialog, format_points, parse_args, parse_points

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


def _case() -> TestCase:
    return TestCase(
        "step_60",
        inputs={},
        stop_time=2.0,
        checks=[
            Check("reaches", "plate_angle", {"value": 59.0, "before": 0.5}),
            Check("max", "plate_angle", {"value": 65}),
        ],
    )


def test_point_and_arg_parsing() -> None:
    assert parse_points("0: 5, 0.2: 60, 1.2: [1 2]") == [(0.0, 5.0), (0.2, 60.0), (1.2, [1.0, 2.0])]
    assert parse_args("lower=0, upper=1.5, path=base.nervres") == {"lower": 0.0, "upper": 1.5, "path": "base.nervres"}
    assert format_points(Signal.steps([(0, 1.0), (1, 2.0)])) == "0.0: 1.0, 1.0: 2.0"


def test_tests_are_undoable_and_saved(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "throttle_pi.nervus")
    window.editor.set_tests([_case()], "Add test")
    assert window.test_panel.tree.topLevelItemCount() == 1
    window.editor.undo_stack.undo()
    assert window.test_panel.tree.topLevelItemCount() == 0
    window.editor.undo_stack.redo()
    assert window.files.save_as(tmp_path / "t")
    window.files.new()
    window.files.open(tmp_path / "t.nervus")
    assert [c.name for c in window.diagram_model.root.tests] == ["step_60"]


def test_run_tests_in_background(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "throttle_pi.nervus")
    failing = TestCase("too_fast", checks=[Check("reaches", "plate_angle", {"value": 59.0, "before": 0.21})])
    window.editor.set_tests([_case(), failing])
    with qtbot.waitSignal(window.tests.finished, timeout=30000):
        window.test_panel.run_all()
    assert window.tests.results["step_60"].passed
    assert not window.tests.results["too_fast"].passed
    items = [window.test_panel.tree.topLevelItem(i) for i in range(2)]
    assert items[0].text(1) == "✓ pass" and items[1].text(1) == "✗ fail"
    assert window.editor.editing_enabled
    labels = [r.label for r in window.sim_model.runs]
    assert "test: step_60" in labels and "test: too_fast" in labels
    window._open_test_result("step_60")
    inspector = window._inspector
    assert inspector is not None
    assert inspector.checked_run_labels() == ["test: step_60"]
    assert inspector.checked_signals() == ["plate_angle"]


def test_inspector_compares_runs(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "throttle_pi.nervus")
    for kp in (1.5, 3.0):
        window.editor.update_variable("Kp", value=kp)
        with qtbot.waitSignal(
            window.simulation.sim_model.stateChanged, timeout=20000, check_params_cb=lambda s: s.value == "finished"
        ):
            window.simulation.run()
    inspector = window.show_inspector()
    inspector.select(["Run 1", "Run 2"], ["plate_angle"])
    assert "max |Δ|" in inspector.summary.text()
    inspector.diff.setChecked(True)
    assert len(inspector.plot.getPlotItem().listDataItems()) == 1


def test_case_dialog_roundtrip(qtbot) -> None:  # type: ignore[no-untyped-def]
    case = TestCase(
        "c",
        inputs={"u": Signal.steps([(0, 1.0), (2, 3.0)])},
        parameters={"Kp": 2.0},
        checks=[Check("bounds", "y", {"lower": 0.0, "upper": 1.0})],
    )
    dlg = TestCaseDialog(case, ["u", "v"])
    qtbot.addWidget(dlg)
    built = dlg.build()
    assert built.to_dict() == case.to_dict()


def test_coverage_after_test_run(window, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "idle_speed_control.nervus")
    with qtbot.waitSignal(window.tests.finished, timeout=60000):
        window.test_panel.run_all()
    assert window.tests.coverage is not None and window.tests.coverage.total > 0
    assert window.test_panel.coverage_label.text().startswith("Coverage")
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    path = window.test_panel.open_coverage_report()
    assert path is not None and opened and "never" not in opened[0]
