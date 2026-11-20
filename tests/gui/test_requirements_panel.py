"""Requirements panel: add, edit, rename (links follow), import, link blocks and tests, status, report."""

from nervus import Diagram
from nervus.blocks import Gain, Scope, Step
from nervus.core import Check, TestCase


def test_requirements_workflow(window, qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("m")
    d.chain(d.add(Step(), name="u"), d.add(Gain(gain=2.0), name="k"), d.add(Scope(), name="sc"))
    window.diagram_model.set_diagram(d)
    root = window.diagram_model.root
    panel = window.requirements_panel
    csv = tmp_path / "reqs.csv"
    csv.write_text("id,title,text\nR1,Gain,Output is twice the input\nR2,Spare,Not done\n")
    assert panel.import_csv(str(csv)) == ["R1", "R2"]
    assert panel.table.rowCount() == 2 and panel.table.item(1, 5).text() == "not implemented"
    # Link a block and a test case; run the tests.
    assert window.link_requirements(root.block("k"), ["R1"])
    assert panel.table.item(0, 3).text() == "k" and panel.table.item(0, 5).text() == "not tested"
    window.editor.set_tests([TestCase("gain", checks=[Check("bounds", "k", {"upper": 2.0})], requirements=["R1"])])
    assert panel.table.item(0, 5).text() == "not run"
    with qtbot.waitSignal(window.tests.finished, timeout=20000):
        window.test_panel.run_all()
    assert panel.table.item(0, 5).text() == "verified" and "1 of 2 verified" in panel.summary.text()
    # Rename: the block and the test follow.
    panel.table.item(0, 0).setText("GAIN-1")
    assert "GAIN-1" in root.requirements and root.block("k").meta["requirements"] == ["GAIN-1"]
    assert root.tests[0].requirements == ["GAIN-1"]
    window.editor.undo_stack.undo()
    assert "R1" in root.requirements and window.diagram_model.root.block("k").meta["requirements"] == ["R1"]
    # Add, edit, delete, report.
    panel._add()
    assert "REQ-001" in window.diagram_model.root.requirements
    panel.table.selectRow(2)
    panel._delete()
    assert "REQ-001" not in window.diagram_model.root.requirements
    html = panel.report(str(tmp_path / "trace.html")).read_text()
    assert "verified" in html and "R2" in html
