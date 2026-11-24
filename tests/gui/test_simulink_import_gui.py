"""File > Import Simulink Model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from test_simulink_import import _slx


def test_import_from_the_editor(window, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert window.import_simulink(str(_slx(tmp_path)), show_report=False)
    assert window.diagram_model.root.name == "loop" and "Imported loop.slx" in window.status_label.text()
