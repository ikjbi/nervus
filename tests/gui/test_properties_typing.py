"""Typing parameter values into the Properties panel, as in Tutorial 1."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit

from nervus.core import Variable


def _field(panel, label: str) -> QLineEdit | None:  # type: ignore[no-untyped-def]
    for form in panel.findChildren(QFormLayout):
        for r in range(form.rowCount()):
            lab = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
            fld = form.itemAt(r, QFormLayout.ItemRole.FieldRole)
            if lab is None or fld is None or not isinstance(lab.widget(), QLabel):
                continue
            if lab.widget().text().split("[")[0].strip().rstrip(":") == label and isinstance(fld.widget(), QLineEdit):
                return fld.widget()
    return None


def test_pid_gains_from_the_workspace(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    """Enter in a field applies the value and rebuilds the panel; that used to crash the editor (the panel touched
    the field it had just deleted)."""
    root = window.diagram_model.root
    root.workspace.add(Variable("Kp", 300.0))
    root.workspace.add(Variable("Ki", 0.0))
    block = window.editor.add_block("control.pid", QPointF(0, 0))
    window.scene.select_blocks([block.name])
    for name, value in (("P", "Kp"), ("I", "Ki")):
        edit = _field(window.properties, name)
        assert edit is not None, [w.text() for w in window.properties.findChildren(QLabel)]
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, value)
        QTest.keyClick(edit, Qt.Key.Key_Return)
        qtbot.wait(10)
        assert block.param_source(name) == value
    assert window.properties.error.text() == ""
