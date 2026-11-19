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
