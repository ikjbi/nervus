"""Code generation from the editor."""

import pytest
from PySide6.QtCore import QPointF

from nervus.codegen.sil import find_compiler


def _controller(window):  # type: ignore[no-untyped-def]
    ed = window.editor
    u = ed.add_block("ports.inport", QPointF(0, 0))
    z = ed.add_block("discrete.zero_order_hold", QPointF(150, 0), sample_time=0.01)
    g = ed.add_block("math.gain", QPointF(300, 0), gain=4.0)
    y = ed.add_block("ports.outport", QPointF(450, 0))
    ed.connect_ports(u, 0, z, 0)
    ed.connect_ports(z, 0, g, 0)
    ed.connect_ports(g, 0, y, 0)
    return u, z, g, y


def test_generate_for_model(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _controller(window)
    dlg = window.generate_code()
    assert dlg is not None
    assert dlg.tabs.count() == 3
    assert "untitled_step" in dlg.code.files["untitled.c"]
    dlg.save_to(tmp_path)
    assert (tmp_path / "untitled.h").exists() and (tmp_path / "untitled_report.html").exists()
    dlg.close()


@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
def test_sil_check_from_dialog(window) -> None:  # type: ignore[no-untyped-def]
    _controller(window)
    dlg = window.generate_code()
    dlg.run_sil()
    assert "PASSED" in dlg.sil_label.text()
    dlg.close()


def test_generate_selected_subsystem_and_error(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    _u, z, g, _y = _controller(window)
    integ = window.editor.add_block("continuous.integrator", QPointF(600, 0))
    window.editor.connect_ports(g, 0, integ, 0)
    with qtbot.waitSignal(window.codegen.errorOccurred):
        assert window.generate_code() is None  # the integrator has continuous states
    sub = window.editor.create_subsystem([z, g])
    window.scene.select_blocks([sub.name])
    dlg = window.generate_code()
    assert dlg is not None and dlg.code.name == "Subsystem"
    dlg.close()
