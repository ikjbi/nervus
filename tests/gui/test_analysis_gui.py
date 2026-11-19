from PySide6.QtCore import QPointF


def test_analysis_dialog(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    u = ed.add_block("ports.inport", QPointF(0, 0))
    tf = ed.add_block("continuous.transfer_function", QPointF(150, 0), numerator=[3.0], denominator=[1.0, 2.0])
    y = ed.add_block("ports.outport", QPointF(300, 0))
    ed.connect_ports(u, 0, tf, 0)
    ed.connect_ports(tf, 0, y, 0)
    dlg = window.show_analysis()
    lin = dlg.run()
    assert lin is not None and abs(lin.dc_gain() - 1.5) < 1e-6
    assert "stable" in dlg.info.text()
    assert len(dlg.mag.getPlotItem().listDataItems()) == 1
    assert len(dlg.step.getPlotItem().listDataItems()) == 2  # open and closed loop
    assert dlg.nyq.getPlotItem().listDataItems() and dlg.locus.getPlotItem().listDataItems()
    assert not dlg.pid_tune.isEnabled()  # no PID block in this model
    dlg.close()


def test_pid_tuning_tab(window) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    window.files.open(Path(__file__).parent.parent.parent / "examples" / "throttle_pi.nervus")
    ws = window.diagram_model.root.workspace
    before = (ws["Kp"], ws["Ki"])
    dlg = window.show_analysis()
    assert dlg.pid_block.currentText() == "throttle_pi"
    gains = dlg.tune()
    assert gains is not None and gains.phase_margin >= 60.0
    assert gains.crossover <= 2 * 3.1416 / (20 * 0.01) + 1e-6  # limited by the 10 ms task
    assert "Tuned" in dlg.pid_info.text() and len(dlg.pid_plot.getPlotItem().listDataItems()) == 2
    assert dlg.apply_gains()
    assert (ws["Kp"], ws["Ki"]) == (gains.P, gains.I) != before  # the gains are workspace variables
    window.editor.undo_stack.undo()
    window.editor.undo_stack.undo()
    assert (ws["Kp"], ws["Ki"]) == before
    dlg.close()


def test_advisor_dialog(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    s = ed.add_block("sources.sine", QPointF(0, 0))
    p = ed.add_block("math.product", QPointF(150, 0), ops="*/")
    ed.connect_ports(s, 0, p, 0)
    ed.connect_ports(s, 0, p, 1)
    ed.connect_ports(p, 0, ed.add_block("sinks.scope", QPointF(300, 0)), 0)
    dlg = window.show_advisor()
    assert any(f.rule == "division" for f in dlg.findings)
    item = next(
        dlg.tree.topLevelItem(i)
        for i in range(dlg.tree.topLevelItemCount())
        if dlg.tree.topLevelItem(i).text(1) == "division"
    )
    dlg._clicked(item)
    assert [b.name for b in window.scene.selected_blocks()] == [p.name]
    dlg.close()
