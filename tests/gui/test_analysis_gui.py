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
