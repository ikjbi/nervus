"""The integer-only option in the code generation dialog."""

import sys
from pathlib import Path

import pytest

from nervus.codegen.sil import find_compiler

sys.path.insert(0, str(Path(__file__).parent.parent))
from test_integer_code import _sensor_chain

EXAMPLES = Path(__file__).parent.parent.parent / "examples"
pytestmark = pytest.mark.skipif(find_compiler() is None, reason="no C compiler")


def test_integer_box(window) -> None:  # type: ignore[no-untyped-def]
    window.diagram_model.set_diagram(_sensor_chain())
    dlg = window.generate_code()
    dlg.integer_box.setChecked(True)
    assert dlg.code.integer_only and "nv_div_" in dlg.code.files["temp.c"]
    dlg.run_sil()
    assert dlg.sil_label.text().startswith("✓"), dlg.sil_label.text()
    dlg.close()


def test_double_model_is_refused(window) -> None:  # type: ignore[no-untyped-def]
    window.files.open(EXAMPLES / "throttle_ecu.nervus")
    window.scene.select_blocks(["ECU"])
    dlg = window.generate_code()
    dlg.integer_box.setChecked(True)
    assert not dlg.integer_box.isChecked() and not dlg.code.integer_only
    assert "not supported in integer-only code" in window.sim_model._error
    dlg.close()
